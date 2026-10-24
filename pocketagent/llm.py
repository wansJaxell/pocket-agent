"""The "brain": any OpenAI-compatible chat API.

Local and free:   Ollama, LM Studio
Free cloud tiers: NVIDIA build.nvidia.com (Nemotron), OpenRouter, Groq
They all speak the same API, so one small client covers every option.
Only `requests` is used (no heavy SDK), so the agent also installs on Android (Termux).
"""

import json
import re
import time
from dataclasses import dataclass, field

import requests

from pocketagent.config import BrainConfig


@dataclass(frozen=True)
class Provider:
    label: str
    base_url: str
    needs_key: bool
    key_url: str = ""
    suggested_model: str = ""


PROVIDERS: dict[str, Provider] = {
    "ollama": Provider("Ollama (local, free)", "http://localhost:11434/v1", False,
                       suggested_model="qwen3.5:9b"),
    "lmstudio": Provider("LM Studio (local, free)", "http://localhost:1234/v1", False),
    "nvidia": Provider("NVIDIA build.nvidia.com (free tier)", "https://integrate.api.nvidia.com/v1", True,
                       key_url="https://build.nvidia.com", suggested_model="nvidia/nemotron-3-super-120b-a12b"),
    "openrouter": Provider("OpenRouter (has free models)", "https://openrouter.ai/api/v1", True,
                           key_url="https://openrouter.ai/keys"),
    "groq": Provider("Groq (free tier)", "https://api.groq.com/openai/v1", True,
                     key_url="https://console.groq.com/keys"),
    "custom": Provider("Other OpenAI-compatible API", "", True),
}

RETRY_STATUS = {429, 500, 502, 503, 504}   # busy or temporarily broken: worth another try


class BrainError(Exception):
    """The model server could not be reached or refused the request."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Reply:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)


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


class Brain:
    def __init__(self, config: BrainConfig, http=None, retries: int = 2, retry_delay: float = 2.0):
        self.config = config
        self.http = http or requests.Session()
        self.retries, self.retry_delay = retries, retry_delay

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> Reply:
        body = {"model": self.config.model, "messages": messages, "temperature": 0.3}
        if tools and self.config.native_tools:
            body["tools"] = tools
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        url = self.config.base_url.rstrip("/") + "/chat/completions"

        for attempt in range(self.retries + 1):
            last_try = attempt == self.retries
            try:
                response = self.http.post(url, json=body, headers=headers, timeout=180)
            except requests.ConnectionError as error:
                if last_try:
                    raise BrainError(f"cannot connect to {self.config.base_url}. "
                                     "Is the model server (e.g. Ollama) running?") from error
                time.sleep(self.retry_delay * (attempt + 1))
                continue
            if response.status_code in RETRY_STATUS and not last_try:
                time.sleep(self.retry_delay * (attempt + 1))
                continue
            if response.status_code >= 400:
                raise BrainError(f"the model server answered HTTP {response.status_code}: {response.text[:300]}")
            message = response.json()["choices"][0]["message"]
            calls = [ToolCall(id=c.get("id") or f"call_{i}", name=c["function"]["name"],
                              arguments=parse_arguments(c["function"].get("arguments")))
                     for i, c in enumerate(message.get("tool_calls") or [])]
            return Reply(content=message.get("content") or "", tool_calls=calls)
        raise BrainError("no answer from the model server")   # not reached; keeps type checkers happy
