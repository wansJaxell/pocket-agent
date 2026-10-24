"""Specialists: the agent writes the prompt, another (free) model makes the image, the voice or the text.

One agent stays in charge (no multi-agent loops): a specialist is a single call, prompt in,
result out, and the result is a file in the workspace that the panel shows and Telegram sends.

    image   Pollinations (free: no key needed; a free key unlocks more models)
            OpenRouter image models (paid: every image asks for approval, like any spending)
            your own OpenAI-compatible server (/v1/images/generations)
    speech  Pollinations (free key needed), this computer's own voices (offline), your own server (/v1/audio/speech)
    writer  any of your brains, e.g. a coding model for long code or documents

Prompts sent to these services leave the computer, so every specialist is off until the user picks one.
"""

import base64
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from urllib.parse import quote

import requests

from pocketagent.config import BrainConfig, Config
from pocketagent.llm import PROVIDERS, Brain, BrainError, strip_thinking


@dataclass(frozen=True)
class Service:
    label: str
    paid: bool = False
    key: str = ""           # which entry of Config.keys it uses
    key_url: str = ""


IMAGE = {
    "pollinations": Service("Pollinations (free, no key needed)", key="pollinations",
                            key_url="https://enter.pollinations.ai/keys"),
    "openrouter": Service("OpenRouter image models (paid: asks every time)", paid=True, key="openrouter"),
    "custom": Service("Your OpenAI-compatible server", key="custom"),
}
SPEECH = {
    "pollinations": Service("Pollinations (free key needed)", key="pollinations",
                            key_url="https://enter.pollinations.ai/keys"),
    "local": Service("This computer's voices (free, offline)"),
    "custom": Service("Your OpenAI-compatible server", key="custom"),
}
CLASSIC_IMAGE = "https://image.pollinations.ai/prompt/"      # works without a key (rate-limited)
GATEWAY = "https://gen.pollinations.ai"                      # needs a free key for images
EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif",
              "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav",
              "audio/ogg": ".ogg", "audio/aac": ".aac", "audio/flac": ".flac"}
MAX_GET_TEXT = 900           # longer speech needs the POST endpoint (with a key)

# Windows' own speech engine; the text and paths come in through environment variables
SAPI = ("Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "if ($env:PA_VOICE) { $s.SelectVoice($env:PA_VOICE) }; "
        "$s.SetOutputToWaveFile($env:PA_OUT); $s.Speak($env:PA_TEXT); $s.Dispose()")


MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
               ".gif": "image/gif", ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg",
               ".aac": "audio/aac", ".flac": "audio/flac", ".aiff": "audio/aiff"}


def media_kind(path) -> str:
    """"image", "audio" or "file", from the file name."""
    content_type = MEDIA_TYPES.get(os.path.splitext(str(path))[1].lower(), "")
    return content_type.split("/")[0] if content_type else "file"


class MediaError(Exception):
    """The specialist is not set up, or its service refused."""


def _size(size: str) -> tuple[int, int]:
    match = re.match(r"^\s*(\d{2,4})\s*[x×*]\s*(\d{2,4})\s*$", size or "")
    width, height = (int(match.group(1)), int(match.group(2))) if match else (1024, 1024)
    return max(64, min(width, 2048)), max(64, min(height, 2048))


def _data_url(url: str) -> tuple[bytes, str]:
    header, _, payload = url.partition(",")
    content_type = header[5:].split(";")[0] if header.startswith("data:") else "image/png"
    return base64.b64decode(payload), EXTENSIONS.get(content_type, ".png")


