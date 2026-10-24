"""Where PocketAgent keeps its settings, memory, workspace and user skills.

Everything lives in one folder:
    Windows:      %APPDATA%\\PocketAgent
    macOS/Linux:  ~/.pocketagent
Set POCKETAGENT_HOME to use another folder (handy for tests or a USB stick).
"""

import json
import os
from dataclasses import asdict, dataclass, field
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
    provider: str = ""          # ollama, lmstudio, nvidia, openrouter, groq, custom
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    native_tools: bool = True   # False: tools are described in the prompt instead


@dataclass
class TelegramConfig:
    token: str = ""
    owner_chat_id: int | None = None   # only this chat may talk to the agent


@dataclass
class Config:
    brain: BrainConfig = field(default_factory=BrainConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    agent_name: str = "PocketAgent"
    max_steps: int = 8              # tool calls allowed per question
    history_messages: int = 20      # how much of the conversation the model sees

    @property
    def brain_ready(self) -> bool:
        return bool(self.brain.base_url and self.brain.model)

    @property
    def telegram_ready(self) -> bool:
        return bool(self.telegram.token and self.telegram.owner_chat_id)


def load(path: Path | None = None) -> Config:
    path = path or config_path()
    if not path.exists():
        return Config()
    data = json.loads(path.read_text(encoding="utf-8"))
    return Config(
        brain=BrainConfig(**data.get("brain", {})),
        telegram=TelegramConfig(**data.get("telegram", {})),
        **{k: v for k, v in data.items() if k not in ("brain", "telegram")},
    )


def save(config: Config, path: Path | None = None) -> Path:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(path, 0o600)   # the file holds API keys: readable by you only (where supported)
    except OSError:
        pass
    return path
