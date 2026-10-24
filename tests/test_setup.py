from types import SimpleNamespace

from conftest import FakeBrain, call, say

from pocketagent import config as cfg
from pocketagent.config import Config
from pocketagent.setup_wizard import detect_local_models, run_setup


class ScriptedIO:
    """Types the given answers, one per question, and records what the wizard printed."""

    def __init__(self, *answers):
        self.answers, self.output = list(answers), []

    def say(self, text=""):
        self.output.append(text)

    def ask(self, prompt, default=""):
        self.output.append(f"? {prompt}")
        answer = self.answers.pop(0)
        return answer or default

    @property
    def text(self):
        return "\n".join(self.output)


class FakeHttp:
    """Ollama on localhost with one model, and a Telegram where the owner presses START."""

    def __init__(self, ollama_models=("qwen3.5:9b",), ollama_running=True, token_ok=True):
        self.ollama_models, self.ollama_running, self.token_ok = ollama_models, ollama_running, token_ok
        self.posts = []

    def get(self, url, timeout):
        if "11434" in url:
            if not self.ollama_running:
                raise ConnectionError("refused")
            return SimpleNamespace(json=lambda: {"models": [{"name": m} for m in self.ollama_models]})
        if "1234" in url:
            raise ConnectionError("refused")
        if url.endswith("/getMe"):
            body = {"ok": True, "result": {"username": "aykut_agent_bot"}} if self.token_ok else {"ok": False}
            return SimpleNamespace(json=lambda: body)
        raise AssertionError(url)

    def post(self, url, json, timeout):
        self.posts.append((url.rsplit("/", 1)[-1], json))
        if url.endswith("/getUpdates"):
            if json.get("offset") == -1:      # old messages from before setup
                return SimpleNamespace(json=lambda: {"result": [{"update_id": 5, "message": {"chat": {"id": 666}}}]})
            if json.get("timeout"):
                return SimpleNamespace(json=lambda: {"result": [{"update_id": 6, "message": {"chat": {"id": 111}}}]})
            return SimpleNamespace(json=lambda: {"result": []})
        return SimpleNamespace(json=lambda: {"ok": True})


def brain_with_tools(_config):
    return FakeBrain(say("OK"), call("get_current_time"))


def brain_without_tools(_config):
    return FakeBrain(say("OK"), say("It is noon."))


def test_detects_ollama_models():
    assert detect_local_models(FakeHttp()) == {"ollama": ["qwen3.5:9b"]}
    assert detect_local_models(FakeHttp(ollama_running=False)) == {}


def test_full_setup_with_local_ollama_and_telegram():
    http = FakeHttp()
    io = ScriptedIO("1", "y", "123:ABC")      # pick Ollama model, connect Telegram, paste token
    config = run_setup(Config(), io=io, http=http, brain_factory=brain_with_tools)

    assert (config.brain.provider, config.brain.model) == ("ollama", "qwen3.5:9b")
    assert config.brain.base_url == "http://localhost:11434/v1"
    assert config.brain.native_tools is True
    assert config.telegram.owner_chat_id == 111            # the new message, not the old one (666)
    assert ("sendMessage", {"chat_id": 111, "text": "✅ PocketAgent is connected. Only this chat can talk to me."}) \
        in http.posts
    assert cfg.load().telegram.owner_chat_id == 111        # saved to disk


def test_cloud_provider_and_text_tool_fallback():
    http = FakeHttp(ollama_running=False)
    # options: 1 nvidia, 2 openrouter, 3 groq, 4 custom -> NVIDIA, paste key, accept suggested model, skip Telegram
    io = ScriptedIO("1", "nvapi-test", "", "n")
    config = run_setup(Config(), io=io, http=http, brain_factory=brain_without_tools)
    assert config.brain.base_url == "https://integrate.api.nvidia.com/v1"
    assert config.brain.api_key == "nvapi-test"
    assert config.brain.model == "nvidia/nemotron-3-super-120b-a12b"
    assert config.brain.native_tools is False
    assert "install Ollama" in io.text
    assert not config.telegram_ready


def test_wrong_telegram_token_is_rejected():
    http = FakeHttp(token_ok=False)
    io = ScriptedIO("1", "y", "bad", "bad", "bad")
    config = run_setup(Config(), io=io, http=http, brain_factory=brain_with_tools)
    assert io.text.count("did not accept this token") == 3
    assert not config.telegram_ready
