"""The "brain": any OpenAI-compatible chat API.

Local and free:   Ollama, LM Studio
Free cloud tiers: OpenRouter, Groq, Google AI Studio (Gemini), NVIDIA, GitHub Models, Cerebras
They all speak the same API, so one small client covers every option.
Only `requests` is used (no heavy SDK), so the agent also installs on Android (Termux).

The user can line up several brains in priority order (the Router): when one is out of free
credit, rate-limited, gone or down (HTTP 402/403/404/429/5xx), the next free one answers instead.
"""

import json
import re
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone

import requests

from pocketagent.config import BrainConfig, Config


@dataclass(frozen=True)
class Provider:
    label: str
    base_url: str
    needs_key: bool
    key_url: str = ""             # where the "Get your free key" button goes
    suggested_model: str = ""
    name: str = ""                # short name shown under each answer
    models_url: str = ""          # the model list, when it is not at {base_url}/models
    oauth: bool = False           # sign in from the browser instead of pasting a key
    trains_on_data: bool = False  # the free tier may use your messages to train models
    local: bool = False           # runs on this computer
    key_check_url: str = ""       # checks the key itself, when the model list answers any key
    key_check_chat: bool = False  # no such page: a 1-token chat request checks the key instead
    retired: bool = False         # the service was shut down: hidden in the panel, its brains are skipped


PROVIDERS: dict[str, Provider] = {
    "openrouter": Provider("OpenRouter (free models, sign in from the browser)", "https://openrouter.ai/api/v1", True,
                           key_url="https://openrouter.ai/keys", name="OpenRouter", oauth=True,
                           key_check_url="https://openrouter.ai/api/v1/key"),
    "groq": Provider("Groq (free tier, very fast)", "https://api.groq.com/openai/v1", True,
                     key_url="https://console.groq.com/keys", suggested_model="llama-3.3-70b-versatile", name="Groq"),
    "gemini": Provider("Google AI Studio: Gemini (free tier)", "https://generativelanguage.googleapis.com/v1beta/openai",
                       True, key_url="https://aistudio.google.com/apikey", suggested_model="gemini-3.5-flash",
                       name="Gemini", trains_on_data=True),
    "nvidia": Provider("NVIDIA build.nvidia.com (free tier)", "https://integrate.api.nvidia.com/v1", True,
                       key_url="https://build.nvidia.com", suggested_model="nvidia/nemotron-3-super-120b-a12b",
                       name="NVIDIA", key_check_chat=True),
    # GitHub retired GitHub Models on 30 July 2026; kept so old settings still load
    "github": Provider("GitHub Models (retired by GitHub on 30 July 2026)", "https://models.github.ai/inference", True,
                       key_url="https://github.com/settings/personal-access-tokens/new",
                       suggested_model="openai/gpt-4.1-mini", name="GitHub Models",
                       models_url="https://models.github.ai/catalog/models", key_check_chat=True, retired=True),
    "cerebras": Provider("Cerebras (free tier)", "https://api.cerebras.ai/v1", True,
                         key_url="https://cloud.cerebras.ai", suggested_model="gpt-oss-120b", name="Cerebras"),
    "ollama": Provider("Ollama (local, free)", "http://localhost:11434/v1", False,
                       suggested_model="qwen3.5:9b", name="Ollama", local=True),
    "lmstudio": Provider("LM Studio (local, free)", "http://localhost:1234/v1", False, name="LM Studio", local=True),
    "custom": Provider("Other OpenAI-compatible API", "", True, name="Custom"),
}

RETRY_STATUS = {429, 500, 502, 503, 504}   # busy or temporarily broken: worth another try
# out of credit, refused, model gone (free models come and go), rate-limited or down: the next brain answers.
# A wrong key (401) or a bad request (400) is not handed over: it needs fixing.
FAILOVER_STATUS = {402, 403, 404, 408, 429, 500, 502, 503, 504}


def hint(status: int | None, text: str) -> str:
    """A sentence that says how to fix a common provider error."""
    if "data policy" in text.lower():
        return (" OpenRouter refuses free models with your privacy settings: allow them at "
                "https://openrouter.ai/settings/privacy")
    if "free-models-per-day" in text.lower():
        return (" OpenRouter's daily free limit is used up (50 requests a day for the whole account, 1000 after a "
                "one-time $10 top-up); add a brain from another provider to keep going.")
    if "agentic harness" in text.lower():
        return " OpenRouter keeps this free model for some other apps only: PocketAgent cannot use it."
    if status == 401:
        return " The API key is wrong or was revoked: save it again in the panel."
    if status == 404:
        return " This model is not (or no longer) available for your account."
    return ""


