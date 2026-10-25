"""Switching between brains: the agent can change brains, and every answer can be retried with another one."""

import threading
from dataclasses import replace
from types import SimpleNamespace

from conftest import FakeWeb, response, say

from pocketagent import config as cfg
from pocketagent.app import App
from pocketagent.approvals import ApprovalEngine, AuditLog, RuleStore
from pocketagent.brains import BrainChoice
from pocketagent.config import BrainConfig, Config
from pocketagent.llm import PROVIDERS, Router
from pocketagent.memory import ConversationStore
from pocketagent.telegram_bot import TelegramBot
from pocketagent.tools import ToolContext, ToolRegistry

NVIDIA = BrainConfig("nvidia", PROVIDERS["nvidia"].base_url, "nvidia/nemotron-3-ultra-550b-a55b")
GROQ = BrainConfig("groq", PROVIDERS["groq"].base_url, "openai/gpt-oss-120b")
GEMINI = BrainConfig("gemini", PROVIDERS["gemini"].base_url, "gemini-3.5-flash", enabled=False)


def three_brains():
    config = Config()
    config.set_brains([replace(b) for b in (NVIDIA, GROQ, GEMINI)])     # copies: tests change them
    config.keys = {"nvidia": "n", "groq": "g", "gemini": "m"}
    return config


# ---------- choosing a brain ----------
def test_a_brain_is_put_first_by_part_of_its_name(home):
    config = three_brains()
    choice = BrainChoice(config, lambda: cfg.save(config))
    assert choice.prefer("GEMINI") == "Gemini · gemini-3.5-flash"
    assert [b.provider for b in config.brains()] == ["gemini", "nvidia", "groq"]
    assert config.brain.enabled                                       # switched on again
    assert cfg.load().brain.provider == "gemini"
    assert choice.prefer("claude") is None
    lines = choice.describe()
    assert lines[0].startswith("1. Gemini · gemini-3.5-flash") and "sees pictures" in lines[0]


def tools():
    registry = ToolRegistry()
    registry.load_builtin()
    return registry


def test_the_agent_can_switch_brains_when_asked(home):
    config = three_brains()
    ctx = ToolContext(workspace=home / "ws", brains=BrainChoice(config, lambda: None))
    listing = tools().call("switch_brain", {}, ctx)
    assert "1. NVIDIA" in listing and "2. Groq" in listing
    assert "Groq · openai/gpt-oss-120b" in tools().call("switch_brain", {"name": "gpt-oss"}, ctx)
    assert config.brain.provider == "groq"
    assert "no brain" in tools().call("switch_brain", {"name": "claude"}, ctx)


def test_after_reading_outside_content_switching_needs_approval(home):
    engine = ApprovalEngine(RuleStore(home), AuditLog(home), lambda: False, timeout=5)
    asked = []
    engine.notifiers.append(lambda p: asked.append(p) or engine.answer(p.id, False))
    config = three_brains()
    ctx = ToolContext(workspace=home / "ws", brains=BrainChoice(config, lambda: None), approvals=engine,
                      tainted_by=["fetch_webpage(https://evil.example)"])
    assert tools().call("switch_brain", {"name": "groq"}, ctx).startswith("Not done")
    assert config.brain.provider == "nvidia" and asked


# ---------- retrying with another brain ----------
class Server:
    def __init__(self):
        self.asked = []

    def post(self, url, json, headers, timeout):
        self.asked.append(json["model"])
        return SimpleNamespace(status_code=200, headers={}, text="",
                               json=lambda: {"choices": [{"message": {"content": f"answer from {json['model']}"}}]})


def test_the_router_can_leave_out_the_brain_that_just_answered():
    router = Router(three_brains(), http=Server(), retry_delay=0)
    router.avoid = {"NVIDIA · nvidia/nemotron-3-ultra-550b-a55b"}
    assert router.chat([]).brain == "Groq · openai/gpt-oss-120b"
    router.avoid = {"NVIDIA · nvidia/nemotron-3-ultra-550b-a55b", "Groq · openai/gpt-oss-120b"}
    assert router.chat([]).brain == "NVIDIA · nvidia/nemotron-3-ultra-550b-a55b"     # nobody else: no change


def test_retrying_replaces_the_last_answer_in_the_conversation(home):
    store = ConversationStore(home)
    for role, text in (("user", "Q1"), ("assistant", "A1"), ("user", "Q2"), ("assistant", "A2")):
        store.add("7", role, text)
    assert store.drop_last_exchange("7") == "Q2"
    assert store.get("7") == [{"role": "user", "content": "Q1"}, {"role": "assistant", "content": "A1"}]


