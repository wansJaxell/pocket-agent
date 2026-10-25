"""Things that made the agent stall or give up: retired providers, unreadable lists, slow brains, shells."""

from types import SimpleNamespace

import pytest
import requests
from conftest import FakeWeb, response, say

from pocketagent.app import App, PanelError
from pocketagent.config import BrainConfig, Config
from pocketagent.llm import PROVIDERS, Brain, BrainError, Router, list_models
from pocketagent.skills import shell


# ---------- providers ----------
def test_github_models_is_retired_and_skipped():
    assert PROVIDERS["github"].retired
    config = Config()
    config.set_brains([BrainConfig("github", PROVIDERS["github"].base_url, "openai/gpt-4.1-mini"),
                       BrainConfig("groq", PROVIDERS["groq"].base_url, "llama")])
    config.keys = {"github": "ghp", "groq": "g"}
    router = Router(config)
    assert router.usable(config.chain()[0]) == "retired"
    assert [b.model for b in router.candidates()] == ["llama"]


def test_the_panel_no_longer_offers_github_and_explains_why(home):
    app = App(Config(), http=FakeWeb())
    assert "github" not in [p["id"] for p in app.state()["providers"]]
    with pytest.raises(PanelError, match="retired"):
        app.save_key("github", "github_pat_x")


def test_an_unreadable_model_list_is_an_error_not_a_crash():
    plain = SimpleNamespace(status_code=200, text="OK", json=lambda: (_ for _ in ()).throw(ValueError("no JSON")))
    with pytest.raises(BrainError, match="model list"):
        list_models("groq", "g", http=SimpleNamespace(get=lambda *a, **k: plain))


def test_speech_models_are_not_offered_as_brains():
    body = {"data": [{"id": "canopylabs/orpheus-v1-english"}, {"id": "playai-tts"}, {"id": "openai/gpt-oss-120b"}]}
    listed = list_models("groq", "g", http=SimpleNamespace(get=lambda *a, **k: SimpleNamespace(
        status_code=200, json=lambda: body, text="")))
    assert [m["id"] for m in listed] == ["openai/gpt-oss-120b"]


# ---------- slow brains never freeze a turn ----------
class Slow:
    def __init__(self, answers):
        self.answers, self.timeouts = answers, []

    def post(self, url, json, headers, timeout):
        self.timeouts.append(timeout)
        answer = self.answers[json["model"]]
        if answer == "slow":
            raise requests.ReadTimeout("read timed out")
        return SimpleNamespace(status_code=200, headers={}, text="",
                               json=lambda: {"choices": [{"message": {"content": answer}}]})


def test_a_brain_that_does_not_answer_in_time_hands_over():
    config = Config()
    config.set_brains([BrainConfig("groq", "https://g.test/v1", "big"), BrainConfig("gemini", "https://m.test/v1", "fast")])
    config.keys = {"groq": "g", "gemini": "m"}
    server = Slow({"big": "slow", "fast": "here"})
    reply = Router(config, http=server, retry_delay=0).chat([])
    assert reply.content == "here" and reply.skipped == ["Groq · big: HTTP 408"]
    assert server.timeouts[0] == (10, 120)           # 10 s to connect, 2 minutes to answer


def test_a_single_slow_brain_explains_itself():
    with pytest.raises(BrainError) as error:
        Brain(BrainConfig("groq", "https://g.test/v1", "big"), http=Slow({"big": "slow"}), retry_delay=0).chat([])
    assert error.value.status == 408 and "2 minutes" in str(error.value)


# ---------- Windows shells ----------
def test_commands_with_and_and_run_in_cmd_when_only_windows_powershell_exists(monkeypatch):
    monkeypatch.setattr(shell.os, "name", "nt")
    monkeypatch.setattr(shell.shutil, "which", lambda name: None)
    assert shell._argv("python --version && pip --version")[:4] == ["cmd", "/d", "/s", "/c"]
    assert shell._argv("Get-ChildItem")[0] == "powershell"
    monkeypatch.setattr(shell.shutil, "which", lambda name: "C:/Program Files/PowerShell/7/pwsh.exe" if name == "pwsh" else None)
    assert shell._argv("python --version && pip --version")[0] == "pwsh"       # PowerShell 7 knows &&


# ---------- the agent is pointed at its browser ----------
def test_with_computer_use_the_agent_is_told_to_read_pages_with_its_browser(make_runtime):
    runtime, brain = make_runtime(say("ok"))
    runtime.config.computer_use = True
    runtime.agent.ask("1", "İstanbul-Malé uçak fiyatlarına bak")
    system = brain.calls[0]["messages"][0]["content"]
    assert "browser_go" in system and "Never install packages" in system


def test_tool_descriptions_say_which_tool_can_read_what(make_runtime):
    runtime, _ = make_runtime()
    tools = runtime.registry.tools
    assert "browser_go" in tools["fetch_webpage"].description
    assert "cannot read" in tools["open_in_browser"].description
