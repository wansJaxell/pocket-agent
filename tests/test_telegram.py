from types import SimpleNamespace

from conftest import call, say

from pocketagent.agent import Answer
from pocketagent.llm import Reply
from pocketagent.telegram_bot import TelegramBot, split_message

OWNER, STRANGER = 111, 999


class FakeTelegram:
    """Records every API call; getUpdates returns prepared updates once."""

    def __init__(self, updates=()):
        self.sent, self.updates = [], list(updates)

    def post(self, url, json=None, timeout=None, data=None, files=None):
        method = url.rsplit("/", 1)[-1]
        if method == "getUpdates":
            result, self.updates = self.updates, []
            return SimpleNamespace(json=lambda: {"ok": True, "result": result})
        if json and json.get("parse_mode") and getattr(self, "refuse_html", False):
            self.sent.append((method, json))
            return SimpleNamespace(json=lambda: {"ok": False, "description": "Bad Request: can't parse entities"})
        if files:                                     # an upload: keep the field name and the bytes
            self.sent.append((method, {**data, "files": {k: (v[0], v[1].read()) for k, v in files.items()}}))
        else:
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


# ---------- approvals and the stop command ----------
def safety_bot(make_runtime, stopped):
    runtime, _ = make_runtime()
    runtime.config.computer_use = True
    http = FakeTelegram()
    bot = TelegramBot("TOKEN", OWNER, runtime.agent, runtime.registry, runtime.conversations, http=http,
                      approvals=runtime.approvals, on_stop=lambda by: stopped.append(by) or
                      {"jobs": 1, "approvals": 0, "processes": 2})
    runtime.approvals.notifiers.append(bot.ask_approval)
    return runtime, bot, http


def press(bot, http, button_text, chat_id=OWNER):
    method, sent = [(m, p) for m, p in http.sent if m == "sendMessage" and "reply_markup" in p][-1]
    buttons = [b for row in sent["reply_markup"]["inline_keyboard"] for b in row]
    data = next(b["callback_data"] for b in buttons if b["text"] == button_text)
    bot.handle_callback({"id": "cb1", "from": {"id": chat_id}, "data": data,
                         "message": {"message_id": 5, "chat": {"id": chat_id}}})


def test_approval_buttons_in_telegram(make_runtime):
    import threading
    from pocketagent.approvals import Action
    runtime, bot, http = safety_bot(make_runtime, [])
    action = Action("shell", "Run a command", {"command": "git status", "folder": "C:/work"},
                    scope={"command": "git status", "folder": "C:/work"})
    result = []
    worker = threading.Thread(target=lambda: result.append(runtime.approvals.request(action)))
    worker.start()
    while not any("reply_markup" in p for _, p in http.sent):
        pass
    prompt = http.messages_to(OWNER)[-1]
    assert "git status" in prompt and "C:/work" in prompt
    press(bot, http, "📌 Allow + remember")
    worker.join(5)
    assert result == ["approved"] and runtime.approvals.rules.all()[0]["scope"]["command"] == "git status"
    assert ("answerCallbackQuery", {"callback_query_id": "cb1", "text": "✅ Allowed + rule saved"}) in http.sent


def test_strangers_cannot_press_approval_buttons(make_runtime):
    runtime, bot, http = safety_bot(make_runtime, [])
    bot.handle_callback({"id": "x", "from": {"id": STRANGER}, "data": "ap:1:once",
                         "message": {"message_id": 5, "chat": {"id": STRANGER}}})
    assert not any(m == "answerCallbackQuery" and "Allowed" in p.get("text", "") for m, p in http.sent)


def test_always_ask_requests_offer_no_remember_button(make_runtime):
    from pocketagent.approvals import Action
    runtime, bot, http = safety_bot(make_runtime, [])
    pending = runtime.approvals._new_pending(Action("shell", "Delete", {"command": "rm x"}, scope={}, classes={"delete"}),
                                             classes={"delete"}, tainted=["read_file(notes.txt)"], source="panel")
    bot.ask_approval(pending)
    sent = http.sent[-1][1]
    labels = [b["text"] for row in sent["reply_markup"]["inline_keyboard"] for b in row]
    assert "📌 Allow + remember" not in labels and "❌ Deny" in labels
    assert "deleting files" in sent["text"] and "read_file(notes.txt)" in sent["text"]