class BrainError(Exception):
    """The model server could not be reached or refused the request."""

    def __init__(self, message: str, status: int | None = None, text: str = "", headers=None):
        super().__init__(message)
        self.status, self.text, self.headers = status, text, dict(headers or {})


def problem_of(error: BrainError) -> str:
    """Name the provider problems that need more than "try the next brain"."""
    text = (error.text or str(error)).lower()
    if error.status == 429 and "free-models-per-day" in text:
        return "daily_quota"         # OpenRouter: 50 free requests a day per account (1000 after a $10 top-up)
    if error.status == 403 and "agentic harness" in text:
        return "app_only"            # OpenRouter: this free model is only for some listed apps
    if "data policy" in text:
        return "data_policy"
    return ""


def is_openrouter_free(brain: BrainConfig) -> bool:
    return brain.provider == "openrouter" and (brain.model.endswith(":free") or brain.model == "openrouter/free")


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Reply:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    brain: str = ""                                    # which brain answered, e.g. "Groq · llama-3.3-70b"
    skipped: list[str] = field(default_factory=list)   # brains that refused first, e.g. "...: HTTP 429"


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_thinking(text: str) -> str:
    """Remove the <think>...</think> block some local models (e.g. Qwen) put before the answer."""
    return _THINK.sub("", text or "").strip()


