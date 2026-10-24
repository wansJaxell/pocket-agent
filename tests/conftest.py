import json
from types import SimpleNamespace

import pytest

from pocketagent.config import Config
from pocketagent.llm import Reply, ToolCall


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    """Every test gets its own empty PocketAgent folder."""
    monkeypatch.setenv("POCKETAGENT_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


class FakeBrain:
    """Replays scripted replies instead of calling a real model, and records what it was sent."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def chat(self, messages, tools=None):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        return self.replies.pop(0)


def call(name, **arguments):
    return Reply(content="", tool_calls=[ToolCall(id=f"call_{name}", name=name, arguments=arguments)])


def say(text):
    return Reply(content=text)


@pytest.fixture
def make_runtime():
    from pocketagent.cli import Runtime

    def build(*replies, native_tools=True):
        config = Config()
        config.brain.native_tools = native_tools
        brain = FakeBrain(*replies)
        return Runtime(config, brain=brain), brain
    return build


def response(body, status=200):
    """A small stand-in for requests.Response."""
    return SimpleNamespace(status_code=status, json=lambda: body, text=json.dumps(body))


class FakeWeb:
    """Plays every web API at once (model providers, Telegram, OpenRouter) and records each request.

    Routes are (method, part of the URL, response or function(url, kwargs) -> response).
    """

    def __init__(self, *routes):
        self.routes, self.requests = list(routes), []

    def get(self, url, **kwargs):
        return self._answer("GET", url, kwargs)

    def post(self, url, **kwargs):
        return self._answer("POST", url, kwargs)

    def _answer(self, method, url, kwargs):
        self.requests.append((method, url, kwargs))
        for route_method, part, answer in self.routes:
            if route_method == method and part in url:
                return answer(url, kwargs) if callable(answer) else answer
        raise ConnectionError(f"FakeWeb has no route for {method} {url}")


def model_reply(url, kwargs):
    """A model server that calls the tool when tools are offered, otherwise answers 'OK'."""
    if kwargs["json"].get("tools"):
        message = {"content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "get_current_time", "arguments": "{}"}}]}
    else:
        message = {"content": "OK"}
    return response({"choices": [{"message": message}]})


def telegram_routes(owner=111, username="aykut_agent_bot"):
    """Telegram where the token is valid and the owner presses START (an old message from 666 is ignored)."""
    def updates(url, kwargs):
        if kwargs["json"].get("offset") == -1:
            return response({"result": [{"update_id": 5, "message": {"chat": {"id": 666}}}]})
        if kwargs["json"].get("timeout"):
            return response({"result": [{"update_id": 6, "message": {"chat": {"id": owner}}}]})
        return response({"result": []})
    return [("GET", "/getMe", response({"ok": True, "result": {"username": username}})),
            ("POST", "/getUpdates", updates),
            ("POST", "/sendMessage", response({"ok": True}))]