def test_dur_stops_everything_at_once(make_runtime):
    stopped = []
    _, bot, http = safety_bot(make_runtime, stopped)
    bot.handle(message(OWNER, "/dur"))
    assert stopped == ["telegram"]
    assert http.messages_to(OWNER)[-1].startswith("🛑")
    bot.handle(message(STRANGER, "/dur"))               # strangers cannot stop (or start) anything
    assert stopped == ["telegram"]


def test_rules_command_lists_saved_rules(make_runtime):
    from pocketagent.approvals import Action
    runtime, bot, http = safety_bot(make_runtime, [])
    runtime.approvals.rules.add(Action("shell", "x", {}, scope={"command": "git status", "folder": "C:/w"}))
    bot.handle(message(OWNER, "/kurallar"))
    assert "#1 shell" in http.messages_to(OWNER)[-1] and "git status" in http.messages_to(OWNER)[-1]


def test_images_and_audio_made_for_the_answer_are_sent_as_files(make_runtime):
    bot, http, _ = make_bot(make_runtime)
    media = bot.agent.workspace / "media"
    media.mkdir(parents=True)
    (media / "image-1.png").write_bytes(b"png-bytes")
    (media / "speech-1.mp3").write_bytes(b"mp3-bytes")
    bot.agent.run = lambda chat_id, text, source="": Answer("Here you go.", files=["media/image-1.png",
                                                                                    "media/speech-1.mp3"])
    bot.handle(message(OWNER, "draw and say it"))
    uploads = [(m, p) for m, p in http.sent if m in ("sendPhoto", "sendAudio", "sendDocument")]
    assert uploads == [("sendPhoto", {"chat_id": OWNER, "files": {"photo": ("image-1.png", b"png-bytes")}}),
                       ("sendAudio", {"chat_id": OWNER, "files": {"audio": ("speech-1.mp3", b"mp3-bytes")}})]


# ---------- formatting ----------
def test_model_markdown_becomes_telegram_formatting():
    from pocketagent.telegram_bot import to_html
    text = ("### Sonuç\n**Kalın** ve *eğik*, `fetch_webpage` ve [OpenRouter](https://openrouter.ai).\n"
            "- birinci madde\n---\n```python\nprint(\"<a> & b\")\n```")
    html = to_html(text)
    assert "<b>Sonuç</b>" in html and "<b>Kalın</b>" in html and "<i>eğik</i>" in html
    assert "<code>fetch_webpage</code>" in html and '<a href="https://openrouter.ai">OpenRouter</a>' in html
    assert "• birinci madde" in html
    assert "<pre>print(&quot;&lt;a&gt; &amp; b&quot;)</pre>" in html or "<pre>print(\"&lt;a&gt; &amp; b\")</pre>" in html
    assert "snake_case_name" in to_html("snake_case_name")          # underscores stay as they are


def test_markdown_tables_become_aligned_blocks():
    from pocketagent.telegram_bot import to_html
    html = to_html("| Yetenek | Durum |\n|---|---|\n| fetch | ✅ Var |\n| JavaScript | ❌ Yok |")
    assert html.startswith("<pre>") and "|---" not in html
    assert "Yetenek     Durum" in html and "JavaScript  ❌ Yok" in html


def test_answers_are_sent_as_html_and_plain_text_if_telegram_refuses(make_runtime):
    bot, http, _ = make_bot(make_runtime, say("**ok**"))
    bot.handle(message(OWNER, "hi"))
    method, sent = [(m, p) for m, p in http.sent if m == "sendMessage"][-1]
    assert sent["text"] == "<b>ok</b>" and sent["parse_mode"] == "HTML"
    http.refuse_html = True
    bot.send(OWNER, "**broken <b> markup**")
    assert http.sent[-1][1]["text"] == "**broken <b> markup**" and "parse_mode" not in http.sent[-1][1]