class Studio:
    def __init__(self, config: Config, http=requests, run=subprocess.run):
        self.config, self.http, self.run = config, http, run

    # ---------- what is set up ----------
    def settings(self, kind: str) -> dict:
        return self.config.media.get(kind) or {}

    def ready(self, kind: str) -> bool:
        return bool(self.settings(kind).get("provider"))

    def paid(self, kind: str) -> bool:
        service = {"image": IMAGE, "speech": SPEECH}.get(kind, {}).get(self.settings(kind).get("provider", ""))
        return bool(service and service.paid)

    def describe(self, kind: str) -> str:
        s = self.settings(kind)
        return f"{s.get('provider', '?')}" + (f" · {s['model']}" if s.get("model") else "")

    def _key(self, name: str) -> str:
        return self.config.keys.get(name, "")

    def _check(self, reply, what: str):
        if reply.status_code >= 400:
            raise MediaError(f"{what} answered HTTP {reply.status_code}: {str(getattr(reply, 'text', ''))[:200]}")
        return reply

    # ---------- images ----------
    def image(self, prompt: str, size: str = "1024x1024") -> tuple[bytes, str]:
        """Make an image; returns (bytes, file extension)."""
        settings, (width, height) = self.settings("image"), _size(size)
        provider, model = settings.get("provider", ""), settings.get("model", "")
        if provider == "pollinations":
            key = self._key("pollinations")
            params = {"width": width, "height": height, "nologo": "true"}
            if key:
                if model:
                    params["model"] = model
                url, headers = f"{GATEWAY}/image/{quote(prompt, safe='')}", {"Authorization": f"Bearer {key}"}
            else:
                url, headers = CLASSIC_IMAGE + quote(prompt, safe=""), {}
            reply = self._check(self.http.get(url, params=params, headers=headers, timeout=180), "Pollinations")
            content_type = reply.headers.get("Content-Type", "").split(";")[0]
            if not content_type.startswith("image/"):
                raise MediaError(f"Pollinations sent {content_type or 'no image'} instead of an image")
            return reply.content, EXTENSIONS.get(content_type, ".jpg")
        if provider == "openrouter":
            reply = self._check(self.http.post(
                PROVIDERS["openrouter"].base_url + "/chat/completions", timeout=180,
                headers={"Authorization": f"Bearer {self._key('openrouter')}"},
                json={"model": model, "modalities": ["image", "text"],
                      "messages": [{"role": "user", "content": prompt}]}), "OpenRouter")
            images = reply.json()["choices"][0]["message"].get("images") or []
            if not images:
                raise MediaError("the model answered without an image")
            return _data_url(images[0]["image_url"]["url"])
        if provider == "custom":
            reply = self._check(self.http.post(
                self.config.custom_url.rstrip("/") + "/images/generations", timeout=180,
                headers={"Authorization": f"Bearer {self._key('custom')}"} if self._key("custom") else {},
                json={"model": model, "prompt": prompt, "size": f"{width}x{height}", "n": 1,
                      "response_format": "b64_json"}), "Your server")
            item = reply.json()["data"][0]
            if item.get("b64_json"):
                return base64.b64decode(item["b64_json"]), ".png"
            picture = self._check(self.http.get(item["url"], timeout=120), "Your server")
            return picture.content, EXTENSIONS.get(picture.headers.get("Content-Type", ""), ".png")
        raise MediaError("no image specialist is set up")

    # ---------- speech ----------
    def speech(self, text: str, voice: str = "") -> tuple[bytes, str]:
        """Read a text aloud; returns (bytes, file extension)."""
        settings = self.settings("speech")
        provider, model = settings.get("provider", ""), settings.get("model", "")
        voice = voice or settings.get("voice", "")
        if provider == "pollinations":
            key = self._key("pollinations")
            if not key:
                raise MediaError("Pollinations needs its free key for speech: get one at "
                                 "https://enter.pollinations.ai/keys and save it in the panel (Specialists)")
            headers = {"Authorization": f"Bearer {key}"}
            if len(text) > MAX_GET_TEXT:
                reply = self.http.post(f"{GATEWAY}/v1/audio/speech", headers=headers, timeout=180, json={
                    "model": model or "openai/tts-1", "input": text[:4000], "voice": voice or "nova"})
            else:
                params = {"voice": voice or "nova", **({"model": model} if model else {})}
                reply = self.http.get(f"{GATEWAY}/audio/{quote(text[:MAX_GET_TEXT], safe='')}",
                                      params=params, headers=headers, timeout=180)
            self._check(reply, "Pollinations")
            return reply.content, EXTENSIONS.get(reply.headers.get("Content-Type", "").split(";")[0], ".mp3")
        if provider == "local":
            return self._local_speech(text, voice)
        if provider == "custom":
            reply = self._check(self.http.post(
                self.config.custom_url.rstrip("/") + "/audio/speech", timeout=180,
                headers={"Authorization": f"Bearer {self._key('custom')}"} if self._key("custom") else {},
                json={"model": model, "input": text, "voice": voice or "alloy"}), "Your server")
            return reply.content, EXTENSIONS.get(reply.headers.get("Content-Type", "").split(";")[0], ".mp3")
        raise MediaError("no speech specialist is set up")

    def _local_speech(self, text: str, voice: str) -> tuple[bytes, str]:
        if os.name == "nt":
            extension = ".wav"
        elif os.path.exists("/usr/bin/say"):     # macOS
            extension = ".aiff"
        else:
            raise MediaError("this computer has no built-in voice PocketAgent can use: choose Pollinations")
        handle, path = tempfile.mkstemp(suffix=extension)
        os.close(handle)
        try:
            if extension == ".wav":
                env = {**os.environ, "PA_TEXT": text[:20000], "PA_OUT": path, "PA_VOICE": voice}
                result = self.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", SAPI], env=env,
                                  capture_output=True, text=True, timeout=300,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            else:
                result = self.run(["/usr/bin/say", "-o", path, *(["-v", voice] if voice else []), "--", text[:20000]],
                                  capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                raise MediaError(f"the computer's voice failed: {(result.stderr or '').strip()[:200]}")
            with open(path, "rb") as f:
                return f.read(), extension
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    # ---------- the writer ----------
    def write(self, task: str) -> str:
        """Hand a long writing or coding task to the writer specialist (one of the user's brains)."""
        settings = self.settings("writer")
        provider, model = settings.get("provider", ""), settings.get("model", "")
        if provider not in PROVIDERS or not model:
            raise MediaError("no writer specialist is set up")
        base_url = self.config.custom_url if provider == "custom" else PROVIDERS[provider].base_url
        brain = Brain(self.config.with_key(BrainConfig(provider, base_url, model)), http=self.http)
        try:
            reply = brain.chat([
                {"role": "system", "content": "You are a specialist writer and programmer. Do exactly the task. "
                                              "Reply with the finished content only, no remarks around it."},
                {"role": "user", "content": task}])
        except BrainError as error:
            raise MediaError(str(error)) from None
        return strip_thinking(reply.content)

    # ---------- choices for the panel ----------
    def models(self, kind: str, provider: str) -> list[dict]:
        """Models a specialist service offers (empty when it has no list)."""
        try:
            if provider == "pollinations" and kind in ("image", "speech"):
                kind_name = "image" if kind == "image" else "audio"
                items = self.http.get(f"{GATEWAY}/{kind_name}/models", timeout=20).json()
                return [{"id": m["name"], "label": m.get("title") or m["name"], "voices": m.get("voices") or []}
                        for m in items if isinstance(m, dict) and m.get("category") == kind_name
                        and kind_name in (m.get("output_modalities") or []) and not m.get("paid_only")]
            if provider == "openrouter" and kind == "image":
                items = self.http.get(PROVIDERS["openrouter"].base_url + "/models", timeout=20).json()["data"]
                return [{"id": m["id"], "label": m.get("name") or m["id"], "voices": []} for m in items
                        if "image" in (m.get("architecture") or {}).get("output_modalities", [])
                        and float((m.get("pricing") or {}).get("prompt", 0) or 0) >= 0]
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise MediaError(f"could not get the model list: {error}") from None
        return []

