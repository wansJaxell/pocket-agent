from types import SimpleNamespace

import pytest
import requests

from pocketagent.config import BrainConfig
from pocketagent.llm import Brain, BrainError, parse_arguments, strip_thinking


class FakeServer:
    """Plays the model server: returns prepared HTTP responses and records each request."""

    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []

    def post(self, url, json, headers, timeout):
        self.requests.append({"url": url, "json": json, "headers": headers})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def ok(message):
    return SimpleNamespace(status_code=200, json=lambda: {"choices": [{"message": message}]}, text="")


def status(code, text="error"):
    return SimpleNamespace(status_code=code, json=lambda: {}, text=text)


def brain(server, **config):
    defaults = {"base_url": "http://localhost:11434/v1/", "model": "qwen3.5:9b"}
    return Brain(BrainConfig(**{**defaults, **config}), http=server, retry_delay=0)


def test_sends_openai_format_and_reads_tool_calls():
    server = FakeServer(ok({"content": None, "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "calculate", "arguments": '{"expression": "2+2"}'}}]}))
    reply = brain(server, api_key="nvapi-x").chat([{"role": "user", "content": "x"}], tools=[{"t": 1}])
    sent = server.requests[0]
    assert sent["url"] == "http://localhost:11434/v1/chat/completions"
    assert sent["json"]["model"] == "qwen3.5:9b" and sent["json"]["tools"] == [{"t": 1}]
    assert sent["headers"]["Authorization"] == "Bearer nvapi-x"
    assert reply.tool_calls[0].name == "calculate" and reply.tool_calls[0].arguments == {"expression": "2+2"}


def test_local_server_gets_no_auth_header_and_no_tools_in_text_mode():
    server = FakeServer(ok({"content": "hi"}))
    reply = brain(server, native_tools=False).chat([], tools=[{"t": 1}])
    assert reply.content == "hi"
    assert "tools" not in server.requests[0]["json"]
    assert "Authorization" not in server.requests[0]["headers"]


def test_retries_when_busy_then_succeeds():
    server = FakeServer(status(429), status(503), ok({"content": "finally"}))
    assert brain(server).chat([]).content == "finally"
    assert len(server.requests) == 3


def test_clear_error_when_server_is_down():
    server = FakeServer(*[requests.ConnectionError("refused")] * 3)
    with pytest.raises(BrainError, match="Is the model server"):
        brain(server).chat([])


def test_clear_error_on_bad_key():
    with pytest.raises(BrainError, match="HTTP 401"):
        brain(FakeServer(status(401, "invalid api key"))).chat([])


def test_broken_tool_arguments_become_empty_dict():
    assert parse_arguments("{not json") == {}
    assert parse_arguments('["a list"]') == {}
    assert parse_arguments({"already": "dict"}) == {"already": "dict"}


def test_strip_thinking():
    assert strip_thinking("<think>\nhmm\n</think>\n\nAnswer") == "Answer"