def parse_arguments(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


TEXT_TOOLS = """

You can use these tools:
{tools}

To use a tool, reply with ONLY this JSON and nothing else:
{{"tool": "<tool name>", "arguments": {{<arguments>}}}}
You will get the result back, then call another tool or write your final answer."""


def describe_tools(schemas: list[dict]) -> str:
    """Text description of the tools, for models without native tool calling."""
    lines = []
    for schema in schemas:
        function = schema.get("function", {}) if isinstance(schema, dict) else {}
        properties = function.get("parameters", {}).get("properties", {})
        args = ", ".join(f"{name}: {p.get('type', 'string')}" for name, p in properties.items())
        lines.append(f"- {function.get('name', '?')}({args}): {function.get('description', '')}")
    return "\n".join(lines)


def with_text_tools(messages: list[dict], tools: list[dict]) -> list[dict]:
    """A copy of the messages whose system message also explains how to call the tools in plain text."""
    text = TEXT_TOOLS.format(tools=describe_tools(tools))
    messages = [dict(m) for m in messages]
    if messages and messages[0].get("role") == "system":
        messages[0]["content"] = (messages[0].get("content") or "") + text
    else:
        messages.insert(0, {"role": "system", "content": text.strip()})
    return messages


def brain_label(config: BrainConfig) -> str:
    provider = PROVIDERS.get(config.provider)
    return f"{provider.name if provider else config.provider or 'Brain'} · {config.model}"


class Brain:
    def __init__(self, config: BrainConfig, http=None, retries: int = 2, retry_delay: float = 2.0,
                 retry_status=RETRY_STATUS):
        self.config = config
        self.http = http or requests.Session()
        self.retries, self.retry_delay, self.retry_status = retries, retry_delay, set(retry_status)

    @property
    def label(self) -> str:
        return brain_label(self.config)

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> Reply:
        body = {"model": self.config.model, "messages": messages, "temperature": 0.3}
        if tools and self.config.native_tools:
            body["tools"] = tools
        elif tools:
            body["messages"] = with_text_tools(messages, tools)
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        url = self.config.base_url.rstrip("/") + "/chat/completions"

        for attempt in range(self.retries + 1):
            last_try = attempt == self.retries
            try:
                # 10 s to connect, 2 minutes to answer: a hanging server must not freeze the turn
                response = self.http.post(url, json=body, headers=headers, timeout=(10, 120))
            except requests.Timeout as error:
                raise BrainError(f"{self.label} did not answer within 2 minutes", status=408) from error
            except requests.ConnectionError as error:
                if last_try:
                    raise BrainError(f"cannot connect to {self.config.base_url}. "
                                     "Is the model server (e.g. Ollama) running?") from error
                time.sleep(self.retry_delay * (attempt + 1))
                continue
            if response.status_code in self.retry_status and not last_try:
                time.sleep(self.retry_delay * (attempt + 1))
                continue
            if response.status_code >= 400:
                raise BrainError(f"the model server answered HTTP {response.status_code}: {response.text[:300]}"
                                 + hint(response.status_code, response.text), status=response.status_code,
                                 text=response.text, headers=getattr(response, "headers", None))
            message = response.json()["choices"][0]["message"]
            calls = [ToolCall(id=c.get("id") or f"call_{i}", name=c["function"]["name"],
                              arguments=parse_arguments(c["function"].get("arguments")))
                     for i, c in enumerate(message.get("tool_calls") or [])]
            return Reply(content=message.get("content") or "", tool_calls=calls, brain=self.label)
        raise BrainError("no answer from the model server")   # not reached; keeps type checkers happy


class Router:
    """The user's brains in priority order. The first one answers; on HTTP 402/403/404/429/5xx the
    next *free* brain in the list takes over. The reply says which brain answered and which refused."""

    def __init__(self, config: Config, http=None, retry_delay: float = 2.0):
        self.config = config        # read on every call, so changes made in the panel apply at once
        self.http = http or requests.Session()
        self.retry_delay = retry_delay
        self.cooldowns: dict[str, float] = {}   # "openrouter-free" -> time when the daily limit resets
        self.on_problem = None                  # called with (brain, problem, error), e.g. to switch a brain off

    def usable(self, brain: BrainConfig) -> str:
        """Why a brain cannot be used right now ("" if it can)."""
        if not brain.enabled:
            return "off"
        if brain.provider in self.config.disabled_providers:
            return "provider_off"
        provider = PROVIDERS.get(brain.provider)
        if provider and provider.retired:
            return "retired"
        if provider and provider.needs_key and brain.provider != "custom" and not brain.api_key:
            return "no_key"
        if is_openrouter_free(brain) and self.cooldowns.get("openrouter-free", 0) > time.time():
            return "daily_quota"
        return ""

    def candidates(self) -> list[BrainConfig]:
        chain = [b for b in self.config.chain() if not self.usable(b)]
        return chain[:1] + [b for b in chain[1:] if b.free]

    def status(self) -> dict:
        until = self.cooldowns.get("openrouter-free", 0)
        return {"openrouter_free_until": datetime.fromtimestamp(until).isoformat(timespec="minutes")
                if until > time.time() else None}

    def _daily_quota(self, error: BrainError) -> None:
        """Remember until when OpenRouter's free models are used up (its reset header, or next UTC midnight)."""
        try:
            until = int(error.headers.get("X-RateLimit-Reset") or error.headers.get("x-ratelimit-reset")) / 1000
        except (TypeError, ValueError):
            tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
            until = datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=timezone.utc).timestamp()
        self.cooldowns["openrouter-free"] = until

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> Reply:
        candidates = self.candidates()
        if not candidates:
            raise BrainError("no brain is connected yet, or every brain is switched off: open the panel")
        skipped = []
        for number, config in enumerate(candidates, 1):
            last = number == len(candidates)
            if self.usable(config):           # e.g. the daily limit was hit by an earlier brain in this call
                if last and not skipped:
                    raise BrainError("no brain can answer right now")
                continue
            # with a fallback waiting, a rate limit is not worth waiting for
            brain = Brain(config, http=self.http, retry_delay=self.retry_delay,
                          retry_status=RETRY_STATUS if last else RETRY_STATUS - FAILOVER_STATUS)
            try:
                reply = brain.chat(messages, tools)
            except BrainError as error:
                problem = problem_of(error)
                if problem == "daily_quota":
                    self._daily_quota(error)
                    skipped.append(f"OpenRouter: daily free limit (until {self.status()['openrouter_free_until'][11:]})")
                elif problem and self.on_problem:
                    self.on_problem(config, problem, error)
                if error.status in FAILOVER_STATUS and not last:
                    if problem != "daily_quota":
                        skipped.append(f"{brain.label}: HTTP {error.status}")
                    continue
                if skipped:          # say what happened to every brain, not only the last one
                    raise BrainError(f"no brain could answer: {'; '.join(skipped)}; {brain.label}: {error}",
                                     status=error.status) from error
                raise
            return replace(reply, brain=brain.label, skipped=skipped)
        raise BrainError("no brain answered")   # not reached


TIME_TOOL = {"type": "function", "function": {
    "name": "get_current_time", "description": "Get the current date and time.",
    "parameters": {"type": "object", "properties": {}, "required": []}}}


