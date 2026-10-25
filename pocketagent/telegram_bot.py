"""Talk to the agent from Telegram (phone, tablet or desktop).

Security: only the owner's chat (captured during setup) can use the agent.
Everyone else gets one polite refusal and is ignored; their buttons and commands do nothing.
Uses long polling, so it works on a home computer without a public server.

/dur (or /stop) stops everything at once. Approval requests arrive as messages with buttons.
"""

import html
import io
import re
import threading
import time

import requests

from pocketagent.media import VOICE_NOTES, MediaError, media_kind, speakable, to_voice_note

FILE_API = "https://api.telegram.org/file/bot{token}/{path}"
MAX_DOWNLOAD = 20_000_000      # Telegram lets bots download files up to 20 MB

API = "https://api.telegram.org/bot{token}/{method}"
MESSAGE_LIMIT = 4000   # Telegram allows 4096 characters per message

TEXT = {
    "en": {
        "help": "Just write to me: questions, tasks, reminders.\n\n"
                "/dur or /stop  stop everything at once\n"
                "/rules  saved approval rules\n"
                "/tasks  scheduled tasks\n"
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
        "tasks": "Scheduled tasks (cancel one by asking me, or in the panel):", "no_tasks": "No scheduled tasks.",
        "classes": {"money": "spending money", "delete": "deleting files", "message": "sending a message",
                    "secrets": "passwords or keys", "untrusted": "after web/file content"},
    },
    "tr": {
        "help": "Bana yazman yeterli: sorular, işler, hatırlatmalar.\n\n"
                "/dur  her şeyi anında durdur\n"
                "/kurallar  kayıtlı onay kuralları\n"
                "/gorevler  zamanlanmış görevler\n"
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
        "tasks": "Zamanlanmış görevler (iptal için bana söyle ya da panelden sil):", "no_tasks": "Zamanlanmış görev yok.",
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


_CODE_BLOCK = re.compile(r"```[\w+#.-]*\n?(.*?)```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_ITALIC = re.compile(r"(?<![*\w])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![*\w])")
_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*$", re.MULTILINE)
_BULLET = re.compile(r"^(\s*)[-*]\s+", re.MULTILINE)
_RULE = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$", re.MULTILINE)
_SEPARATOR = re.compile(r":?-{2,}:?")


def _table(lines: list[str]) -> str:
    """A Markdown table as aligned plain-text columns (Telegram has no tables)."""
    rows = []
    for line in lines:
        cells = [re.sub(r"\*\*|`", "", c).strip() for c in line.strip().strip("|").split("|")]
        if all(_SEPARATOR.fullmatch(c) for c in cells if c):     # the |---|---| line
            continue
        rows.append(cells)
    if not rows:
        return ""
    widths = [max(len(r[i]) if i < len(r) else 0 for r in rows) for i in range(max(map(len, rows)))]
    return "\n".join("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(r)).rstrip() for r in rows)


def to_html(text: str) -> str:
    """Model answers are Markdown; Telegram shows a small HTML subset. Everything else is escaped."""
    kept = []           # code blocks and tables stay out of the inline rules

    def keep(fragment: str) -> str:
        kept.append(fragment)
        return f"\x00{len(kept) - 1}\x00"

    text = _CODE_BLOCK.sub(lambda m: keep("<pre>" + html.escape(m.group(1).rstrip("\n"), quote=False) + "</pre>"), text)
    lines, table = [], []
    for line in text.split("\n") + [""]:
        if line.strip().startswith("|") and line.strip().endswith("|") and len(line.strip()) > 1:
            table.append(line)
            continue
        if table:
            lines.append(keep("<pre>" + html.escape(_table(table), quote=False) + "</pre>"))
            table = []
        lines.append(line)
    text = html.escape("\n".join(lines[:-1]), quote=False)
    text = _INLINE_CODE.sub(lambda m: keep(f"<code>{m.group(1)}</code>"), text)
    text = _LINK.sub(lambda m: f'<a href="{m.group(2).replace(chr(34), "%22")}">{m.group(1)}</a>', text)
    text = _HEADING.sub(r"<b>\1</b>", text)
    text = _RULE.sub("──────────", text)
    text = _BULLET.sub(r"\1• ", text)
    text = _BOLD.sub(r"<b>\1</b>", text)
    text = _STRIKE.sub(r"<s>\1</s>", text)
    text = _ITALIC.sub(r"<i>\1</i>", text)
    return re.sub("\x00(\\d+)\x00", lambda m: kept[int(m.group(1))], text)


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
                 jobs=None, approvals=None, on_stop=None, language=None, tasks=None, studio=None,
                 voice_reply=None):
        self.token, self.owner = token, int(owner_chat_id)
        self.agent, self.registry, self.conversations, self.http = agent, registry, conversations, http
        self.jobs = jobs            # a JobQueue: answers are worked out there, so polling never waits
        self.approvals = approvals  # the ApprovalEngine: buttons answer its requests
        self.on_stop = on_stop      # called by /dur with "telegram"; returns a summary
        self.tasks = tasks          # the TaskStore, for /tasks
        self.studio = studio        # media.Studio: hears voice messages, speaks answers
        self.voice_reply = voice_reply or (lambda: "off")   # "off", "spoken" or "always"
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
        for part in split_message(text, MESSAGE_LIMIT - 500):     # room for the HTML tags
            reply = self.call("sendMessage", chat_id=chat_id, text=to_html(part), parse_mode="HTML")
            if reply.get("ok") is False:          # Telegram could not read the markup: send it as it is
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
        has_media = any(kind in message for kind in ("voice", "audio", "video_note", "photo", "document"))
        if not text and not has_media:
            self.send(chat_id, "I can read text, voice messages, photos and files.")
            return

        command = text.split()[0].lower().split("@")[0] if text.startswith("/") and not has_media else ""
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
        elif command in ("/tasks", "/gorevler", "/görevler"):
            tasks = self.tasks.all() if self.tasks else []
            self.send(chat_id, self.t("tasks") + "\n" + "\n".join(
                f"#{t['id']} {t['next'].replace('T', ' ')[:16]} ({t['repeat'] or 'once'}): {t['task']}" for t in tasks)
                if tasks else self.t("no_tasks"))
        elif command in ("/rules", "/kurallar"):
            self.send(chat_id, self.rules_text())
        elif self.jobs:
            self.jobs.submit(f"telegram: {text[:40] or 'media'}", lambda: self.process(chat_id, message),
                             source="telegram")
        else:
            self.process(chat_id, message)

    # ---------- voice messages, photos, files ----------
    def download(self, file_id: str) -> bytes:
        info = self.call("getFile", file_id=file_id).get("result") or {}
        if not info.get("file_path"):
            raise MediaError("Telegram did not give the file")
        if (info.get("file_size") or 0) > MAX_DOWNLOAD:
            raise MediaError("the file is larger than 20 MB, the most Telegram lets a bot download")
        reply = self.http.get(FILE_API.format(token=self.token, path=info["file_path"]), timeout=120)
        if reply.status_code >= 400:
            raise MediaError(f"Telegram answered HTTP {reply.status_code} for the file")
        return reply.content

    def save_upload(self, file_id: str, filename: str) -> str:
        """Save a file sent on Telegram in workspace/inbox under a safe name; returns its workspace path."""
        safe = re.sub(r"[^\w.-]+", "_", filename.replace("\\", "/").rsplit("/", 1)[-1]).strip("._") or "file"
        folder = self.agent.workspace / "inbox"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / safe
        path.write_bytes(self.download(file_id))
        return f"inbox/{path.name}"

    def process(self, chat_id, message: dict) -> None:
        """Turn a message (text, voice, photo or file) into words for the agent, then answer."""
        text = (message.get("text") or message.get("caption") or "").strip()
        spoken = False
        try:
            sound = message.get("voice") or message.get("audio") or message.get("video_note")
            if sound:
                if not self.studio or not self.studio.ready("hearing"):
                    self.send(chat_id, "To understand voice messages, choose a hearing specialist in the panel "
                                       "(Specialists; Groq's free key works).")
                    return
                transcript = self.studio.transcribe(self.download(sound["file_id"]), "voice.ogg")
                if not transcript:
                    self.send(chat_id, "I could not make out any words in that voice message.")
                    return
                self.send(chat_id, f"🎤 *{transcript}*")
                text, spoken = (transcript + ("\n" + text if text else "")), True
            elif message.get("photo"):
                biggest = max(message["photo"], key=lambda p: p.get("width", 0) * p.get("height", 1))
                path = self.save_upload(biggest["file_id"], f"photo-{time.strftime('%Y%m%d-%H%M%S')}.jpg")
                text = f"[The user sent a photo, saved as {path}. Look at it with look_at_image.]\n{text}".strip()
            elif message.get("document"):
                document = message["document"]
                path = self.save_upload(document["file_id"], f"{time.strftime('%Y%m%d-%H%M%S')}-"
                                                             f"{document.get('file_name') or 'file'}")
                hint = ("look_at_image" if (document.get("mime_type") or "").startswith("image/") else "read_document")
                text = f"[The user sent a file, saved as {path}. Read it with {hint}.]\n{text}".strip()
        except (MediaError, requests.RequestException, OSError) as error:
            self.send(chat_id, f"⚠️ {error}")
            return
        self.answer(chat_id, text, spoken=spoken)

    def speak(self, chat_id, text: str) -> None:
        """Send the answer as a voice message too (a voice bubble for MP3/OGG, an audio player for WAV)."""
        try:
            data, extension = to_voice_note(*self.studio.speech(speakable(text)))
        except MediaError as error:
            self.send(chat_id, f"(No voice reply: {error})")
            return
        method, field = ("sendVoice", "voice") if extension in VOICE_NOTES else ("sendAudio", "audio")
        try:
            self.http.post(API.format(token=self.token, method=method), data={"chat_id": chat_id},
                           files={field: (f"answer{extension}", io.BytesIO(data))}, timeout=120)
        except requests.RequestException:
            pass

    def answer(self, chat_id, text: str, spoken: bool = False) -> None:
        done = threading.Event()
        threading.Thread(target=self._keep_typing, args=(chat_id, done), daemon=True).start()
        files, said = [], ""
        try:
            answer = self.agent.run(chat_id, text, source="telegram")
            reply, files, said = answer.text + footer(answer), answer.files, answer.text
        except Exception as error:   # brain offline, bad key, ...
            reply = f"⚠️ I could not reach my brain: {type(error).__name__}: {error}"
        finally:
            done.set()
        self.send(chat_id, reply)
        for relative in files:
            self.send_file(chat_id, relative)
        mode = self.voice_reply()
        if said and self.studio and (mode == "always" or (mode == "spoken" and spoken)) and self.studio.ready("speech"):
            self.speak(chat_id, said)

    def send_file(self, chat_id, relative: str) -> None:
        """Send a workspace file: images as photos, audio as audio, anything else as a document."""
        path = (self.agent.workspace / relative).resolve()
        if not path.is_file() or self.agent.workspace.resolve() not in path.parents:
            return
        method, field = {"image": ("sendPhoto", "photo"), "audio": ("sendAudio", "audio")}.get(
            media_kind(path), ("sendDocument", "document"))
        if method == "sendPhoto" and path.stat().st_size > 10_000_000:     # Telegram's photo limit
            method, field = "sendDocument", "document"
        try:
            with open(path, "rb") as f:
                self.http.post(API.format(token=self.token, method=method), data={"chat_id": chat_id},
                               files={field: (path.name, f)}, timeout=120)
        except requests.RequestException as error:
            self.send(chat_id, f"⚠️ Could not send {relative}: {error}")

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
