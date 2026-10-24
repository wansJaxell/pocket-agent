from types import SimpleNamespace

import pytest
import requests

from pocketagent.config import BrainConfig, Config
from pocketagent.llm import (PROVIDERS, Brain, BrainError, Router, list_models, parse_arguments,
                             strip_thinking)


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


CALCULATE = {"type": "function", "function": {
    "name": "calculate", "description": "Do exact math.",
    "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]}}}


def test_text_mode_describes_the_tools_in_the_system_message():
    server = FakeServer(ok({"content": "hi"}))
    brain(server, native_tools=False).chat(
        [{"role": "system", "content": "You are Robi."}, {"role": "user", "content": "6*7?"}], [CALCULATE])
    sent = server.requests[0]["json"]
    assert sent["messages"][0]["content"].startswith("You are Robi.")
    assert "calculate(expression: string): Do exact math." in sent["messages"][0]["content"]
    assert '{"tool": "<tool name>"' in sent["messages"][0]["content"]
    assert "tools" not in sent


def test_http_errors_carry_the_status_code():
    with pytest.raises(BrainError) as error:
        brain(FakeServer(status(402, "no credit"))).chat([])
    assert error.value.status == 402


# ---------- the brain chain (fallbacks) ----------
def chain(*brains, keys=None):
    config = Config()
    config.set_brains(list(brains))
    config.keys = keys or {}
    return config


def router(config, server):
    return Router(config, http=server, retry_delay=0)


def test_rate_limited_brain_hands_over_to_the_next_free_one():
    config = chain(BrainConfig("groq", "https://groq.test/v1", "llama"),
                   BrainConfig("openrouter", "https://or.test/v1", "paid/model", free=False),
                   BrainConfig("gemini", "https://gemini.test/v1", "gemini-2.5-flash"),
                   keys={"groq": "g-key", "openrouter": "o-key", "gemini": "m-key"})
    server = FakeServer(status(429), ok({"content": "from gemini"}))
    reply = router(config, server).chat([{"role": "user", "content": "hi"}])
    assert reply.content == "from gemini"
    assert reply.brain == "Gemini · gemini-2.5-flash"
    assert reply.skipped == ["Groq · llama: HTTP 429"]
    # 429 is not retried when a fallback exists, and the paid model is never used as a fallback
    assert [r["url"] for r in server.requests] == ["https://groq.test/v1/chat/completions",
                                                   "https://gemini.test/v1/chat/completions"]
    assert server.requests[1]["headers"]["Authorization"] == "Bearer m-key"


@pytest.mark.parametrize("code", [402, 403])
def test_out_of_credit_or_forbidden_also_hands_over(code):
    config = chain(BrainConfig("openrouter", "https://or.test/v1", "a:free"), BrainConfig("groq", "https://g.test/v1", "b"))
    reply = router(config, FakeServer(status(code), ok({"content": "ok"}))).chat([])
    assert reply.brain == "Groq · b" and reply.skipped == [f"OpenRouter · a:free: HTTP {code}"]


@pytest.mark.parametrize("code", [404, 503])
def test_a_model_that_is_gone_or_down_also_hands_over(code):
    config = chain(BrainConfig("openrouter", "https://or.test/v1", "removed:free"), BrainConfig("groq", "https://g.test/v1", "b"))
    reply = router(config, FakeServer(status(code), ok({"content": "ok"}))).chat([])
    assert reply.brain == "Groq · b" and reply.skipped == [f"OpenRouter · removed:free: HTTP {code}"]


def test_when_every_brain_fails_the_error_lists_them_all():
    config = chain(BrainConfig("openrouter", "https://or.test/v1", "a:free"), BrainConfig("openrouter", "https://or.test/v1", "b:free"))
    server = FakeServer(status(429), status(404, "No endpoints found matching your data policy (Free model publication)"),
                        status(404, "No endpoints found matching your data policy"))
    with pytest.raises(BrainError) as error:
        router(config, server).chat([])
    message = str(error.value)
    assert "a:free: HTTP 429" in message and "settings/privacy" in message


def test_other_errors_are_not_hidden_by_the_fallback():
    config = chain(BrainConfig("groq", "https://g.test/v1", "a"), BrainConfig("gemini", "https://m.test/v1", "b"))
    server = FakeServer(status(401, "invalid api key"))
    with pytest.raises(BrainError, match="HTTP 401"):
        router(config, server).chat([])
    assert len(server.requests) == 1


def test_the_last_brain_still_retries_when_busy():
    config = chain(BrainConfig("groq", "https://g.test/v1", "a"))
    reply = router(config, FakeServer(status(429), ok({"content": "patience"}))).chat([])
    assert reply.content == "patience" and reply.skipped == []


def test_no_brain_yet_is_explained():
    with pytest.raises(BrainError, match="panel"):
        router(Config(), FakeServer()).chat([])


# ---------- providers and model lists ----------
def test_every_direct_key_provider_has_a_free_key_page():
    for provider in ("groq", "gemini", "nvidia", "github", "cerebras"):
        assert PROVIDERS[provider].needs_key and PROVIDERS[provider].key_url.startswith("https://")
    assert PROVIDERS["openrouter"].oauth
    assert PROVIDERS["gemini"].trains_on_data
    assert PROVIDERS["custom"].base_url == ""


class FakeModels:
    def __init__(self, body, status_code=200):
        self.body, self.status_code, self.calls = body, status_code, []

    def get(self, url, headers, timeout):
        self.calls.append((url, headers))
        return SimpleNamespace(status_code=self.status_code, json=lambda: self.body, text=str(self.body))


def ids(models):
    return [m["id"] for m in models]


OPENROUTER_CATALOG = {"data": [
    {"id": "openai/gpt-5", "pricing": {"prompt": "0.000002", "completion": "0.00001"}, "context_length": 400000,
     "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
     "supported_parameters": ["tools", "temperature"]},
    {"id": "cohere/north-mini-code:free", "pricing": {"prompt": "0", "completion": "0"}, "context_length": 256000,
     "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]}, "supported_parameters": ["tools"]},
    {"id": "nvidia/nemotron-3-ultra-550b-a55b:free", "pricing": {"prompt": "0", "completion": "0"},
     "context_length": 1000000, "created": 1760000000,
     "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]}, "supported_parameters": ["tools"]},
    {"id": "liquid/lfm-2.5-2.6b:free", "pricing": {"prompt": "0", "completion": "0"}, "context_length": 65536,
     "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]}, "supported_parameters": []},
    {"id": "google/lyria-3-clip-preview", "pricing": {"prompt": "0", "completion": "0"}, "context_length": 1048576,
     "architecture": {"input_modalities": ["text"], "output_modalities": ["text", "audio"]}},
    {"id": "nvidia/nemotron-3.5-content-safety:free", "pricing": {"prompt": "0", "completion": "0"},
     "context_length": 128000, "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]}},
    {"id": "openrouter/auto", "pricing": {"prompt": "-1", "completion": "-1"}, "context_length": 2000000,
     "architecture": {"input_modalities": ["text"], "output_modalities": ["text", "image"]}}]}


def test_openrouter_models_come_with_what_the_panel_needs_to_choose():
    models = list_models("openrouter", http=FakeModels(OPENROUTER_CATALOG))
    # free first, biggest context first; music models and safety classifiers are not chat brains
    assert ids(models) == ["nvidia/nemotron-3-ultra-550b-a55b:free", "cohere/north-mini-code:free",
                           "liquid/lfm-2.5-2.6b:free", "openai/gpt-5"]
    ultra = models[0]
    assert ultra == {"id": "nvidia/nemotron-3-ultra-550b-a55b:free", "free": True, "context": 1000000,
                     "tools": True, "input": ["text"], "created": 1760000000}
    assert models[2]["tools"] is False and models[3]["free"] is False
    assert models[3]["input"] == ["text", "image"]


def test_model_lists_from_gemini_and_the_github_catalog():
    gemini = list_models("gemini", "m-key", http=FakeModels(
        {"data": [{"id": "models/gemini-2.5-flash"}, {"id": "models/text-embedding-004"}]}))
    assert ids(gemini) == ["gemini-2.5-flash"]                       # no prefix, no embedding models
    assert gemini[0]["free"] is True and gemini[0]["tools"] is None   # unknown: the panel tests it
    github = FakeModels([{"id": "openai/gpt-4.1-mini", "capabilities": ["streaming", "tool-calling"],
                          "limits": {"max_input_tokens": 1048576}}])
    model = list_models("github", "ghp-x", http=github)[0]
    assert (model["id"], model["tools"], model["context"]) == ("openai/gpt-4.1-mini", True, 1048576)
    assert github.calls == [("https://models.github.ai/catalog/models", {"Authorization": "Bearer ghp-x"})]


def test_rejected_key_while_listing_models():
    with pytest.raises(BrainError) as error:
        list_models("groq", "bad", http=FakeModels({"error": "invalid"}, status_code=401))
    assert error.value.status == 401
