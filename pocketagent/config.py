"""Where PocketAgent keeps its settings, memory, workspace and user skills.

Everything lives in one folder:
    Windows:      %APPDATA%\\PocketAgent
    macOS/Linux:  ~/.pocketagent
Set POCKETAGENT_HOME to use another folder (handy for tests or a USB stick).
"""

import json
import os
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path


def home_dir() -> Path:
    custom = os.getenv("POCKETAGENT_HOME")
    if custom:
        return Path(custom)
    if os.name == "nt":
        return Path(os.getenv("APPDATA", str(Path.home()))) / "PocketAgent"
    return Path.home() / ".pocketagent"


def config_path() -> Path:
    return home_dir() / "config.json"


def workspace_dir() -> Path:
    """The only folder the file skills may read and write."""
    return home_dir() / "workspace"


def memory_dir() -> Path:
    return home_dir() / "memory"


def user_skills_dir() -> Path:
    """Drop your own skill files (*.py) here; they are loaded at start-up."""
    return home_dir() / "skills"


@dataclass
class BrainConfig:
    provider: str = ""          # a key of llm.PROVIDERS: groq, openrouter, gemini, ollama, custom, ...
    base_url: str = ""
    model: str = ""
    api_key: str = ""           # old config files only: keys now live in Config.keys, one per provider
    native_tools: bool = True   # False: tools are described in the prompt instead
    free: bool = True           # only free brains are used as automatic fallbacks


@dataclass
class TelegramConfig:
    token: str = ""
    owner_chat_id: int | None = None   # only this chat may talk to the agent
    username: str = ""                 # the bot's @name, shown in the panel


@dataclass
class Config:
    brain: BrainConfig = field(default_factory=BrainConfig)            # first choice
    fallbacks: list[BrainConfig] = field(default_factory=list)         # next choices, in the user's order
    keys: dict[str, str] = field(default_factory=dict)                 # provider -> API key
    custom_url: str = ""                                               # address of the "custom" provider
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    agent_name: str = "PocketAgent"
    max_steps: int = 8              # tool calls allowed per question
    history_messages: int = 20      # how much of the conversation the model sees
    language: str = ""              # "en" or "tr"; empty: follow the browser
    panel_port: int = 8765

    @property
    def brain_ready(self) -> bool:
        return bool(self.brain.base_url and self.brain.model)

    @property
    def telegram_ready(self) -> bool:
        return bool(self.telegram.token and self.telegram.owner_chat_id)

    def brains(self) -> list[BrainConfig]:
        """The brains in priority order."""
        return [b for b in (self.brain, *self.fallbacks) if b.model]

    def set_brains(self, brains: list[BrainConfig]) -> None:
        self.brain = brains[0] if brains else BrainConfig()
        self.fallbacks = list(brains[1:])

    def with_key(self, brain: BrainConfig) -> BrainConfig:
        return replace(brain, api_key=self.keys.get(brain.provider) or brain.api_key)

    def chain(self) -> list[BrainConfig]:
        """The brains in priority order, each with its provider's key filled in."""
        return [self.with_key(b) for b in self.brains()]


def _build(cls, data):
    """Make a dataclass from saved JSON, ignoring settings this version does not know."""
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in (data or {}).items() if k in names})


def load(path: Path | None = None) -> Config:
    path = path or config_path()
    if not path.exists():
        return Config()
    data = json.loads(path.read_text(encoding="utf-8"))
    config = _build(Config, {k: v for k, v in data.items() if k not in ("brain", "fallbacks", "telegram")})
    config.brain = _build(BrainConfig, data.get("brain"))
    config.fallbacks = [_build(BrainConfig, b) for b in data.get("fallbacks", [])]
    config.telegram = _build(TelegramConfig, data.get("telegram"))
    for brain in (config.brain, *config.fallbacks):      # version 0.1 kept the key inside the brain
        if brain.api_key:
            config.keys.setdefault(brain.provider, brain.api_key)
            brain.api_key = ""
    return config


def save(config: Config, path: Path | None = None) -> Path:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)   # the file holds API keys: readable by you only (where supported)
    except OSError:
        pass
    tmp.replace(path)          # write-then-rename: a crash never leaves a half-written config
    return path
