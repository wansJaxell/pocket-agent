"""The application: the agent and everything around it (brains, Telegram, jobs) as plain methods.

The web panel (panel.py) is only a thin HTTP layer over App, so all of this is tested without
a browser, a model or Telegram.
"""

import re
import secrets
import threading
import time
from collections import deque
from datetime import datetime

import requests

from pocketagent import __version__, autostart, vault
from pocketagent import config as cfg
from pocketagent.agent import Agent
from pocketagent.approvals import ApprovalEngine, AuditLog, RuleStore
from pocketagent.config import BrainConfig, Config, TelegramConfig
from pocketagent.jobs import JobQueue
from pocketagent.llm import (PROVIDERS, Brain, BrainError, Router, brain_label, check_key, list_models, probe,
                             problem_of)
from pocketagent import media
from pocketagent.media import MediaError, Studio
from pocketagent.memory import ConversationStore, DecisionLog, IdentityStore, NoteStore, ReminderStore
from pocketagent.oauth import authorize_url, exchange_code, make_verifier
from pocketagent.setup_wizard import TELEGRAM_API, detect_local_models, wait_for_owner
from pocketagent.tools import ToolRegistry

FREE_ROUTER = "openrouter/free"          # OpenRouter's own router over its free models: a last resort
BUSY = {402, 408, 429, 500, 502, 503, 504}  # a listed model may still be added while it is busy
SYNC_EVERY = 12 * 3600                    # seconds between automatic free-model syncs

TELEGRAM_TOKEN = re.compile(r"^\d+:[A-Za-z0-9_-]+$")   # also keeps a pasted token from bending the API URL


class Runtime:
    """Everything the agent needs, built from the saved config."""

    def __init__(self, config: Config, brain=None, http=None):
        self.config = config
        self.registry = ToolRegistry()
        self.registry.load_builtin()
        self.registry.load_folder(cfg.user_skills_dir())
        memory = cfg.memory_dir()
        self.conversations = ConversationStore(memory, keep=config.history_messages)
        self.notes = NoteStore(memory)
        self.reminders = ReminderStore(memory)
        self.identity = IdentityStore(memory, default_name=config.agent_name)
        self.decisions = DecisionLog(memory)
        self.rules = RuleStore(memory)
        self.audit = AuditLog(cfg.logs_dir(), echo=True)
        self.approvals = ApprovalEngine(self.rules, self.audit, enabled=lambda: config.computer_use,
                                        timeout=config.approval_timeout)
        self.studio = Studio(config, http=http or requests)
        self.agent = Agent(config, brain or Router(config, http=http), self.registry, self.conversations,
                           self.notes, self.reminders, cfg.workspace_dir(),
                           identity=self.identity, decisions=self.decisions,
                           approvals=self.approvals, audit=self.audit, studio=self.studio)


def start_reminder_loop(runtime: Runtime, notify, stop: threading.Event) -> None:
    def loop():
        while not stop.is_set():
            for item in runtime.reminders.pop_due():
                notify(item["chat_id"], f"⏰ Reminder: {item['text']}")
            stop.wait(15)
    threading.Thread(target=loop, daemon=True).start()


class PanelError(Exception):
    """Something the user can fix (a rejected key, an empty name...): the panel shows the message."""


def mask(key: str) -> str:
    return f"{key[:4]}…{key[-4:]}" if len(key) > 12 else "••••"


