"""Talk to the agent from Telegram (phone, tablet or desktop).

Security: only the owner's chat (captured during setup) can use the agent.
Everyone else gets one polite refusal and is ignored; their buttons and commands do nothing.
Uses long polling, so it works on a home computer without a public server.

/dur (or /stop) stops everything at once. Approval requests arrive as messages with buttons.
"""

import threading
import time

import requests

API = "https://api.telegram.org/bot{token}/{method}"
MESSAGE_LIMIT = 4000   # Telegram allows 4096 characters per message

TEXT = {
    "en": {
        "help": "Just write to me: questions, tasks, reminders.\n\n"
                "/dur or /stop  stop everything at once\n"
                "/rules  saved approval rules\n"
                "/reset  forget this conversation\n"
                "/skills  what I can do\n"
                "/help  this message",
        "approval": "🔐 Approval needed", "from": "asked from", "once": "✅ Allow once",
        "rule": "📌 Allow + remember", "deny": "❌ Deny", "always": "⚠️ Always asks: {classes}",
        "after": "⚠️ Comes after reading untrusted content: {sources}",
        "approved": "✅ Allowed", "approved_rule": "✅ Allowed + rule saved", "denied": "❌ Denied",
        "stale": "This request is no longer waiting.", "ended": "⌛ Ended",
        "stopped": "🛑 Stopped everything: {jobs} waiting job(s) cancelled, {approvals} approval(s) denied, "
                   "{processes} process(es) ended. Computer use is now OFF: turn it on again in the panel.",
        "rules": "Saved approval rules (delete them in the panel):", "no_rules": "No saved approval rules.",
        "classes": {"money": "spending money", "delete": "deleting files", "message": "sending a message",
                    "secrets": "passwords or keys", "untrusted": "after web/file content"},
    },
    "tr": {
        "help": "Bana yazman yeterli: sorular, işler, hatırlatmalar.\n\n"
                "/dur  her şeyi anında durdur\n"
                "/kurallar  kayıtlı onay kuralları\n"
                "/reset  bu sohbeti unut\n"
                "/skills  neler yapabilirim\n"
                "/help  bu mesaj",
        "approval": "🔐 Onay gerekiyor", "from": "isteyen", "once": "✅ Bir kez izin ver",
        "rule": "📌 İzin ver + hatırla", "deny": "❌ Reddet", "always": "⚠️ Her zaman sorulur: {classes}",
        "after": "⚠️ Güvenilmeyen içerik okunduktan sonra geldi: {sources}",
        "approved": "✅ İzin verildi", "approved_rule": "✅ İzin verildi + kural kaydedildi", "denied": "❌ Reddedildi",
        "stale": "Bu istek artık beklemiyor.", "ended": "⌛ Sona erdi",
        "stopped": "🛑 Her şey durduruldu: {jobs} bekleyen iş iptal, {approvals} onay reddedildi, "
                   "{processes} işlem sonlandırıldı. Bilgisayar kullanımı KAPALI: panelden yeniden açabilirsin.",
        "rules": "Kayıtlı onay kuralları (panelden silebilirsin):", "no_rules": "Kayıtlı onay kuralı yok.",
        "classes": {"money": "para harcama", "delete": "dosya silme", "message": "mesaj gönderme",
                    "secrets": "şifre/anahtar", "untrusted": "web/dosya içeriğinden sonra"},
    },
}
HELP = TEXT["en"]["help"]


