"""Specialists: the agent writes the prompt, another (free) model makes the image, the voice or the text.

One agent stays in charge (no multi-agent loops): a specialist is a single call, prompt in,
result out, and the result is a file in the workspace that the panel shows and Telegram sends.

    image   Pollinations (free: no key needed; a free key unlocks more models)
            OpenRouter image models (paid: every image asks for approval, like any spending)
            your own OpenAI-compatible server (/v1/images/generations)
    speech  Pollinations (free key needed), Piper (natural voices, Turkish too, on this computer, offline),
            Windows/macOS voices (offline), your own server (/v1/audio/speech)
    hearing Groq Whisper (free key) or your own server: voice messages become text
    vision  a model that can see pictures (photos sent on Telegram, screenshots)
    writer  any of your brains, e.g. a coding model for long code or documents

Prompts sent to these services leave the computer. Images and the writer are off until the user picks
a service. Hearing, seeing and speech work by themselves when possible, with what is already there:
Groq Whisper when a Groq key is saved, the first brain that can see pictures, Piper or the computer's
own voices. A choice made in the panel always wins.
"""

import base64
import io
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import requests

from pocketagent.config import BrainConfig, Config, home_dir
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
    "piper": Service("Piper: natural voices on this computer (free, offline, Turkish too)"),
    "local": Service("This computer's voices (free, offline)"),
    "custom": Service("Your OpenAI-compatible server", key="custom"),
}
HEARING = {
    "groq": Service("Groq Whisper (free key)", key="groq", key_url="https://console.groq.com/keys"),
    "custom": Service("Your OpenAI-compatible server", key="custom"),
}
# Piper: one program (about 22 MB) and one model file per voice (about 60 MB), from Piper's own releases
PIPER_ZIP = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip"
PIPER_VOICES = ["en_US-amy-medium", "en_US-lessac-medium", "en_GB-alan-medium", "tr_TR-dfki-medium",
                "de_DE-thorsten-medium", "fr_FR-siwis-medium", "es_ES-davefx-medium", "es_MX-ald-medium",
                "it_IT-paola-medium", "pt_BR-faber-medium", "ru_RU-irina-medium", "uk_UA-ukrainian_tts-medium",
                "pl_PL-gosia-medium", "nl_NL-mls-medium", "ar_JO-kareem-medium", "zh_CN-huayan-medium",
                "hi_IN-priyamvada-medium", "fa_IR-amir-medium", "sv_SE-nst-medium", "cs_CZ-jirka-medium",
                "el_GR-rapunzelina-medium", "ro_RO-mihai-medium", "hu_HU-anna-medium", "vi_VN-vais1000-medium",
                "id_ID-news_tts-medium"]
VOICE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/{path}"
DEFAULT_PIPER_VOICE = "en_US-amy-medium"
CULTURES = {"tr": "tr-TR", "en": "en-US", "de": "de-DE", "fr": "fr-FR", "es": "es-ES", "it": "it-IT", "pt": "pt-BR",
            "ru": "ru-RU", "uk": "uk-UA", "pl": "pl-PL", "nl": "nl-NL", "ar": "ar-SA", "zh": "zh-CN", "hi": "hi-IN",
            "fa": "fa-IR", "sv": "sv-SE", "cs": "cs-CZ", "el": "el-GR", "ro": "ro-RO", "hu": "hu-HU", "vi": "vi-VN",
            "id": "id-ID"}


def voice_path(voice: str) -> str:
    """Where a Piper voice lives in its repository, e.g. tr/tr_TR/dfki/medium/tr_TR-dfki-medium."""
    locale, quality = voice.split("-")[0], voice.rsplit("-", 1)[1]
    name = voice[len(locale) + 1:-(len(quality) + 1)]
    return f"{locale.split('_')[0]}/{locale}/{name}/{quality}/{voice}"


