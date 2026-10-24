"""Turning brains and providers on and off, and handling free-tier limits without wasting requests."""

import time
from types import SimpleNamespace

import pytest
from conftest import FakeWeb, response

from pocketagent import config as cfg
from pocketagent.app import App, PanelError
from pocketagent.config import BrainConfig, Config
from pocketagent.llm import PROVIDERS, BrainError, Router, check_key, probe


class Server:
    """A model server whose answers depend on the model asked for; records the models asked."""

    def __init__(self, answers):
        self.answers, self.asked = answers, []

    def post(self, url, json, headers, timeout):
        self.asked.append(json["model"])
        answer = self.answers[json["model"]]
        if isinstance(answer, tuple):
            code, text, extra = (answer + ({},))[:3]
            return SimpleNamespace(status_code=code, text=text, headers=extra, json=lambda: {})
        return SimpleNamespace(status_code=200, text="", headers={},
                               json=lambda: {"choices": [{"message": {"content": answer}}]})


def chain(*brains, keys=None, disabled=()):
    config = Config()
    config.set_brains(list(brains))
    config.keys = {"openrouter": "o", "groq": "g", "nvidia": "n"} if keys is None else keys
    config.disabled_providers = list(disabled)
    return config


OR_A = BrainConfig("openrouter", "https://or.test/v1", "a:free")
OR_B = BrainConfig("openrouter", "https://or.test/v1", "b:free")
GROQ = BrainConfig("groq", "https://groq.test/v1", "llama")
DAILY = (429, '{"error":{"message":"Rate limit exceeded: free-models-per-day. Add 10 credits to unlock 1000"}}')


def test_brains_that_are_off_are_skipped():
    off = BrainConfig("openrouter", "https://or.test/v1", "a:free", enabled=False)
    server = Server({"llama": "from groq"})
    reply = Router(chain(off, GROQ), http=server, retry_delay=0).chat([])
    assert reply.brain == "Groq · llama" and server.asked == ["llama"]


def test_a_provider_that_is_off_is_skipped_entirely():
    server = Server({"llama": "from groq"})
    Router(chain(OR_A, OR_B, GROQ, disabled=["openrouter"]), http=server, retry_delay=0).chat([])
    assert server.asked == ["llama"]


def test_a_brain_without_a_key_is_skipped_instead_of_failing():
    server = Server({"llama": "from groq"})
    Router(chain(OR_A, GROQ, keys={"groq": "g"}), http=server, retry_delay=0).chat([])
    assert server.asked == ["llama"]


def test_openrouters_daily_free_limit_is_remembered_until_it_resets():
    reset = int((time.time() + 3600) * 1000)
    server = Server({"a:free": DAILY + ({"X-RateLimit-Reset": str(reset)},), "b:free": "never asked", "llama": "groq"})
    router = Router(chain(OR_A, OR_B, GROQ), http=server, retry_delay=0)
    reply = router.chat([])
    assert reply.content == "groq" and server.asked == ["a:free", "llama"]        # b:free is not even tried
    assert "daily free limit" in reply.skipped[0]
    router.chat([])
    assert server.asked == ["a:free", "llama", "llama"]                           # no wasted request
    assert router.status()["openrouter_free_until"] is not None
    router.cooldowns["openrouter-free"] = time.time() - 1                         # the limit has reset
    server.answers["a:free"] = "back"
    assert router.chat([]).content == "back"


def test_a_model_only_for_other_apps_is_reported_once():
    problems = []
    server = Server({"a:free": (403, '{"error":{"message":"a:free is only available on agentic harnesses."}}'),
                     "llama": "groq"})
    router = Router(chain(OR_A, GROQ), http=server, retry_delay=0)
    router.on_problem = lambda brain, kind, error: problems.append((brain.model, kind))
    assert router.chat([]).content == "groq"
    assert problems == [("a:free", "app_only")]


def test_probe_needs_one_request_when_the_catalog_knows_about_tools():
    calls = []

    class Fake:
        def __init__(self, config):
            pass

        def chat(self, messages, tools=None):
            calls.append(tools)
            return SimpleNamespace(content="OK", tool_calls=[])
    assert probe(GROQ, Fake, known_tools=True) == ("OK", True)
    assert calls == [None]


class KeyCheck:
    def __init__(self, status):
        self.status, self.sent = status, []

    def post(self, url, json, headers, timeout):
        self.sent.append((url, json))
        return SimpleNamespace(status_code=self.status, text="", headers={})


def test_nvidia_keys_are_checked_with_one_tiny_request():
    # NVIDIA's model list answers any key, so a 1-token chat request checks it
    with pytest.raises(BrainError) as error:
        check_key("nvidia", "nvapi-wrong", KeyCheck(401))
    assert error.value.status == 401
    check_key("nvidia", "nvapi-right", KeyCheck(404))         # the model may be gone, but the key was accepted
    sent = KeyCheck(200)
    check_key("nvidia", "nvapi-right", sent)
    assert sent.sent[0][1]["max_tokens"] == 1 and sent.sent[0][0].endswith("/chat/completions")


# ---------- the panel's side ----------
def make_app(*routes):
    return App(Config(), http=FakeWeb(*routes))


def test_a_wrong_key_can_be_deleted(home):
    app = make_app()
    app.config.keys["nvidia"] = "nvapi-wrong"
    app.delete_key("nvidia")
    assert "nvidia" not in app.config.keys and "nvidia" not in cfg.load().keys
    assert next(p for p in app.state()["providers"] if p["id"] == "nvidia")["has_key"] is False
    with pytest.raises(PanelError):
        app.delete_key("nvidia")


def test_brains_and_providers_can_be_switched_off_and_on(home):
    app = make_app()
    app.config.keys.update({"openrouter": "o", "groq": "g"})
    app.config.set_brains([OR_A, GROQ])
    app.toggle_brain(1, False)
    assert cfg.load().fallbacks[0].enabled is False
    assert app.state()["brains"][1]["enabled"] is False and app.state()["brains"][1]["problem"] == "off"
    app.toggle_brain(1, True)
    app.set_provider_enabled("openrouter", False)
    state = app.state()
    assert next(p for p in state["providers"] if p["id"] == "openrouter")["enabled"] is False
    assert state["brains"][0]["problem"] == "provider_off" and state["brains"][1]["problem"] == ""
    with pytest.raises(PanelError):
        app.sync_free_models()                                # OpenRouter is off
    app.set_provider_enabled("openrouter", True)
    assert cfg.load().disabled_providers == []


def test_a_model_only_for_other_apps_is_turned_off_and_never_added_again(home):
    app = make_app()
    app.config.keys["openrouter"] = "o"
    app.config.set_brains([OR_A, GROQ])
    app.config.keys["groq"] = "g"
    app._model_problem(app.config.brains()[0], "app_only", BrainError("only available on agentic harnesses", 403))
    assert app.config.brain.enabled is False and "a:free" in app.config.free_sync["skip"]
    assert "a:free" in app.notices[-1]["text"]


def test_adding_a_model_only_for_other_apps_explains_why(home):
    app = make_app(("POST", "/chat/completions", response(
        {"error": {"message": "thinkingmachines/inkling:free is only available on agentic harnesses."}}, 403)))
    app.config.keys["openrouter"] = "o"
    with pytest.raises(PanelError, match="other apps"):
        app.add_brain("openrouter", "thinkingmachines/inkling:free")
    assert "thinkingmachines/inkling:free" in app.config.free_sync["skip"]
