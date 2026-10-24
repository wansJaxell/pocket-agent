"""Specialists: the agent writes the prompt, another free model makes the image, the voice or the text."""

import base64
from types import SimpleNamespace

import pytest
from conftest import FakeWeb, call, response, say

from pocketagent import media
from pocketagent.approvals import ApprovalEngine, AuditLog, RuleStore
from pocketagent.config import Config
from pocketagent.media import Studio
from pocketagent.tools import ToolContext, ToolRegistry

PNG = b"\x89PNG\r\n\x1a\nfake-image"
MP3 = b"ID3fake-voice"


def binary(data, content_type, status=200):
    return SimpleNamespace(status_code=status, content=data, headers={"Content-Type": content_type},
                           text="", json=lambda: {})


def studio_with(*routes, **media_settings):
    config = Config()
    config.media.update(media_settings)
    web = FakeWeb(*routes)
    return Studio(config, http=web), web, config


def context(tmp_path, studio, engine=None):
    return ToolContext(workspace=tmp_path / "ws", studio=studio, approvals=engine,
                       generation=engine.generation if engine else None)


def tools():
    registry = ToolRegistry()
    registry.load_builtin()
    return registry


# ---------- images ----------
def test_pollinations_makes_images_without_a_key(tmp_path):
    studio, web, _ = studio_with(("GET", "image.pollinations.ai/prompt/", binary(b"\xff\xd8jpeg", "image/jpeg")),
                                 image={"provider": "pollinations", "model": ""})
    ctx = context(tmp_path, studio)
    result = tools().call("create_image", {"prompt": "a red apple on a desk", "size": "512x768"}, ctx)
    assert "media/image-" in result and ctx.files[0].endswith(".jpg")
    assert (tmp_path / "ws" / ctx.files[0]).read_bytes() == b"\xff\xd8jpeg"
    method, url, kwargs = web.requests[0]
    assert "a%20red%20apple%20on%20a%20desk" in url
    assert kwargs["params"]["width"] == 512 and kwargs["params"]["height"] == 768
    assert "Authorization" not in kwargs["headers"]


def test_a_free_pollinations_key_uses_the_new_gateway_and_its_models(tmp_path):
    studio, web, config = studio_with(("GET", "gen.pollinations.ai/image/", binary(PNG, "image/png")),
                                      image={"provider": "pollinations", "model": "flux.1-schnell"})
    config.keys["pollinations"] = "pk_free"
    ctx = context(tmp_path, studio)
    tools().call("create_image", {"prompt": "logo"}, ctx)
    _, url, kwargs = web.requests[0]
    assert url.startswith("https://gen.pollinations.ai/image/logo")
    assert kwargs["params"]["model"] == "flux.1-schnell" and kwargs["headers"]["Authorization"] == "Bearer pk_free"
    assert ctx.files[0].endswith(".png")


def test_paid_image_models_ask_every_time_even_in_safe_mode(tmp_path):
    image = "data:image/png;base64," + base64.b64encode(PNG).decode()
    studio, web, config = studio_with(("POST", "openrouter.ai/api/v1/chat/completions", response(
        {"choices": [{"message": {"content": "", "images": [{"image_url": {"url": image}}]}}]})),
        image={"provider": "openrouter", "model": "google/gemini-3.1-flash-lite-image"})
    config.keys["openrouter"] = "sk-or"
    engine = ApprovalEngine(RuleStore(tmp_path), AuditLog(tmp_path), lambda: False, timeout=5)   # safe mode
    asked = []
    engine.notifiers.append(lambda p: asked.append(p) or engine.answer(p.id, True, True))
    ctx = context(tmp_path, studio, engine)
    for _ in range(2):
        tools().call("create_image", {"prompt": "a cat"}, ctx)
    assert len(asked) == 2 and "money" in asked[0].classes and not asked[0].can_remember
    assert web.requests[0][2]["json"]["modalities"] == ["image", "text"]
    assert (tmp_path / "ws" / ctx.files[0]).read_bytes() == PNG


def test_a_denied_paid_image_is_not_made(tmp_path):
    studio, web, config = studio_with(image={"provider": "openrouter", "model": "x"})
    config.keys["openrouter"] = "sk-or"
    engine = ApprovalEngine(RuleStore(tmp_path), AuditLog(tmp_path), lambda: True, timeout=5)
    engine.notifiers.append(lambda p: engine.answer(p.id, False))
    result = tools().call("create_image", {"prompt": "a cat"}, context(tmp_path, studio, engine))
    assert result.startswith("Not done") and web.requests == []


def test_your_own_server_can_make_images(tmp_path):
    studio, web, config = studio_with(("POST", "/images/generations", response(
        {"data": [{"b64_json": base64.b64encode(PNG).decode()}]})), image={"provider": "custom", "model": "flux"})
    config.custom_url, config.keys["custom"] = "http://192.168.1.5:8000/v1", "local-key"
    data, extension = studio.image("a cat", "1024x1024")
    assert data == PNG and extension == ".png"
    assert web.requests[0][1] == "http://192.168.1.5:8000/v1/images/generations"