_STOPWORDS = {
    "tr": "ve bir bu için ile da de değil çok ama gibi olarak olan var yok ne mi sen ben biz",
    "en": "the and is are to of in that it for with you this not be on have will i a an my your we at from by "
          "can do what here or if so but they was has would there about me all ll",
    "de": "und der die das ist nicht ein eine zu mit ich sie es den von auf für wird",
    "fr": "le la les et est des une un du en que pas pour il fait vous ne au",
    "es": "el la los las y es en que de por un una para con no se del será hará",
    "it": "il la e di che è un una per non sono con del della gli",
    "pt": "o a os as e é de que em um uma para com não do da",
    "nl": "de het een en is van in dat niet op te zijn met voor",
    "pl": "i w nie się na jest że to z do jak co",
    "sv": "och är att det en som på inte med för av",
    "cs": "a je se na že to v s z do jsem ne",
    "ro": "și este de la în nu cu o un care pe",
    "hu": "és a az hogy nem is egy van meg de",
    "id": "dan yang di ini itu dengan untuk tidak ada akan",
    "vi": "và là của có không một những được cho",
}
_STOPSETS = {language: set(words.split()) for language, words in _STOPWORDS.items()}
_MARKS = {"tr": "ğışİı", "de": "ß", "es": "ñ¿¡", "pt": "ãõ", "pl": "łąęśźżń", "ro": "ășț", "hu": "őű", "cs": "řěů",
          "sv": "å", "vi": "ạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹđ"}


def guess_language(text: str, default: str = "en") -> str:
    """The language of a text, as a two-letter code (good enough to pick a voice); `default` if it cannot tell."""
    if re.search(r"[\u0600-\u06FF]", text):
        return "fa" if re.search(r"[پچژگ]", text) else "ar"
    if re.search(r"[\u0400-\u04FF]", text):
        return "uk" if re.search(r"[іїєґІЇЄҐ]", text) else "ru"
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    if re.search(r"[\u0900-\u097F]", text):
        return "hi"
    if re.search(r"[\u0370-\u03FF]", text):
        return "el"
    words = re.findall(r"[^\W\d_]+", text.lower())
    scores = {language: sum(word in stops for word in words) for language, stops in _STOPSETS.items()}
    for language, marks in _MARKS.items():
        if any(mark in text for mark in marks):
            scores[language] += 3
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else default


# Whisper names the language it heard ("english", or "English" on Groq); some servers give the code
WHISPER_LANGUAGES = {"english": "en", "turkish": "tr", "german": "de", "french": "fr", "spanish": "es", "italian": "it",
                     "portuguese": "pt", "russian": "ru", "ukrainian": "uk", "polish": "pl", "dutch": "nl", "arabic": "ar",
                     "chinese": "zh", "hindi": "hi", "persian": "fa", "swedish": "sv", "czech": "cs", "greek": "el",
                     "romanian": "ro", "hungarian": "hu", "vietnamese": "vi", "indonesian": "id", "korean": "ko",
                     "japanese": "ja"}


def heard_language(name: str) -> str:
    name = (name or "").strip().lower()
    return name if len(name) == 2 else WHISPER_LANGUAGES.get(name, name)


_SEES = re.compile(r"gemini|gemma-?[34]|vision|[-_.]vl\b|[-_]vl[-_:]|llama-4|llava|pixtral|gpt-4o|gpt-4\.1|gpt-5|"
                   r"qwen.*vl|omni|kimi-k2\.5|glm-4\.\dv|claude|grok-4", re.IGNORECASE)


def sees_images(brain: BrainConfig) -> bool:
    """Whether a brain takes pictures: the provider's list said so, or the model is known to."""
    return brain.sees_images or brain.provider == "gemini" or bool(_SEES.search(brain.model))
VOICE_NOTES = {".mp3", ".ogg", ".oga", ".m4a"}      # what Telegram shows as a voice bubble
CLASSIC_IMAGE = "https://image.pollinations.ai/prompt/"      # works without a key (rate-limited)
GATEWAY = "https://gen.pollinations.ai"                      # needs a free key for images
EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif",
              "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav",
              "audio/ogg": ".ogg", "audio/aac": ".aac", "audio/flac": ".flac"}
