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


def test_terminal_chat_asks_for_approval_in_the_terminal(make_runtime, monkeypatch, capsys):
    from conftest import call, say
    from pocketagent.cli import console_approver
    from pocketagent.skills import shell
    runs = []

    class FakePopen:
        def __init__(self, argv, cwd, **kwargs):
            runs.append(argv)
            self.pid, self.returncode = 1, 0

        def communicate(self, timeout=None):
            return b"ok", None

        def poll(self):
            return 0
    monkeypatch.setattr(shell, "Popen", FakePopen)
    runtime, _ = make_runtime(call("run_command", command="git status"), say("done"),
                              call("run_command", command="git status"), say("done"))
    runtime.config.computer_use = True
    runtime.approvals.notifiers.append(console_approver(runtime.approvals))
    answers = iter(["r"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    runtime.agent.run("terminal", "status?")
    runtime.agent.run("terminal", "status again?")          # the rule saved with "r" covers it
    assert len(runs) == 2
    assert "git status" in capsys.readouterr().out