def probe(config: BrainConfig, brain_factory=Brain, known_tools: bool | None = None) -> tuple[str, bool]:
    """Check a brain answers (raises BrainError if not), then whether it supports native tool calls.

    known_tools: what the provider's model list says; then one request is enough (free quotas are small).
    """
    brain = brain_factory(replace(config, native_tools=True))
    answer = brain.chat([{"role": "user", "content": "Reply with the single word OK."}]).content
    if known_tools is not None:
        return strip_thinking(answer), known_tools
    try:
        reply = brain.chat([{"role": "user", "content": "What time is it now? Use your tool."}], [TIME_TOOL])
        native = bool(reply.tool_calls)
    except Exception:
        native = False
    return strip_thinking(answer), native


_NOT_CHAT = re.compile(r"embed|whisper|tts|rerank|moderation|guard|safety|dall-e|image|audio|transcrib|lyria|"
                       r"orpheus|playai",
                       re.IGNORECASE)


def _is_free(model: dict) -> bool:
    pricing = model.get("pricing") or {}
    try:
        zero = float(pricing.get("prompt", 1)) == 0 and float(pricing.get("completion", 1)) == 0
    except (TypeError, ValueError):
        zero = False
    return zero or str(model.get("id", "")).endswith(":free")


def _describe(item: dict, provider: str) -> dict:
    """What the panel shows about a model; tools is None when the provider does not say."""
    architecture = item.get("architecture") or {}
    parameters = item.get("supported_parameters")
    capabilities = item.get("capabilities")
    tools = ("tools" in parameters if isinstance(parameters, list)
             else "tool-calling" in capabilities if isinstance(capabilities, list) else None)
    limits = item.get("limits") if isinstance(item.get("limits"), dict) else {}
    context = item.get("context_length") or item.get("context_window") or limits.get("max_input_tokens")
    return {"id": str(item.get("id") or item.get("name") or "").removeprefix("models/"),
            "free": _is_free(item) if provider == "openrouter" else True,
            "context": context if isinstance(context, int) else None, "tools": tools,
            "input": architecture.get("input_modalities") or item.get("supported_input_modalities") or ["text"],
            "created": item.get("created") if isinstance(item.get("created"), int) else None}


def check_key(provider: str, api_key: str, http=requests) -> None:
    """Raise BrainError if the provider refuses the key (only where the model list cannot tell)."""
    info = PROVIDERS[provider]
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        if info.key_check_url:
            response = http.get(info.key_check_url, headers=headers, timeout=20)
        elif info.key_check_chat:      # NVIDIA, GitHub: their model lists answer any key
            response = http.post(info.base_url.rstrip("/") + "/chat/completions", headers=headers, timeout=60,
                                 json={"model": info.suggested_model, "max_tokens": 1,
                                       "messages": [{"role": "user", "content": "hi"}]})
        else:
            return
    except OSError as error:
        raise BrainError(f"cannot reach {info.name}: {error}") from error
    refused = response.status_code >= 400 if info.key_check_url else response.status_code in (401, 403)
    if refused:     # for the chat check, other errors (a retired model, a busy server) say nothing about the key
        raise BrainError(f"{info.name} answered HTTP {response.status_code}", status=response.status_code)


def list_models(provider: str, api_key: str = "", base_url: str = "", http=requests) -> list[dict]:
    """The chat models a provider offers, free ones and the biggest context first:
    [{"id", "free", "context", "tools", "input", "created"}].

    Only OpenRouter mixes free and paid models; the other providers are used on their free tier.
    Models that make music, images or speech are left out: they are specialists, not brains.
    """
    info = PROVIDERS[provider]
    url = info.models_url or (base_url or info.base_url).rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        response = http.get(url, headers=headers, timeout=20)
    except OSError as error:            # requests' network errors are OSErrors too
        raise BrainError(f"cannot reach {url}: {error}") from error
    if response.status_code >= 400:
        raise BrainError(f"{info.name or provider} answered HTTP {response.status_code}: {response.text[:200]}",
                         status=response.status_code)
    try:
        data = response.json()
    except ValueError:
        raise BrainError(f"{info.name or provider} sent a model list PocketAgent cannot read") from None
    items = data.get("data", []) if isinstance(data, dict) else data   # the GitHub catalog is a plain list
    models = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        outputs = (item.get("architecture") or {}).get("output_modalities") or ["text"]
        model = _describe(item, provider)
        if model["id"] and outputs == ["text"] and not _NOT_CHAT.search(model["id"]):
            models.append(model)
    return sorted(models, key=lambda m: (not m["free"], -(m["context"] or 0), m["id"].lower()))
