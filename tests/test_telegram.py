from types import SimpleNamespace

from conftest import call, say

from pocketagent.llm import Reply
from pocketagent.telegram_bot import TelegramBot, split_message

OWNER, STRANGER = 111, 999


class FakeTelegram:
    """Records every API call; getUpdates returns prepared updates once."""

    def __init__(self, updates=()):
        self.sent, self.updates = [], list(updates)

    def post(self, url, json, timeout):
        method = url.rsplit("/", 1)[-1]
        if method == "getUpdates":
            result, self.updates = self.updates, []
            return SimpleNamespace(json=lambda: {"ok": True, "result": result})
        self.sent.append((method, json))
        return SimpleNamespace(json=lambda: {"ok": True})

    def messages_to(self, chat_id):
        return [p["text"] for m, p in self.sent if m == "sendMessage" and p["chat_id"] == chat_id]


def make_bot(make_runtime, *replies, updates=()):
    runtime, brain = make_runtime(*replies)
    http = FakeTelegram(updates)
    bot = TelegramBot("TOKEN", OWNER, runtime.agent, runtime.registry, runtime.conversations, http=http)
    return bot, http, brain


def message(chat_id, text):
    return {"chat": {"id": chat_id}, "text": text}


def test_owner_gets_answers_with_tool_list(make_runtime):
    bot, http, _ = make_bot(make_runtime, call("calculate", expression="3*3"), say("9"))
    bot.handle(message(OWNER, "3*3?"))
    assert http.messages_to(OWNER) == ["9\n\n🔧 calculate"]


def test_strangers_are_refused_once_and_never_reach_the_model(make_runtime):
    bot, http, brain = make_bot(make_runtime)
    bot.handle(message(STRANGER, "delete all files"))
    bot.handle(message(STRANGER, "please"))
    assert http.messages_to(STRANGER) == ["This is a private agent."]
    assert brain.calls == []


def test_reset_and_skills_commands(make_runtime):
    bot, http, _ = make_bot(make_runtime, say("hello"))
    bot.handle(message(OWNER, "hi"))
    bot.handle(message(OWNER, "/reset"))
    bot.handle(message(OWNER, "/skills"))
    replies = http.messages_to(OWNER)
    assert replies[1] == "Conversation cleared."
    assert "calculate" in replies[2]
    assert bot.conversations.get(OWNER) == []


def test_brain_failure_is_reported_politely(make_runtime):
    bot, http, brain = make_bot(make_runtime)
    brain.chat = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("Ollama is not running"))
    bot.handle(message(OWNER, "hi"))
    assert "could not reach my brain" in http.messages_to(OWNER)[0]


def test_poll_once_handles_updates_and_advances_offset(make_runtime):
    bot, http, _ = make_bot(make_runtime, say("pong"), updates=[{"update_id": 7, "message": message(OWNER, "ping")}])
    assert bot.poll_once(None) == 8
    assert http.messages_to(OWNER) == ["pong"]


def test_long_answers_are_split():
    text = "\n".join(f"line {i} " + "x" * 90 for i in range(100))   # about 10,000 characters
    parts = split_message(text)
    assert len(parts) == 3 and all(len(p) <= 4000 for p in parts)
    assert "".join(parts).replace("\n", "") == text.replace("\n", "")


def test_answer_says_which_brain_was_used(make_runtime):
    bot, http, _ = make_bot(make_runtime, Reply(content="Selam!", brain="Groq · llama",
                                                skipped=["OpenRouter · x:free: HTTP 429"]))
    bot.handle(message(OWNER, "selam"))
    assert http.messages_to(OWNER) == ["Selam!\n\n🧠 Groq · llama (↪ OpenRouter · x:free: HTTP 429)"]