def test_without_a_specialist_the_agent_is_told_where_to_set_one_up(tmp_path):
    studio, web, _ = studio_with()
    assert "panel" in tools().call("create_image", {"prompt": "x"}, context(tmp_path, studio))
    assert web.requests == []


# ---------- speech ----------
def test_pollinations_speech_needs_its_free_key(tmp_path):
    studio, web, config = studio_with(("GET", "gen.pollinations.ai/audio/", binary(MP3, "audio/mpeg")),
                                      speech={"provider": "pollinations", "voice": "nova", "model": ""})
    ctx = context(tmp_path, studio)
    assert "enter.pollinations.ai/keys" in tools().call("create_speech", {"text": "Merhaba Aykut"}, ctx)
    assert web.requests == []                       # no request that is sure to fail
    config.keys["pollinations"] = "pk_free"
    result = tools().call("create_speech", {"text": "Merhaba Aykut"}, ctx)
    assert "media/speech-" in result and ctx.files[0].endswith(".mp3")
    _, url, kwargs = web.requests[0]
    assert "Merhaba%20Aykut" in url and kwargs["params"]["voice"] == "nova"
    assert kwargs["headers"]["Authorization"] == "Bearer pk_free"


def test_this_computer_can_speak_offline(tmp_path, monkeypatch):
    monkeypatch.setattr(media.os, "name", "nt")
    calls = []

    def fake_powershell(argv, env, **kwargs):
        calls.append((argv, env))
        with open(env["PA_OUT"], "wb") as f:
            f.write(b"RIFFwave")
        return SimpleNamespace(returncode=0, stderr="")
    config = Config()
    config.media["speech"] = {"provider": "local", "voice": "Microsoft Zira Desktop", "model": ""}
    data, extension = Studio(config, run=fake_powershell).speech("hello there")
    assert (data, extension) == (b"RIFFwave", ".wav")
    argv, env = calls[0]
    assert argv[0] == "powershell" and env["PA_TEXT"] == "hello there"      # text never inside the script
    assert env["PA_VOICE"] == "Microsoft Zira Desktop"


# ---------- the writer specialist ----------
def test_the_writer_specialist_gets_the_prompt_and_can_save_a_file(tmp_path):
    studio, web, config = studio_with(("POST", "/chat/completions", response(
        {"choices": [{"message": {"content": "def add(a, b):\n    return a + b\n"}}]})),
        writer={"provider": "openrouter", "model": "cohere/north-mini-code:free"})
    config.keys["openrouter"] = "sk-or"
    ctx = context(tmp_path, studio)
    result = tools().call("ask_specialist", {"task": "Write an add function in Python", "save_as": "code/add.py"}, ctx)
    assert "code/add.py" in result and ctx.files == ["code/add.py"]
    assert (tmp_path / "ws" / "code" / "add.py").read_text(encoding="utf-8").startswith("def add")
    sent = web.requests[0][2]["json"]
    assert sent["model"] == "cohere/north-mini-code:free" and "add function" in sent["messages"][-1]["content"]
    assert ctx.tainted_by                              # another model's text: treated as untrusted output


def test_specialist_files_cannot_leave_the_workspace(tmp_path):
    studio, _, config = studio_with(("POST", "/chat/completions", response({"choices": [{"message": {"content": "x"}}]})),
                                    writer={"provider": "openrouter", "model": "m"})
    config.keys["openrouter"] = "sk-or"
    result = tools().call("ask_specialist", {"task": "x", "save_as": "../../evil.bat"}, context(tmp_path, studio))
    assert "outside the workspace" in result and not (tmp_path / "evil.bat").exists()


# ---------- the whole chain ----------
def test_the_agent_hands_the_prompt_to_the_image_specialist(make_runtime, monkeypatch):
    runtime, brain = make_runtime(call("create_image", prompt="A watercolor fox in a snowy forest"), say("Here it is."))
    runtime.config.media["image"] = {"provider": "pollinations", "model": ""}
    runtime.studio.http = FakeWeb(("GET", "image.pollinations.ai", binary(b"\xff\xd8jpeg", "image/jpeg")))
    answer = runtime.agent.run("panel", "Kar altında bir tilki çiz")
    assert answer.text == "Here it is." and len(answer.files) == 1 and answer.files[0].startswith("media/image-")


def test_specialist_settings_and_models_for_the_panel():
    studio, _, _ = studio_with(("GET", "gen.pollinations.ai/image/models", response([
        {"name": "flux.1-schnell", "title": "FLUX schnell", "category": "image", "output_modalities": ["image"], "paid_only": False},
        {"name": "gpt-image-2.5", "category": "image", "output_modalities": ["image"], "paid_only": True}])))
    assert [m["id"] for m in studio.models("image", "pollinations")] == ["flux.1-schnell"]
    assert set(media.IMAGE) == {"pollinations", "openrouter", "custom"}
    assert set(media.SPEECH) == {"pollinations", "local", "custom"}
    with pytest.raises(media.MediaError):
        studio.image("x", "1024x1024")                      # not set up