def test_panel_retry_asks_another_brain(home):
    config = three_brains()
    server = Server()
    app = App(config, http=server)
    app.runtime.agent.brain.http = server
    first = app.chat("Uçak fiyatı?")
    app.jobs.get(first["id"]).done.wait(5)
    again = app.retry_chat()
    app.jobs.get(again["id"]).done.wait(5)
    assert app.job(again["id"])["result"]["brain"] == "Groq · openai/gpt-oss-120b"
    assert server.asked == ["nvidia/nemotron-3-ultra-550b-a55b", "openai/gpt-oss-120b"]
    assert [m["content"] for m in app.history()] == ["Uçak fiyatı?", "answer from openai/gpt-oss-120b"]


# ---------- Telegram ----------
OWNER = 111


class Telegram:
    def __init__(self):
        self.sent = []

    def post(self, url, json=None, timeout=None, data=None, files=None):
        self.sent.append((url.rsplit("/", 1)[-1], json))
        return SimpleNamespace(json=lambda: {"ok": True, "result": {"message_id": len(self.sent)}})

    def last(self, method="sendMessage"):
        return [p for m, p in self.sent if m == method][-1]


def telegram_bot(make_runtime, *replies, jobs=None):
    runtime, brain = make_runtime(*replies)
    runtime.config.set_brains([replace(NVIDIA), replace(GROQ)])
    runtime.config.keys = {"nvidia": "n", "groq": "g"}
    http = Telegram()
    bot = TelegramBot("TOKEN", OWNER, runtime.agent, runtime.registry, runtime.conversations, http=http,
                      brains=BrainChoice(runtime.config, lambda: None), jobs=jobs)
    return bot, http, brain, runtime


def press(bot, data):
    bot.handle_callback({"id": "cb", "from": {"id": OWNER}, "data": data, "message": {"chat": {"id": OWNER}}})


def test_every_answer_has_a_try_another_brain_button(make_runtime):
    from pocketagent.llm import Reply
    bot, http, brain, runtime = telegram_bot(make_runtime, Reply("I cannot read it.", brain="NVIDIA · x"),
                                             Reply("14.900 TL", brain="Groq · y"))
    bot.handle({"chat": {"id": OWNER}, "text": "Uçak fiyatı?"})
    buttons = http.last()["reply_markup"]["inline_keyboard"][0]
    assert buttons[0]["callback_data"] == "retry"
    seen = {}
    original = bot.agent.run
    bot.agent.run = lambda chat_id, text, source="", avoid=(): seen.update(text=text, avoid=set(avoid)) or \
        original(chat_id, text, source=source, avoid=avoid)
    press(bot, "retry")
    assert seen == {"text": "Uçak fiyatı?", "avoid": {"NVIDIA · x"}}
    assert http.last()["text"].startswith("14.900 TL")
    assert [m["content"] for m in runtime.conversations.get(OWNER)] == ["Uçak fiyatı?", "14.900 TL"]


def test_the_brain_command_lists_brains_and_a_button_puts_one_first(make_runtime):
    bot, http, _, runtime = telegram_bot(make_runtime)
    bot.handle({"chat": {"id": OWNER}, "text": "/beyin"})
    labels = [b[0]["text"] for b in http.last()["reply_markup"]["inline_keyboard"]]
    assert labels[0].startswith("1. NVIDIA") and labels[1].startswith("2. Groq")
    press(bot, "brain:1")
    assert runtime.config.brain.provider == "groq"
    assert "Groq" in [p for m, p in http.sent if m == "answerCallbackQuery"][-1]["text"]


def test_a_message_that_has_to_wait_says_so(make_runtime):
    from pocketagent.jobs import JobQueue
    jobs, release = JobQueue(), threading.Event()
    jobs.submit("busy", release.wait)
    while jobs.current is None:
        pass
    bot, http, _, _ = telegram_bot(make_runtime, say("ok"), jobs=jobs)
    bot.handle({"chat": {"id": OWNER}, "text": "selam"})
    assert http.last()["text"].startswith("⏳")
    release.set()


def test_the_bot_shows_its_commands_in_telegrams_menu(make_runtime):
    bot, http, _, _ = telegram_bot(make_runtime)
    bot.announce_commands()
    menus = {(p or {}).get("language_code", ""): [c["command"] for c in p["commands"]]
             for m, p in http.sent if m == "setMyCommands"}
    assert "brain" in menus[""] and "beyin" in menus["tr"] and "dur" in menus["tr"]