def split_message(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    """Split long answers at line breaks so each part fits in one Telegram message."""
    parts, current = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:                     # a single huge line
            parts.append(current + line[:limit - len(current)])
            line, current = line[limit - len(current):], ""
        if len(current) + len(line) > limit:
            parts.append(current)
            current = ""
        current += line
    if current.strip():
        parts.append(current)
    return [p.rstrip() for p in parts] or [""]


def footer(answer) -> str:
    """The lines under an answer: tools used and the brain that wrote it."""
    lines = []
    if answer.tools:
        lines.append("🔧 " + ", ".join(dict.fromkeys(answer.tools)))
    if answer.brain:
        lines.append(f"🧠 {answer.brain}" + (f" (↪ {', '.join(answer.skipped)})" if answer.skipped else ""))
    return ("\n\n" + "\n".join(lines)) if lines else ""


class TelegramBot:
    def __init__(self, token: str, owner_chat_id: int, agent, registry, conversations, http=requests,
                 jobs=None, approvals=None, on_stop=None, language=None):
        self.token, self.owner = token, int(owner_chat_id)
        self.agent, self.registry, self.conversations, self.http = agent, registry, conversations, http
        self.jobs = jobs            # a JobQueue: answers are worked out there, so polling never waits
        self.approvals = approvals  # the ApprovalEngine: buttons answer its requests
        self.on_stop = on_stop      # called by /dur with "telegram"; returns a summary
        self.language = language or (lambda: "en")
        self._refused: set[int] = set()
        self._approval_messages: dict[str, int] = {}

    def t(self, key: str):
        texts = TEXT.get(self.language(), TEXT["en"])
        return texts.get(key, TEXT["en"][key])

    def call(self, method: str, http_timeout: float = 30, **params) -> dict:
        response = self.http.post(API.format(token=self.token, method=method), json=params,
                                  timeout=http_timeout)
        return response.json()

    def send(self, chat_id, text: str) -> None:
        for part in split_message(text):
            self.call("sendMessage", chat_id=chat_id, text=part)

    def _keep_typing(self, chat_id, done: threading.Event) -> None:
        """Telegram's "typing..." lasts 5 s; repeat it while a slow local model thinks."""
        while not done.is_set():
            try:
                self.call("sendChatAction", http_timeout=10, chat_id=chat_id, action="typing")
            except requests.RequestException:
                pass
            done.wait(4)

    def handle(self, message: dict) -> None:
        chat_id = message.get("chat", {}).get("id")
        text = (message.get("text") or message.get("caption") or "").strip()
        if chat_id is None:
            return
        if chat_id != self.owner:
            if chat_id not in self._refused:          # answer strangers once, then ignore
                self.send(chat_id, "This is a private agent.")
                self._refused.add(chat_id)
            return
        if not text:
            self.send(chat_id, "I can only read text messages for now.")
            return

        command = text.split()[0].lower().split("@")[0]
        if command in ("/dur", "/stop"):             # handled here at once, never queued behind a job
            summary = self.on_stop("telegram") if self.on_stop else {}
            self.send(chat_id, self.stopped_text(summary))
        elif command in ("/start", "/help"):
            self.send(chat_id, self.t("help"))
        elif command == "/reset":
            self.conversations.reset(chat_id)
            self.send(chat_id, "Conversation cleared.")
        elif command == "/skills":
            self.send(chat_id, "\n".join(f"• {t.name}: {t.description}" for t in self.registry.tools.values()))
        elif command in ("/rules", "/kurallar"):
            self.send(chat_id, self.rules_text())
        elif self.jobs:
            self.jobs.submit(f"telegram: {text[:40]}", lambda: self.answer(chat_id, text), source="telegram")
        else:
            self.answer(chat_id, text)

    def answer(self, chat_id, text: str) -> None:
        done = threading.Event()
        threading.Thread(target=self._keep_typing, args=(chat_id, done), daemon=True).start()
        try:
            answer = self.agent.run(chat_id, text, source="telegram")
            reply = answer.text + footer(answer)
        except Exception as error:   # brain offline, bad key, ...
            reply = f"⚠️ I could not reach my brain: {type(error).__name__}: {error}"
        finally:
            done.set()
        self.send(chat_id, reply)

    # ---------- stop, rules, approvals ----------
    def stopped_text(self, summary: dict) -> str:
        return self.t("stopped").format(jobs=summary.get("jobs", 0), approvals=summary.get("approvals", 0),
                                        processes=summary.get("processes", 0))

    def rules_text(self) -> str:
        rules = self.approvals.rules.all() if self.approvals else []
        if not rules:
            return self.t("no_rules")
        lines = [f"#{r['id']} {r['kind']}: " + ", ".join(f"{k}={v}" for k, v in r["scope"].items()) for r in rules]
        return self.t("rules") + "\n" + "\n".join(lines)

    def ask_approval(self, pending) -> None:
        """Send an approval request to the owner, with buttons."""
        names = self.t("classes")
        lines = [f"{self.t('approval')} ({self.t('from')}: {pending.source or '?'})", pending.action.summary]
        lines += [f"{key}: {value}" for key, value in pending.action.params.items()]
        always = [names.get(c, c) for c in pending.classes if c != "untrusted"]
        if always:
            lines.append(self.t("always").format(classes=", ".join(always)))
        if pending.tainted:
            lines.append(self.t("after").format(sources=", ".join(pending.tainted)))
        first_row = [{"text": self.t("once"), "callback_data": f"ap:{pending.id}:once"}]
        if pending.can_remember:
            first_row.append({"text": self.t("rule"), "callback_data": f"ap:{pending.id}:rule"})
        keyboard = [first_row, [{"text": self.t("deny"), "callback_data": f"ap:{pending.id}:deny"}]]
        reply = self.call("sendMessage", chat_id=self.owner, text="\n".join(lines)[:MESSAGE_LIMIT],
                          reply_markup={"inline_keyboard": keyboard})
        message_id = (reply.get("result") or {}).get("message_id")
        if message_id:
            self._approval_messages[pending.id] = message_id

    def approval_resolved(self, pending) -> None:
        """Replace the buttons with the outcome, whoever answered (Telegram, the panel or stop)."""
        message_id = self._approval_messages.pop(pending.id, None)
        if not message_id:
            return
        outcome = (self.t("approved_rule") if pending.approved and pending.remember and pending.can_remember
                   else self.t("approved") if pending.approved else self.t("denied") if pending.by else self.t("ended"))
        try:
            self.call("editMessageReplyMarkup", chat_id=self.owner, message_id=message_id,
                      reply_markup={"inline_keyboard": [[{"text": outcome, "callback_data": "ap:done"}]]})
        except requests.RequestException:
            pass

    def handle_callback(self, callback: dict) -> None:
        if callback.get("from", {}).get("id") != self.owner:       # only the owner's buttons count
            return
        parts = (callback.get("data") or "").split(":")
        text = self.t("stale")
        if len(parts) == 3 and parts[0] == "ap" and self.approvals:
            _, pending_id, choice = parts
            if self.approvals.answer(pending_id, choice in ("once", "rule"), choice == "rule", by="telegram"):
                text = {"once": self.t("approved"), "rule": self.t("approved_rule")}.get(choice, self.t("denied"))
        self.call("answerCallbackQuery", callback_query_id=callback.get("id"), text=text)

    def poll_once(self, offset: int | None) -> int | None:
        # timeout=25: Telegram holds the request open until a message arrives (long polling)
        data = self.call("getUpdates", http_timeout=40, offset=offset, timeout=25)
        for update in data.get("result", []):
            offset = update["update_id"] + 1
            if "message" in update:
                self.handle(update["message"])
            elif "callback_query" in update:
                self.handle_callback(update["callback_query"])
        return offset

    def run_forever(self, stop: threading.Event | None = None) -> None:
        offset = None
        while not (stop and stop.is_set()):
            try:
                offset = self.poll_once(offset)
            except requests.RequestException as error:
                print(f"[telegram] network problem, retrying in 5 s: {error}")
                time.sleep(5)