class App:
    WRONG_PASSWORD_DELAY = 1.0      # seconds: makes guessing the panel password slow

    def __init__(self, config: Config, http=None, runtime: Runtime | None = None):
        self.config = config
        self.http = http or requests
        self.lock = threading.RLock()
        self.runtime = runtime or Runtime(config, http=self.http)
        self.jobs = JobQueue()
        self.notices: deque[dict] = deque(maxlen=20)      # reminders and news for the panel
        self.telegram_status = "connected" if config.telegram_ready else "idle"
        self.telegram_thread: threading.Thread | None = None
        self._telegram_pending = ""                       # bot @name while waiting for START
        self.bot = None
        self._bot_stop: threading.Event | None = None
        self._verifier: str | None = None                 # OpenRouter login in progress
        self._catalog: dict[str, dict[str, dict]] = {}    # provider -> model id -> what the list said
        self._services = threading.Event()
        self._stop = threading.Event()
        self.sessions: set[str] = set()                   # browsers that gave the panel password
        approvals = self.runtime.approvals                # approval requests also go to Telegram
        approvals.notifiers.append(lambda pending: self.bot and self.bot.ask_approval(pending))
        approvals.resolved.append(lambda pending: self.bot and self.bot.approval_resolved(pending))
        self.router = self.runtime.agent.brain if isinstance(self.runtime.agent.brain, Router) else None
        if self.router:
            self.router.on_problem = self._model_problem

    def save(self) -> None:
        with self.lock:
            cfg.save(self.config)

    def notice(self, text: str) -> None:
        self.notices.append({"time": datetime.now().isoformat(timespec="seconds"), "text": text})

    @property
    def locked(self) -> bool:
        return self.config.locked

    # ---------- what the panel shows ----------
    def state(self) -> dict:
        c = self.config
        return {
            "app": "PocketAgent", "version": __version__, "language": c.language,
            "identity": self.runtime.identity.get(),
            "providers": [self._provider(pid) for pid in PROVIDERS],
            "custom_url": c.custom_url,
            "brains": [self._brain(i, b) for i, b in enumerate(c.chain())],
            "limits": self.router.status() if self.router else {},
            "telegram": self._telegram(),
            "access": c.access,
            "free_sync": {k: v for k, v in c.free_sync.items() if k != "skip"},
            "autostart": {"supported": autostart.supported(), "enabled": autostart.is_enabled()},
            "setup": {"brain": c.brain_ready, "telegram": c.telegram_ready},
            "memory": {"notes": len(self.runtime.notes.all()), "decisions": len(self.runtime.decisions.all())},
            "specialists": self._specialists(),
            "computer_use": c.computer_use,
            "approvals": self.runtime.approvals.waiting(),
            "rules": self.runtime.rules.all(),
            "audit": self.runtime.audit.recent(40),
            "jobs": self.jobs.recent(10),
            "notices": list(self.notices),
        }

    def locked_state(self) -> dict:
        """All a browser sees before it gives the panel password."""
        return {"app": "PocketAgent", "version": __version__, "locked": True, "language": self.config.language,
                "identity": {"name": self.runtime.identity.get()["name"]}}

    def _provider(self, pid: str) -> dict:
        p, key = PROVIDERS[pid], self.config.keys.get(pid, "")
        return {"id": pid, "name": p.name, "label": p.label, "needs_key": p.needs_key, "key_url": p.key_url,
                "oauth": p.oauth, "trains_on_data": p.trains_on_data, "local": p.local,
                "suggested_model": p.suggested_model, "has_key": bool(key), "key_hint": mask(key) if key else "",
                "enabled": pid not in self.config.disabled_providers}

    def _brain(self, index: int, b: BrainConfig) -> dict:
        """b comes from config.chain(), so its key is filled in (never shown, only checked)."""
        return {"index": index, "provider": b.provider, "model": b.model, "label": brain_label(b),
                "free": b.free, "native_tools": b.native_tools, "auto": b.auto, "enabled": b.enabled,
                "problem": self.router.usable(b) if self.router else ""}

    def _telegram(self) -> dict:
        username = self.config.telegram.username or self._telegram_pending
        return {"status": self.telegram_status, "connected": self.config.telegram_ready, "username": username,
                "link": f"https://t.me/{username}" if username else ""}

    # ---------- step 1: brains ----------
    @staticmethod
    def _provider_info(provider: str):
        if provider not in PROVIDERS:
            raise PanelError(f"Unknown provider '{provider}'.")
        return PROVIDERS[provider]

    def local_models(self) -> dict:
        return detect_local_models(self.http)

    def save_key(self, provider: str, key: str, base_url: str = "") -> dict:
        """Check a key by listing the provider's models; keep it only if the provider accepts it."""
        info = self._provider_info(provider)
        key, base_url = (key or "").strip(), (base_url or "").strip().rstrip("/")
        if provider == "custom" and not base_url.startswith(("http://", "https://")):
            raise PanelError("Enter the API address first (it usually ends with /v1).")
        if provider != "custom" and not key:
            raise PanelError("Paste the key first.")
        try:
            check_key(provider, key, self.http)
            models = list_models(provider, key, base_url, self.http)
            self._catalog[provider] = {m["id"]: m for m in models}
        except BrainError as error:
            if error.status in (401, 403):
                raise PanelError(f"{info.name} rejected this key ({error}).") from None
            if provider != "custom":
                raise PanelError(f"Could not check the key: {error}") from None
            models = []          # many self-hosted servers have no model list: type the model name
        with self.lock:
            if provider == "custom":
                self.config.custom_url = base_url
            if key:
                self.config.keys[provider] = key
            self.save()
        return {"models": models}

    def delete_key(self, provider: str) -> None:
        """Forget a saved key (a wrong one, or a provider you no longer use)."""
        self._provider_info(provider)
        with self.lock:
            if self.config.keys.pop(provider, None) is None:
                raise PanelError("There is no saved key for this provider.")
            self.save()
        self._catalog.pop(provider, None)
        self.runtime.audit.write("key_deleted", provider=provider)

    def set_provider_enabled(self, provider: str, enabled: bool) -> None:
        """Switch a whole provider off (all its brains are skipped) or on again."""
        self._provider_info(provider)
        with self.lock:
            disabled = [p for p in self.config.disabled_providers if p != provider]
            self.config.disabled_providers = disabled if enabled else disabled + [provider]
            self.save()
        self.runtime.audit.write("provider_switched", provider=provider, enabled=bool(enabled))

    def toggle_brain(self, index, enabled: bool) -> None:
        with self.lock:
            brains, index = self._brain_list(index)
            brains[index].enabled = bool(enabled)
            self.config.set_brains(brains)
            self.save()

    def _model_problem(self, brain: BrainConfig, problem: str, error: Exception) -> None:
        """A brain failed in a way that will not go away by itself: switch it off and say so."""
        if problem != "app_only":
            return
        with self.lock:
            for b in self.config.brains():
                if (b.provider, b.model) == (brain.provider, brain.model):
                    b.enabled = False
            skip = self.config.free_sync.setdefault("skip", [])
            if brain.model not in skip:
                skip.append(brain.model)
            self.save()
        self.notice(f"{brain.model} is only for some other apps on OpenRouter: it was switched off.")
        self.runtime.audit.write("brain_switched_off", model=brain.model, reason=problem)

    def models(self, provider: str) -> dict:
        info = self._provider_info(provider)
        if info.needs_key and provider not in self.config.keys:
            raise PanelError(f"Save a key for {info.name} first.")
        base_url = self.config.custom_url if provider == "custom" else ""
        try:
            models = list_models(provider, self.config.keys.get(provider, ""), base_url, self.http)
        except BrainError as error:
            raise PanelError(f"Could not get the model list: {error}") from None
        self._catalog[provider] = {m["id"]: m for m in models}
        return {"models": models}

    def add_brain(self, provider: str, model: str, free: bool = True) -> dict:
        """Test a brain and add it at the end of the priority list."""
        info = self._provider_info(provider)
        model = (model or "").strip()
        if not model:
            raise PanelError("Choose a model first.")
        if info.needs_key and provider not in self.config.keys:
            raise PanelError(f"Save a key for {info.name} first.")
        base_url = self.config.custom_url if provider == "custom" else info.base_url
        if not base_url:
            raise PanelError("Enter the API address first.")
        brain = BrainConfig(provider, base_url, model, free=bool(free))
        known, warning = self._catalog.get(provider, {}).get(model), ""
        try:
            answer, brain.native_tools = probe(self.config.with_key(brain),
                                               lambda c: Brain(c, http=self.http, retries=0),
                                               known_tools=known.get("tools") if known else None)
        except Exception as error:
            status = getattr(error, "status", None)
            if isinstance(error, BrainError) and problem_of(error) == "app_only":
                with self.lock:
                    self.config.free_sync.setdefault("skip", []).append(model)
                    self.save()
                self.runtime.audit.write("brain_add_failed", provider=provider, model=model, error=str(error))
                raise PanelError(f"{model} is kept for other apps only by OpenRouter (\"agentic harnesses\"): "
                                 "PocketAgent cannot use it. Choose another model.") from None
            if status not in BUSY or known is None:
                self.runtime.audit.write("brain_add_failed", provider=provider, model=model, error=str(error))
                raise PanelError(f"{brain_label(brain)} did not answer: {error}") from None
            # free models are often busy; the provider listed this one, so keep it: fallbacks cover the busy times
            answer, brain.native_tools = "", known.get("tools") is not False
            warning = f"{brain_label(brain)} is busy right now (HTTP {status}); it was added and answers when it can."
        with self.lock:
            brains = [b for b in self.config.brains() if (b.provider, b.model) != (provider, model)]
            self.config.set_brains(brains + [brain])
            self.save()
        return {**self._brain(len(brains), brain), "answer": answer, "warning": warning}

    def _brain_list(self, index) -> tuple[list[BrainConfig], int]:
        brains = self.config.brains()
        try:
            index = int(index)
        except (TypeError, ValueError):
            index = -1
        if not 0 <= index < len(brains):
            raise PanelError("There is no such brain in the list.")
        return brains, index

    def move_brain(self, index, delta) -> None:
        with self.lock:
            brains, index = self._brain_list(index)
            target = max(0, min(len(brains) - 1, index + (1 if int(delta) > 0 else -1)))
            brains[index].auto = False          # placed by hand: the free-model sync keeps it
            brains.insert(target, brains.pop(index))
            self.config.set_brains(brains)
            self.save()

    def remove_brain(self, index) -> None:
        with self.lock:
            brains, index = self._brain_list(index)
            removed = brains.pop(index)
            if removed.auto:                    # the free-model sync must not bring it back
                self.config.free_sync.setdefault("skip", []).append(removed.model)
            self.config.set_brains(brains)
            self.save()

    def test_brain(self, index) -> dict:
        brains, index = self._brain_list(index)
        try:
            answer, native = probe(self.config.with_key(brains[index]), lambda c: Brain(c, http=self.http, retries=0))
        except Exception as error:
            return {"ok": False, "message": f"{type(error).__name__}: {error}"}
        return {"ok": True, "message": answer, "native_tools": native}

    def sync_free_models(self, count: int | None = None, min_context: int | None = None) -> dict:
        """Put OpenRouter's best free models (tool calling, biggest context first) after the
        user's own brains, as automatic fallbacks; the previous automatic ones are replaced."""
        if "openrouter" not in self.config.keys:
            raise PanelError("Connect OpenRouter first (step 1), then add its free models.")
        if "openrouter" in self.config.disabled_providers:
            raise PanelError("OpenRouter is switched off: switch it on first.")
        settings = self.config.free_sync
        count = settings.get("count", 5) if count is None else max(0, min(int(count), 20))
        min_context = settings.get("min_context", 0) if min_context is None else max(0, int(min_context))
        try:
            models = list_models("openrouter", self.config.keys["openrouter"], http=self.http)
        except BrainError as error:
            raise PanelError(f"Could not get OpenRouter's model list: {error}") from None
        self._catalog["openrouter"] = {m["id"]: m for m in models}
        with self.lock:
            manual = [b for b in self.config.brains() if not b.auto]
            taken = {b.model for b in manual if b.provider == "openrouter"} | set(settings.get("skip", []))
            usable = [m for m in models if m["free"] and m["tools"] and m["id"] not in taken
                      and m["id"] != FREE_ROUTER and (m["context"] or 0) >= min_context]
            usable.sort(key=lambda m: (-(m["context"] or 0), -(m["created"] or 0)))
            chosen = [m["id"] for m in usable[:count]]
            if FREE_ROUTER in self._catalog["openrouter"] and FREE_ROUTER not in taken:
                chosen.append(FREE_ROUTER)
            before = [b.model for b in self.config.brains() if b.auto]
            base_url = PROVIDERS["openrouter"].base_url
            self.config.set_brains(manual + [BrainConfig("openrouter", base_url, model_id, auto=True)
                                             for model_id in chosen])
            settings.update(count=count, min_context=min_context, last=datetime.now().isoformat(timespec="seconds"))
            self.save()
        result = {"added": [m for m in chosen if m not in before], "removed": [m for m in before if m not in chosen],
                  "count": len(chosen)}
        self.runtime.audit.write("free_models_synced", **result)
        return result

    def set_free_sync(self, enabled: bool, count=None, min_context=None) -> dict:
        with self.lock:
            settings = self.config.free_sync
            settings["enabled"] = bool(enabled)
            if count is not None:
                settings["count"] = max(0, min(int(count), 20))
            if min_context is not None:
                settings["min_context"] = max(0, int(min_context))
            self.save()
        return {k: v for k, v in settings.items() if k != "skip"}

    def _free_sync_due(self) -> bool:
        settings = self.config.free_sync
        if (not settings.get("enabled") or self.locked or "openrouter" not in self.config.keys
                or "openrouter" in self.config.disabled_providers):
            return False
        try:
            return (datetime.now() - datetime.fromisoformat(settings.get("last") or "")).total_seconds() > SYNC_EVERY
        except ValueError:
            return True

    def _free_sync_loop(self) -> None:
        while not self._stop.wait(5):
            if self._free_sync_due():
                try:
                    result = self.sync_free_models()
                    if result["added"] or result["removed"]:
                        self.notice(f"Free OpenRouter models updated: +{len(result['added'])} −{len(result['removed'])}")
                except PanelError as error:
                    self.notice(str(error))
            self._stop.wait(1800)

    # ---------- specialists (image, speech, writer) ----------
    def _specialists(self) -> dict:
        key = self.config.keys.get("pollinations", "")
        services = {kind: [{"id": sid, "label": s.label, "paid": s.paid, "key_url": s.key_url}
                           for sid, s in table.items()] for kind, table in (("image", media.IMAGE),
                                                                            ("speech", media.SPEECH))}
        return {**{kind: dict(self.config.media.get(kind) or {}) for kind in ("image", "speech", "writer")},
                "services": services, "pollinations_key": mask(key) if key else ""}

    def set_specialist(self, kind: str, provider: str, model: str = "", voice: str = "") -> dict:
        """Choose who makes images, speech or long texts; an empty provider switches it off."""
        choices = {"image": media.IMAGE, "speech": media.SPEECH, "writer": PROVIDERS}.get(kind)
        if choices is None:
            raise PanelError(f"Unknown specialist '{kind}'.")
        provider, model = (provider or "").strip(), (model or "").strip()
        if provider and provider not in choices:
            raise PanelError(f"Unknown service '{provider}'.")
        if kind == "writer" and provider and not model:
            raise PanelError("Choose the writer's model.")
        with self.lock:
            self.config.media[kind] = {"provider": provider, "model": model if provider else "",
                                       **({"voice": (voice or "").strip()} if kind == "speech" else {})}
            self.save()
        self.runtime.audit.write("specialist", kind=kind, provider=provider, model=model)
        return self._specialists()

    def save_service_key(self, service: str, key: str) -> None:
        if service != "pollinations":
            raise PanelError(f"Unknown service '{service}'.")
        with self.lock:
            if (key or "").strip():
                self.config.keys[service] = key.strip()
            else:
                self.config.keys.pop(service, None)
            self.save()

    def specialist_models(self, kind: str, provider: str) -> dict:
        try:
            return {"models": self.runtime.studio.models(kind, provider)}
        except MediaError as error:
            raise PanelError(str(error)) from None

    def try_specialist(self, kind: str) -> dict:
        """Make a small sample so the user sees the specialist works (paid services are not tried)."""
        studio = self.runtime.studio
        if not studio.ready(kind):
            raise PanelError("Choose a service first.")
        if studio.paid(kind):
            raise PanelError("Paid services are not tried automatically: ask the agent, and approve the cost.")
        from pocketagent.skills.specialists import save_media
        from pocketagent.tools import ToolContext
        ctx = ToolContext(workspace=cfg.workspace_dir())
        try:
            if kind == "image":
                data, extension = studio.image("a small red apple on a wooden table, soft light", "512x512")
                save_media(ctx, "image", data, extension)
            elif kind == "speech":
                data, extension = studio.speech("Hello! This is your PocketAgent speaking.")
                save_media(ctx, "speech", data, extension)
            else:
                return {"text": studio.write("Reply with one short friendly sentence that says you are ready."),
                        "files": []}
        except MediaError as error:
            raise PanelError(str(error)) from None
        return {"text": "", "files": ctx.files}

    def workspace_file(self, relative: str):
        """A file inside the workspace, for the panel to show (nothing outside it)."""
        root = cfg.workspace_dir().resolve()
        target = (root / (relative or "")).resolve()
        if root not in target.parents or not target.is_file():
            raise PanelError("There is no such file in the workspace.")
        return target

    def openrouter_start(self, callback_url: str) -> str:
        self._verifier = make_verifier()
        return authorize_url(callback_url, self._verifier)

    def openrouter_finish(self, code: str) -> None:
        verifier, self._verifier = self._verifier, None
        if not verifier or not code:
            raise PanelError("No OpenRouter login is in progress: start it again from the panel.")
        try:
            key = exchange_code(code, verifier, self.http)
        except BrainError as error:
            raise PanelError(str(error)) from None
        with self.lock:
            self.config.keys["openrouter"] = key
            self.save()

    # ---------- step 2: Telegram ----------
    def telegram_connect(self, token: str) -> dict:
        """Check the bot token, then wait (in the background) for the owner to press START."""
        token = (token or "").strip()
        if not TELEGRAM_TOKEN.match(token):
            raise PanelError("This does not look like a bot token. Copy it again from @BotFather.")
        try:
            me = self.http.get(TELEGRAM_API.format(token=token, method="getMe"), timeout=15).json()
        except Exception as error:
            raise PanelError(f"Could not reach Telegram: {error}") from None
        if not me.get("ok"):
            raise PanelError("Telegram did not accept this token. Copy it again from @BotFather.")
        username = me["result"]["username"]
        self.stop_telegram()        # one poller per token, or Telegram refuses both
        self.telegram_status, self._telegram_pending = "waiting", username
        self.telegram_thread = threading.Thread(target=self._wait_for_owner, args=(token, username), daemon=True)
        self.telegram_thread.start()
        return {"username": username, "link": f"https://t.me/{username}"}

    def _wait_for_owner(self, token: str, username: str) -> None:
        try:
            owner = wait_for_owner(token, self.http, wait_seconds=300)
        except Exception as error:
            self.telegram_status = "error"
            self.notice(f"Telegram: {type(error).__name__}: {error}")
            return
        if owner is None:
            self.telegram_status = "timeout"
            return
        with self.lock:
            self.config.telegram = TelegramConfig(token, owner, username)
            self.save()
        try:
            name = self.runtime.identity.get()["name"]
            self.http.post(TELEGRAM_API.format(token=token, method="sendMessage"), timeout=15, json={
                "chat_id": owner, "text": f"✅ {name} is connected. Only this chat can talk to me."})
        except Exception:
            pass
        self.telegram_status = "connected"
        if self._services.is_set():
            self.start_telegram()

    def telegram_disconnect(self) -> None:
        self.stop_telegram()
        with self.lock:
            self.config.telegram = TelegramConfig()
            self.save()
        self.telegram_status, self._telegram_pending = "idle", ""

    def start_telegram(self) -> None:
        from pocketagent.telegram_bot import TelegramBot
        with self.lock:
            if self.bot or self.locked or not self.config.telegram_ready:
                return
            t, r = self.config.telegram, self.runtime
            self._bot_stop = threading.Event()
            self.bot = TelegramBot(t.token, t.owner_chat_id, r.agent, r.registry, r.conversations, jobs=self.jobs,
                                   approvals=r.approvals, on_stop=self.emergency_stop,
                                   language=lambda: self.config.language)
            threading.Thread(target=self.bot.run_forever, args=(self._bot_stop,), daemon=True).start()
            self.telegram_status = "connected"

    def stop_telegram(self) -> None:
        with self.lock:
            if self._bot_stop:
                self._bot_stop.set()
            self.bot = self._bot_stop = None

    # ---------- step 3: name and personality ----------
    def set_identity(self, name: str, personality: str = "") -> dict:
        name = (name or "").strip()[:40]
        if not name:
            raise PanelError("The agent needs a name.")
        with self.lock:
            identity = self.runtime.identity.set(name, (personality or "")[:2000])
            self.config.agent_name = name          # also kept in config.json for the terminal tools
            self.save()
        return identity

    # ---------- step 4: access (open, or locked with an encrypted vault) ----------
    def new_session(self) -> str:
        session = secrets.token_urlsafe(32)
        self.sessions.add(session)
        return session

    def signed_in(self, session: str | None) -> bool:
        return self.config.access != "locked" or (bool(session) and session in self.sessions and not self.locked)

    def logout(self, session: str | None) -> None:
        self.sessions.discard(session)

    def unlock(self, password: str) -> str:
        """Check the panel password; on the first unlock also decrypt the keys and start Telegram."""
        try:
            if self.locked:
                cfg.unlock(self.config, password or "")
            else:
                cfg.check_password(self.config, password or "")
        except vault.WrongPassword:
            time.sleep(self.WRONG_PASSWORD_DELAY)
            raise PanelError("Wrong password.") from None
        if self._services.is_set():
            self.start_telegram()
        return self.new_session()

    def set_access(self, mode: str, password: str = "") -> str | None:
        """Open mode, or locked mode with a (new) password. Returns a session for this browser."""
        if self.locked:
            raise PanelError("Unlock the panel first.")
        if mode == "open":
            with self.lock:
                cfg.open_access(self.config)
                self.save()
            self.sessions.clear()
            return None
        if mode != "locked":
            raise PanelError("Unknown access mode.")
        if len(password or "") < 8:
            raise PanelError("Choose a password of at least 8 characters.")
        with self.lock:
            cfg.lock_with(self.config, password)
            self.save()
        self.sessions.clear()                    # other browsers must give the new password
        return self.new_session()

    def forget_vault(self) -> None:
        """Forgotten password: delete the encrypted keys; they must be entered again."""
        self.stop_telegram()
        with self.lock:
            cfg.forget_secrets(self.config)
            self.save()
        self.sessions.clear()
        self.telegram_status, self._telegram_pending = "idle", ""

    def set_autostart(self, enabled: bool) -> dict:
        try:
            autostart.enable() if enabled else autostart.disable()
        except autostart.AutostartError as error:
            raise PanelError(str(error)) from None
        return {"supported": autostart.supported(), "enabled": autostart.is_enabled()}

    # ---------- chat ----------

    def set_language(self, language: str) -> None:
        if language not in ("en", "tr"):
            raise PanelError("Unknown language.")
        with self.lock:
            self.config.language = language
            self.save()

    def chat(self, text: str, chat_id: str = "panel") -> dict:
        text = (text or "").strip()
        if not text:
            raise PanelError("Write a message first.")
        return self.jobs.submit(f"panel: {text[:40]}", lambda: self._answer(chat_id, text)).as_dict()

    def _answer(self, chat_id: str, text: str) -> dict:
        answer = self.runtime.agent.run(chat_id, text, source="panel")
        return {"text": answer.text, "brain": answer.brain, "tools": answer.tools, "skipped": answer.skipped,
                "files": answer.files}

    def job(self, job_id) -> dict:
        job = self.jobs.get(job_id)
        if job is None:
            raise PanelError("Unknown job.")
        return job.as_dict()

    def history(self, chat_id: str = "panel") -> list[dict]:
        return self.runtime.conversations.get(chat_id)

    def reset_chat(self, chat_id: str = "panel") -> None:
        self.runtime.conversations.reset(chat_id)

    # ---------- computer use: approvals, rules, stop ----------
    def set_computer_use(self, enabled: bool, by: str = "panel") -> None:
        with self.lock:
            self.config.computer_use = bool(enabled)
            self.save()
        self.runtime.audit.write("computer_use", enabled=bool(enabled), by=by)

    def answer_approval(self, pending_id, approve: bool, remember: bool = False) -> None:
        if not self.runtime.approvals.answer(str(pending_id), approve, remember, by="panel"):
            raise PanelError("This request is no longer waiting for an answer.")

    def delete_rule(self, rule_id) -> None:
        try:
            removed = self.runtime.rules.remove(int(rule_id))
        except (TypeError, ValueError):
            removed = False
        if not removed:
            raise PanelError("There is no such rule.")
        self.runtime.audit.write("rule_deleted", rule=int(rule_id), by="panel")

    def emergency_stop(self, by: str = "panel") -> dict:
        """Stop everything now: waiting jobs, the running turn, approval requests and processes.
        Computer use is switched off and stays off until the user turns it on again."""
        waiting = self.jobs.cancel_waiting()
        running = self.jobs.cancel_running()
        summary = {"jobs": waiting, "running": running, **self.runtime.approvals.stop_everything(by)}
        with self.lock:
            self.config.computer_use = False
            self.save()
        self.notice("🛑 Stopped. Computer use is off.")
        print(f"[stop] by {by}: {summary}")
        if self.bot and by != "telegram":
            try:
                self.bot.send(self.bot.owner, self.bot.stopped_text(summary))
            except Exception:
                pass
        return summary

    # ---------- background services ----------
    def start_services(self) -> None:
        self._services.set()
        self.start_telegram()

        def notify(chat_id, text):
            if self.bot and str(chat_id) not in ("panel", "terminal"):
                self.bot.send(chat_id, text)
            else:
                self.notice(text)
        start_reminder_loop(self.runtime, notify, self._stop)
        threading.Thread(target=self._free_sync_loop, daemon=True).start()

    def stop_services(self) -> None:
        self._stop.set()
        self._services.clear()
        self.stop_telegram()