MAX_GET_TEXT = 900           # longer speech needs the POST endpoint (with a key)

# Windows' own speech engine; the text and paths come in through environment variables
SAPI = ("Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "if ($env:PA_VOICE) { $s.SelectVoice($env:PA_VOICE) } elseif ($env:PA_CULTURE) { try { "
        "$s.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::NotSet, "
        "[System.Speech.Synthesis.VoiceAge]::NotSet, 0, [Globalization.CultureInfo]::new($env:PA_CULTURE)) "
        "} catch {} }; $s.SetOutputToWaveFile($env:PA_OUT); $s.Speak($env:PA_TEXT); $s.Dispose()")


MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
               ".gif": "image/gif", ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg",
               ".aac": "audio/aac", ".flac": "audio/flac", ".aiff": "audio/aiff"}


def media_kind(path) -> str:
    """"image", "audio" or "file", from the file name."""
    content_type = MEDIA_TYPES.get(os.path.splitext(str(path))[1].lower(), "")
    return content_type.split("/")[0] if content_type else "file"


class MediaError(Exception):
    """The specialist is not set up, or its service refused."""


def piper_dir() -> Path:
    return home_dir() / "piper"


def piper_program() -> Path:
    return piper_dir() / "piper" / ("piper.exe" if os.name == "nt" else "piper")


def speakable(text: str, limit: int = 1200) -> str:
    """An answer as it should be read aloud: no Markdown, code or links."""
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"^\s*[-•]\s+", " ", text, flags=re.MULTILINE)
    text = re.sub(r"[*_`~]", "", text)                  # emphasis marks go away without a gap
    text = " ".join(re.sub(r"[#>|]", " ", text).split())
    if len(text) > limit:
        cut = max(text.rfind(mark, 0, limit) for mark in ".!?")
        text = text[:cut + 1] if cut > limit // 2 else text[:limit]
    return text


