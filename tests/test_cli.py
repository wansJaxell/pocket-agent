import threading
from datetime import datetime

from pocketagent import config as cfg
from pocketagent.cli import Runtime, main, start_reminder_loop


def test_due_reminders_are_delivered(make_runtime):
    runtime, _ = make_runtime()
    runtime.reminders.add(datetime(2020, 1, 1), "drink water", chat_id="111")
    delivered, done, stop = [], threading.Event(), threading.Event()

    def notify(chat_id, text):
        delivered.append((chat_id, text))
        done.set()
    start_reminder_loop(runtime, notify, stop)
    assert done.wait(5)
    stop.set()
    assert delivered == [("111", "⏰ Reminder: drink water")]


def test_skills_command_works_before_setup(capsys):
    main(["skills"])
    output = capsys.readouterr().out
    assert "[basics]" in output and "calculate" in output


def test_user_skills_are_loaded_at_start(home):
    skills = home / "skills"
    skills.mkdir(parents=True)
    (skills / "greet.py").write_text(
        "from pocketagent.tools import tool\n\n@tool\ndef greet(name: str) -> str:\n"
        "    '''Greet someone.'''\n    return f'Hello {name}'\n", encoding="utf-8")
    runtime = Runtime(cfg.Config())
    assert runtime.registry.tools["greet"].skill == "user:greet"


def test_terminal_commands_ask_for_the_panel_password_in_locked_mode(monkeypatch, capsys):
    from pocketagent import vault
    from pocketagent.cli import unlock_in_terminal
    monkeypatch.setattr(vault, "default_kdf", lambda: {"name": "scrypt", "n": 2 ** 10, "r": 8, "p": 1})
    config = cfg.Config()
    config.keys = {"groq": "gsk_secret"}
    cfg.lock_with(config, "a long password")
    cfg.save(config)
    locked = cfg.load()
    answers = iter(["wrong", "a long password"])
    assert unlock_in_terminal(locked, ask=lambda prompt: next(answers))
    assert locked.keys == {"groq": "gsk_secret"}
    assert "Wrong password" in capsys.readouterr().out
    assert unlock_in_terminal(cfg.Config()) is True          # open mode: nothing to ask
