"""Locked access mode: API keys and the Telegram token are stored encrypted with the panel password."""

import json
from pathlib import Path

import pytest
import requests
from conftest import FakeWeb

from pocketagent import autostart, vault
from pocketagent import config as cfg
from pocketagent.app import App, PanelError
from pocketagent.panel import PanelServer

FAST = {"name": "scrypt", "n": 2 ** 10, "r": 8, "p": 1}


@pytest.fixture(autouse=True)
def fast_kdf(monkeypatch):
    monkeypatch.setattr(vault, "default_kdf", lambda: dict(FAST))
    monkeypatch.setattr(App, "WRONG_PASSWORD_DELAY", 0)


def configured():
    config = cfg.Config()
    config.keys = {"groq": "gsk_very_secret_key"}
    config.telegram = cfg.TelegramConfig("123:SECRET_TOKEN", 111, "robi_bot")
    return config


def test_locking_encrypts_keys_and_token_on_disk(home):
    app = App(configured())
    app.set_access("locked", "a long password")
    text = (home / "config.json").read_text(encoding="utf-8")
    assert "gsk_very_secret_key" not in text and "SECRET_TOKEN" not in text
    saved = json.loads(text)
    assert saved["access"] == "locked" and saved["vault"]["kdf"]["name"] == "scrypt"
    assert saved["telegram"]["owner_chat_id"] == 111            # not a secret: only the token is


def test_after_a_restart_nothing_works_until_the_password_is_given(home):
    App(configured()).set_access("locked", "a long password")
    app = App(cfg.load())
    assert app.locked and app.config.keys == {} and not app.config.telegram_ready
    assert app.locked_state() == {"app": "PocketAgent", "version": app.state()["version"], "locked": True,
                                  "language": "", "identity": {"name": "PocketAgent"}}
    with pytest.raises(PanelError, match="password"):
        app.unlock("wrong password")
    app.unlock("a long password")
    assert not app.locked
    assert app.config.keys == {"groq": "gsk_very_secret_key"} and app.config.telegram.token == "123:SECRET_TOKEN"


def test_changes_made_while_unlocked_stay_encrypted(home):
    App(configured()).set_access("locked", "a long password")
    app = App(cfg.load())
    app.unlock("a long password")
    app.config.keys["gemini"] = "AIza_new_secret"
    app.save()
    assert "AIza_new_secret" not in (home / "config.json").read_text(encoding="utf-8")
    again = cfg.load()
    cfg.unlock(again, "a long password")
    assert again.keys == {"groq": "gsk_very_secret_key", "gemini": "AIza_new_secret"}


def test_short_passwords_are_refused():
    with pytest.raises(PanelError, match="8"):
        App(configured()).set_access("locked", "short")


def test_back_to_open_mode_needs_the_panel_unlocked(home):
    app = App(configured())
    app.set_access("locked", "a long password")
    app.set_access("open")
    saved = json.loads((home / "config.json").read_text(encoding="utf-8"))
    assert saved["access"] == "open" and saved["vault"] is None and saved["keys"]["groq"] == "gsk_very_secret_key"


def test_a_forgotten_password_means_entering_the_keys_again(home):
    App(configured()).set_access("locked", "a long password")
    app = App(cfg.load())
    app.forget_vault()
    assert not app.locked and app.config.access == "open"
    assert app.config.keys == {} and not app.config.telegram.token
    assert cfg.load().vault is None


# ---------- the panel in locked mode ----------
@pytest.fixture
def locked_panel(home):
    App(configured()).set_access("locked", "a long password")
    server = PanelServer(App(cfg.load(), http=FakeWeb()), port=0)
    server.start(poll_interval=0.02)
    yield server
    server.stop()


def call(session, panel, method, path, body=None):
    if method == "POST" and body is None:
        body = {}
    return session.request(method, panel.url + path, json=body, timeout=5,
                           headers={"X-Pocket-Token": panel.token})


def test_locked_panel_shows_only_the_unlock_screen(locked_panel):
    browser = requests.Session()
    browser.trust_env = False
    assert call(browser, locked_panel, "GET", "api/state").json()["locked"] is True
    assert call(browser, locked_panel, "POST", "api/identity", {"name": "x"}).status_code == 401
    assert call(browser, locked_panel, "POST", "api/unlock", {"password": "nope"}).status_code == 400
    reply = call(browser, locked_panel, "POST", "api/unlock", {"password": "a long password"})
    cookie = reply.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    state = call(browser, locked_panel, "GET", "api/state").json()
    assert "locked" not in state and state["access"] == "locked"
    assert "gsk_very_secret_key" not in json.dumps(state)

    other_browser = requests.Session()           # the app is unlocked, but this browser has not proved the password
    other_browser.trust_env = False
    assert call(other_browser, locked_panel, "GET", "api/state").json()["locked"] is True

    call(browser, locked_panel, "POST", "api/lock")       # the "lock panel" button
    assert call(browser, locked_panel, "GET", "api/state").json()["locked"] is True


# ---------- start with Windows ----------
def test_autostart_puts_a_visible_shortcut_in_the_startup_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(autostart, "supported", lambda: True)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    ran = []

    def fake_powershell(command, env, **kwargs):
        ran.append((command, env))
        autostart.shortcut_path().write_bytes(b"lnk")
        return type("Done", (), {"returncode": 0, "stderr": ""})()

    link = autostart.enable(run=fake_powershell)
    assert link == tmp_path / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "PocketAgent.lnk"
    command, env = ran[0]
    assert command[0] == "powershell" and "WScript.Shell" in command[-1]
    assert env["PA_LINK"] == str(link) and "--autostart" in env["PA_ARGS"]
    assert env["PA_STYLE"] == "7"                               # minimized, but a normal visible window
    assert env["PA_DIR"] == str(autostart.PROJECT)              # from source: start where the package is
    assert autostart.is_enabled()
    autostart.disable()
    assert not link.exists() and not autostart.is_enabled()


def test_autostart_is_windows_only(monkeypatch):
    monkeypatch.setattr(autostart, "supported", lambda: False)
    with pytest.raises(autostart.AutostartError):
        autostart.enable()
    app = App(cfg.Config())
    assert app.state()["autostart"] == {"supported": False, "enabled": False}


def test_a_desktop_icon_starts_this_copy_of_the_program(monkeypatch, tmp_path):
    monkeypatch.setattr(autostart, "supported", lambda: True)
    made = []

    def fake_powershell(command, env, **kwargs):
        if "GetFolderPath" in command[-1]:
            return type("Done", (), {"returncode": 0, "stdout": str(tmp_path / "Masaüstü") + "\n", "stderr": ""})()
        made.append(env)
        Path(env["PA_LINK"]).write_bytes(b"lnk")
        return type("Done", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    link = autostart.desktop_shortcut(run=fake_powershell)
    assert link == tmp_path / "Masaüstü" / "PocketAgent.lnk" and link.exists()
    assert made[0]["PA_STYLE"] == "1" and "--autostart" not in made[0]["PA_ARGS"]
    assert made[0]["PA_DIR"] == str(autostart.PROJECT)