def to_voice_note(data: bytes, extension: str, run=subprocess.run) -> tuple[bytes, str]:
    """Telegram shows MP3/OGG/M4A as a voice bubble; a WAV becomes OGG when ffmpeg is installed."""
    ffmpeg = shutil.which("ffmpeg")
    if extension in VOICE_NOTES or not ffmpeg:
        return data, extension
    folder = tempfile.mkdtemp()
    source, target = os.path.join(folder, "in" + extension), os.path.join(folder, "out.ogg")
    try:
        with open(source, "wb") as f:
            f.write(data)
        result = run([ffmpeg, "-y", "-loglevel", "error", "-i", source, "-c:a", "libopus", "-b:a", "32k", target],
                     capture_output=True, timeout=120)
        if result.returncode == 0 and os.path.exists(target):
            with open(target, "rb") as f:
                return f.read(), ".ogg"
    except (OSError, subprocess.SubprocessError):
        pass
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return data, extension


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
        return self.choice(kind)

    def choice(self, kind: str) -> dict:
        """The specialist used for a kind: the user's choice, or an automatic one from what is connected."""
        chosen = self.config.media.get(kind) or {}
        return chosen if chosen.get("provider") else self.automatic(kind)

    def automatic(self, kind: str) -> dict:
        keys, off = self.config.keys, set(self.config.disabled_providers)
        if kind == "hearing":
            return {"provider": "groq", "model": "", "auto": True} if keys.get("groq") and "groq" not in off else {}
        if kind == "vision":
            for brain in self.config.chain():
                info = PROVIDERS.get(brain.provider)
                usable = (info and not info.retired and brain.enabled and brain.provider not in off
                          and (brain.api_key or not info.needs_key or brain.provider == "custom"))
                if usable and sees_images(brain):
                    return {"provider": brain.provider, "model": brain.model, "auto": True}
            return {}
        if kind == "speech":
            if self.piper_status()["installed"]:
                return {"provider": "piper", "model": "", "voice": "auto", "auto": True}
            if os.name == "nt" or os.path.exists("/usr/bin/say"):
                return {"provider": "local", "model": "", "voice": "", "auto": True}
        return {}

    def ready(self, kind: str) -> bool:
        return bool(self.choice(kind).get("provider"))

    def paid(self, kind: str) -> bool:
        service = {"image": IMAGE, "speech": SPEECH}.get(kind, {}).get(self.choice(kind).get("provider", ""))
        return bool(service and service.paid)

    def describe(self, kind: str, choice: dict | None = None) -> str:
        s = self.choice(kind) if choice is None else choice
        if not s.get("provider"):
            return ""
        return s["provider"] + (f" · {s['model']}" if s.get("model") else "")

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
        if provider == "piper":
            return self._piper(text, voice)
        if provider == "custom":
            reply = self._check(self.http.post(
                self.config.custom_url.rstrip("/") + "/audio/speech", timeout=180,
                headers={"Authorization": f"Bearer {self._key('custom')}"} if self._key("custom") else {},
                json={"model": model, "input": text, "voice": voice or "alloy"}), "Your server")
            return reply.content, EXTENSIONS.get(reply.headers.get("Content-Type", "").split(";")[0], ".mp3")
        raise MediaError("no speech specialist is set up")

    def _piper_voice(self, text: str, voice: str) -> str:
        """The voice to read a text with: the chosen one, or (auto) an installed voice in the text's language."""
        if voice and voice != "auto":
            return voice
        installed = set(self.piper_status()["voices"])
        ordered = [v for v in PIPER_VOICES if v in installed] + sorted(installed - set(PIPER_VOICES))
        language = guess_language(text)
        for candidate in ordered:
            if candidate.split("_")[0] == language:
                return candidate
        preferred = "tr_TR-dfki-medium" if self.config.language == "tr" else DEFAULT_PIPER_VOICE
        return preferred if preferred in installed or not ordered else ordered[0]

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
                env = {**os.environ, "PA_TEXT": text[:20000], "PA_OUT": path, "PA_VOICE": voice,
                       "PA_CULTURE": "" if voice else CULTURES.get(guess_language(text), "en-US")}
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

    # ---------- Piper ----------
    def _piper(self, text: str, voice: str) -> tuple[bytes, str]:
        program = piper_program()
        model = piper_dir() / "voices" / f"{self._piper_voice(text, voice)}.onnx"
        if not program.exists() or not model.exists():
            raise MediaError("Piper is not installed yet: install it in the panel (Specialists, Speech)")
        handle, out = tempfile.mkstemp(suffix=".wav")
        os.close(handle)
        try:
            result = self.run([str(program), "--model", str(model), "--output_file", out],
                              input=text[:20000].encode("utf-8"), capture_output=True, timeout=300,
                              cwd=str(program.parent), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode != 0:
                raise MediaError(f"Piper failed: {(result.stderr or b'').decode('utf-8', 'replace').strip()[:200]}")
            with open(out, "rb") as f:
                return f.read(), ".wav"
        finally:
            try:
                os.remove(out)
            except OSError:
                pass

    def piper_status(self) -> dict:
        voices = piper_dir() / "voices"
        installed = sorted(p.name[:-5] for p in voices.glob("*.onnx")) if voices.is_dir() else []
        return {"installed": piper_program().exists() and bool(installed), "voices": installed,
                "supported": os.name == "nt"}

    def _download(self, url: str, progress=None) -> bytes:
        try:
            reply = self.http.get(url, timeout=600, stream=True)
        except OSError as error:
            raise MediaError(f"cannot download {url}: {error}") from None
        self._check(reply, "The download")
        if not hasattr(reply, "iter_content"):
            return reply.content
        total, chunks, done = int(reply.headers.get("Content-Length") or 0), [], 0
        for chunk in reply.iter_content(chunk_size=1 << 20):
            chunks.append(chunk)
            done += len(chunk)
            if progress:
                progress(url.rsplit("/", 1)[-1], done, total)
        return b"".join(chunks)

    def install_piper(self, voice: str = DEFAULT_PIPER_VOICE, progress=None) -> dict:
        """Download Piper and a voice into the PocketAgent folder (Windows)."""
        if os.name != "nt":
            raise MediaError("installing Piper from the panel works on Windows for now")
        if voice not in PIPER_VOICES:
            raise MediaError(f"unknown Piper voice '{voice}'")
        folder = piper_dir()
        folder.mkdir(parents=True, exist_ok=True)
        if not piper_program().exists():
            with zipfile.ZipFile(io.BytesIO(self._download(PIPER_ZIP, progress))) as archive:
                root = folder.resolve()
                for member in archive.namelist():        # check every path before writing anything
                    target = (root / member).resolve()
                    if target != root and root not in target.parents:
                        raise MediaError(f"the Piper archive has an unsafe path: {member}")
                archive.extractall(root)
        voices = folder / "voices"
        voices.mkdir(exist_ok=True)
        for suffix in (".onnx.json", ".onnx"):
            target = voices / f"{voice}{suffix}"
            if not target.exists():
                data = self._download(VOICE_URL.format(path=voice_path(voice) + suffix), progress)
                target.with_suffix(target.suffix + ".part").write_bytes(data)
                target.with_suffix(target.suffix + ".part").replace(target)
        return self.piper_status()

    # ---------- hearing and seeing ----------
    def transcribe(self, data: bytes, filename: str, expect=()) -> str:
        """A voice message as text.

        expect: languages the user probably speaks, likeliest first. Whisper sometimes takes accented
        speech for another language (English heard as Korean); then it is asked again, told the language.
        """
        settings = self.settings("hearing")
        provider, model = settings.get("provider", ""), settings.get("model", "")
        if provider == "groq":
            key = self._key("groq")
            if not key:
                raise MediaError("Groq needs its free key for voice messages: save one in the panel (step 1, Groq)")
            url, headers, model, name = (PROVIDERS["groq"].base_url + "/audio/transcriptions",
                                         {"Authorization": f"Bearer {key}"}, model or "whisper-large-v3-turbo", "Groq")
        elif provider == "custom":
            key = self._key("custom")
            url, headers, model, name = (self.config.custom_url.rstrip("/") + "/audio/transcriptions",
                                         {"Authorization": f"Bearer {key}"} if key else {}, model or "whisper-1",
                                         "Your server")
        else:
            raise MediaError("no hearing specialist is set up")
        # Groq says which language it heard; other servers may not offer verbose_json, so they get plain json
        form = {"model": model, "response_format": "verbose_json" if provider == "groq" else "json"}

        def hear(**language) -> dict:
            try:
                reply = self.http.post(url, headers=headers, files={"file": (filename, data)},
                                       data={**form, **language}, timeout=180)
            except OSError as error:
                raise MediaError(f"cannot reach {name}: {error}") from None
            return self._check(reply, name).json()

        heard = hear()
        language = heard_language(heard.get("language", ""))
        if expect and language and language not in expect:
            heard = hear(language=expect[0])
        return (heard.get("text") or "").strip()

    def look(self, image: bytes, mime: str, question: str) -> str:
        """Ask the vision specialist about a picture."""
        settings = self.settings("vision")
        provider, model = settings.get("provider", ""), settings.get("model", "")
        if provider not in PROVIDERS or not model:
            raise MediaError("no vision specialist is set up: choose a model that can see pictures in the panel")
        base_url = self.config.custom_url if provider == "custom" else PROVIDERS[provider].base_url
        brain = Brain(self.config.with_key(BrainConfig(provider, base_url, model)), http=self.http)
        picture = f"data:{mime};base64,{base64.b64encode(image).decode('ascii')}"
        try:
            reply = brain.chat([{"role": "user", "content": [{"type": "text", "text": question},
                                                             {"type": "image_url", "image_url": {"url": picture}}]}])
        except BrainError as error:
            raise MediaError(str(error)) from None
        return strip_thinking(reply.content)

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

