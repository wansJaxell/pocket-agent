"""Talk to the agent from Telegram (phone, tablet or desktop).

Security: only the owner's chat (captured during setup) can use the agent.
Everyone else gets one polite refusal and is ignored.
Uses long polling, so it works on a home computer without a public server.
"""

import threading
import time

import requests

API = "https://api.telegram.org/bot{token}/{method}"
MESSAGE_LIMIT = 4000   # Telegram allows 4096 characters per message

HELP = ("Just write to me: questions, tasks, reminders.\n\n"
        "/reset  forget this conversation\n"
        "/skills  what I can do\n"
        "/help  this message")


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
                 jobs=None):
        self.token, self.owner = token, int(owner_chat_id)
        self.agent, self.registry, self.conversations, self.http = agent, registry, conversations, http
        self.jobs = jobs            # a JobQueue: answers are worked out there, so polling never waits
        self._refused: set[int] = set()

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

        command = text.split()[0].lower()
        if command in ("/start", "/help"):
            self.send(chat_id, HELP)
        elif command == "/reset":
            self.conversations.reset(chat_id)
            self.send(chat_id, "Conversation cleared.")
        elif command == "/skills":
            self.send(chat_id, "\n".join(f"• {t.name}: {t.description}" for t in self.registry.tools.values()))
        elif self.jobs:
            self.jobs.submit(f"telegram: {text[:40]}", lambda: self.answer(chat_id, text), source="telegram")
        else:
            self.answer(chat_id, text)

    def answer(self, chat_id, text: str) -> None:
        done = threading.Event()
        threading.Thread(target=self._keep_typing, args=(chat_id, done), daemon=True).start()
        try:
            answer = self.agent.run(chat_id, text)
            reply = answer.text + footer(answer)
        except Exception as error:   # brain offline, bad key, ...
            reply = f"⚠️ I could not reach my brain: {type(error).__name__}: {error}"
        finally:
            done.set()
        self.send(chat_id, reply)

    def poll_once(self, offset: int | None) -> int | None:
        # timeout=25: Telegram holds the request open until a message arrives (long polling)
        data = self.call("getUpdates", http_timeout=40, offset=offset, timeout=25)
        for update in data.get("result", []):
            offset = update["update_id"] + 1
            if "message" in update:
                self.handle(update["message"])
        return offset

    def run_forever(self, stop: threading.Event | None = None) -> None:
        offset = None
        while not (stop and stop.is_set()):
            try:
                offset = self.poll_once(offset)
            except requests.RequestException as error:
                print(f"[telegram] network problem, retrying in 5 s: {error}")
                time.sleep(5)
