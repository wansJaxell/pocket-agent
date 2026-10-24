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
