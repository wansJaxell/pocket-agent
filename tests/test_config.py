import json

from pocketagent import config as cfg
from pocketagent.config import BrainConfig


def test_default_config_is_not_ready():
    config = cfg.load()
    assert not config.brain_ready and not config.telegram_ready


def test_save_and_load_roundtrip(home):
    config = cfg.Config()
    config.brain.base_url, config.brain.model = "http://localhost:11434/v1", "qwen3.5:9b"
    config.telegram.token, config.telegram.owner_chat_id = "123:ABC", 111
    path = cfg.save(config)
    assert path == home / "config.json"
    loaded = cfg.load()
    assert loaded == config and loaded.brain_ready and loaded.telegram_ready


def test_old_config_files_still_load_and_keys_move_to_the_key_store(home):
    home.mkdir(parents=True)
    (home / "config.json").write_text(json.dumps({
        "brain": {"provider": "groq", "base_url": "https://api.groq.com/openai/v1", "model": "llama",
                  "api_key": "gsk_old", "native_tools": True},
        "telegram": {"token": "1:A", "owner_chat_id": 5}, "agent_name": "Robo",
        "a_setting_from_a_newer_version": 1}), encoding="utf-8")
    config = cfg.load()
    assert config.keys == {"groq": "gsk_old"} and config.brain.api_key == ""
    assert config.chain()[0].api_key == "gsk_old"
    assert config.agent_name == "Robo" and config.telegram_ready


def test_brain_priority_list_roundtrip():
    config = cfg.Config()
    config.set_brains([BrainConfig("groq", "https://g/v1", "m1"), BrainConfig("openrouter", "https://o/v1", "m2:free")])
    config.keys = {"groq": "k1"}
    cfg.save(config)
    loaded = cfg.load()
    assert [b.model for b in loaded.brains()] == ["m1", "m2:free"]
    assert [b.api_key for b in loaded.chain()] == ["k1", ""]
    loaded.set_brains([])
    assert loaded.brains() == [] and not loaded.brain_ready
