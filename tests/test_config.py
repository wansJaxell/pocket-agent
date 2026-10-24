from pocketagent import config as cfg


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
