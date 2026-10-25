"""Telegram: voice messages become commands, photos and files land in the workspace, answers can speak."""

from types import SimpleNamespace

from conftest import say

from pocketagent import media
from pocketagent.telegram_bot import TelegramBot

OWNER = 111


class TelegramWithFiles:
    """Telegram's API with files to download; records what the bot sends."""

    def __init__(self, files=None):
        self.files, self.sent = files or {}, []

    def post(self, url, json=None, timeout=None, data=None, files=None):
        method = url.rsplit("/", 1)[-1]
        if method == "getFile":
            path, content = self.files[json["file_id"]]
            return SimpleNamespace(json=lambda: {"ok": True, "result": {"file_path": path, "file_size": len(content)}})
        if files:
            self.sent.append((method, {**data, "files": {k: (v[0], v[1].read()) for k, v in files.items()}}))
        else:
            self.sent.append((method, json))
        return SimpleNamespace(json=lambda: {"ok": True})

    def get(self, url, timeout=None, **kwargs):
        for path, content in self.files.values():
            if url == f"https://api.telegram.org/file/botTOKEN/{path}":
                return SimpleNamespace(status_code=200, content=content, headers={})
        raise AssertionError(url)

    def texts(self):
        return [p["text"] for m, p in self.sent if m == "sendMessage"]

    def uploads(self):
        return [(m, p["files"]) for m, p in self.sent if "files" in p]


class FakeStudio:
    def __init__(self, transcript="Yarın hava nasıl olacak?", hearing=True, extension=".mp3"):
        self.transcript, self.hearing, self.extension = transcript, hearing, extension
        self.heard, self.spoken = [], []

    def ready(self, kind):
        return {"hearing": self.hearing, "speech": True}.get(kind, False)

    def transcribe(self, data, filename):
        self.heard.append((data, filename))
        return self.transcript

    def speech(self, text, voice=""):
        self.spoken.append(text)
        return b"voice-bytes", self.extension


def bot_with(make_runtime, *replies, files=None, studio=None, voice_reply="off"):
    runtime, brain = make_runtime(*replies)
    http = TelegramWithFiles(files)
    bot = TelegramBot("TOKEN", OWNER, runtime.agent, runtime.registry, runtime.conversations, http=http,
                      studio=studio or FakeStudio(), voice_reply=lambda: voice_reply)
    return bot, http, brain, runtime


def voice(file_id="v1"):
    return {"chat": {"id": OWNER}, "voice": {"file_id": file_id, "duration": 3, "mime_type": "audio/ogg"}}


def test_a_voice_message_becomes_a_command_and_the_answer_can_speak(make_runtime):
    studio = FakeStudio()
    bot, http, brain, _ = bot_with(make_runtime, say("Yarın **güneşli**, 18 °C."), studio=studio,
                                   files={"v1": ("voice/file_7.oga", b"OggS-bytes")}, voice_reply="spoken")
    bot.handle(voice())
    assert studio.heard == [(b"OggS-bytes", "voice.ogg")]
    assert brain.calls[0]["messages"][-1]["content"] == "Yarın hava nasıl olacak?"
    assert http.texts()[0] == "🎤 <i>Yarın hava nasıl olacak?</i>"          # what was understood
    assert studio.spoken == ["Yarın güneşli, 18 °C."]                         # read without the Markdown
    assert http.uploads() == [("sendVoice", {"voice": ("answer.mp3", b"voice-bytes")})]


def test_voice_messages_without_a_hearing_specialist_explain_the_setup(make_runtime):
    bot, http, brain, _ = bot_with(make_runtime, studio=FakeStudio(hearing=False),
                                   files={"v1": ("voice/a.oga", b"OggS")})
    bot.handle(voice())
    assert brain.calls == [] and "panel" in http.texts()[0]


def test_a_photo_is_saved_in_the_inbox_and_handed_to_the_agent(make_runtime):
    bot, http, brain, runtime = bot_with(make_runtime, say("Bu bir fatura."),
                                         files={"p2": ("photos/file_9.jpg", b"\xff\xd8big")})
    bot.handle({"chat": {"id": OWNER}, "caption": "Bu ne?",
                "photo": [{"file_id": "p1", "width": 90}, {"file_id": "p2", "width": 1280}]})
    asked = brain.calls[0]["messages"][-1]["content"]
    assert "inbox/photo-" in asked and "look_at_image" in asked and asked.endswith("Bu ne?")
    saved = list((runtime.agent.workspace / "inbox").iterdir())
    assert len(saved) == 1 and saved[0].read_bytes() == b"\xff\xd8big" and saved[0].name in asked


def test_a_file_is_saved_in_the_inbox_with_a_safe_name(make_runtime):
    bot, http, brain, runtime = bot_with(make_runtime, say("Okudum."), files={"d1": ("documents/x.pdf", b"%PDF")})
    bot.handle({"chat": {"id": OWNER}, "document": {"file_id": "d1", "file_name": "../../Rapor Ekim.pdf"}})
    asked = brain.calls[0]["messages"][-1]["content"]
    assert "read_document" in asked and "Rapor_Ekim.pdf" in asked
    saved = list((runtime.agent.workspace / "inbox").iterdir())
    assert len(saved) == 1 and saved[0].read_bytes() == b"%PDF"


def test_always_speaking_and_wav_voices_without_ffmpeg(make_runtime, monkeypatch):
    monkeypatch.setattr(media.shutil, "which", lambda name: None)
    bot, http, _, _ = bot_with(make_runtime, say("Tamam."), studio=FakeStudio(extension=".wav"), voice_reply="always")
    bot.handle({"chat": {"id": OWNER}, "text": "selam"})
    assert http.uploads() == [("sendAudio", {"audio": ("answer.wav", b"voice-bytes")})]   # a player, not a bubble


def test_no_voice_when_voice_replies_are_off(make_runtime):
    studio = FakeStudio()
    bot, http, _, _ = bot_with(make_runtime, say("Tamam."), studio=studio,
                               files={"v1": ("voice/a.oga", b"OggS")}, voice_reply="off")
    bot.handle(voice())
    assert studio.spoken == [] and http.uploads() == []
