import json
import threading

import pytest

from pocketagent.approvals import (ALWAYS_ASK, Action, ApprovalEngine, AuditLog, Refused, RuleStore, Stopped,
                                   classify_command)


class Switch:
    def __init__(self, on=True):
        self.on = on

    def __call__(self):
        return self.on


def make_engine(tmp_path, answer=None, on=True, timeout=5):
    """An engine whose 'user' answers every request with answer(pending) -> (approve, remember)."""
    engine = ApprovalEngine(RuleStore(tmp_path), AuditLog(tmp_path), Switch(on), timeout=timeout)
    asked = []

    def user(pending):
        asked.append(pending)
        if answer:
            approve, remember = answer(pending)
            engine.answer(pending.id, approve, remember, by="test")
    engine.notifiers.append(user)
    return engine, asked


def shell(command, folder="C:/work"):
    return Action("shell", f"Run: {command}", {"command": command, "folder": folder},
                  scope={"command": command, "folder": folder}, classes=classify_command(command))


def test_an_approval_opens_a_narrow_rule_not_a_category(tmp_path):
    engine, asked = make_engine(tmp_path, answer=lambda p: (True, True))
    assert engine.request(shell("git status")) == "approved"
    assert engine.request(shell("git status")).startswith("rule #1")       # same command, same folder
    assert len(asked) == 1
    engine.request(shell("git status", folder="C:/other"))                   # new folder: asks again
    engine.request(shell("git log"))                                         # new command: asks again
    assert len(asked) == 3
    assert [r["scope"] for r in engine.rules.all()][0] == {"command": "git status", "folder": "C:/work"}


def test_approve_once_saves_no_rule(tmp_path):
    engine, asked = make_engine(tmp_path, answer=lambda p: (True, False))
    engine.request(shell("dir"))
    engine.request(shell("dir"))
    assert len(asked) == 2 and engine.rules.all() == []


@pytest.mark.parametrize("command, kind", [
    ("del C:\\Users\\me\\report.docx", "delete"), ("Remove-Item -Recurse old", "delete"), ("rm -rf build", "delete"),
    ("git clean -fdx", "delete"), ("cmdkey /list", "secrets"), ("type C:\\Users\\me\\.ssh\\id_rsa", "secrets"),
    ("Send-MailMessage -To boss@example.com -Subject hi", "message"),
    ("curl -X POST https://api.stripe.com/v1/charges", "money")])
def test_dangerous_commands_are_classified(command, kind):
    assert kind in classify_command(command)


def test_harmless_commands_have_no_class():
    assert classify_command("git status") == set() and classify_command("Get-ChildItem C:\\work") == set()
    assert classify_command("pwd") == set()


def test_always_ask_classes_ask_every_time_and_never_become_rules(tmp_path):
    engine, asked = make_engine(tmp_path, answer=lambda p: (True, True))   # the user even ticks "remember"
    for _ in range(2):
        engine.request(shell("rm old.txt"))
    assert len(asked) == 2 and engine.rules.all() == []
    assert asked[0].can_remember is False and "delete" in asked[0].classes
    pay = Action("payment", "Pay 10 TL", {"amount": "10 TL", "to": "shop"}, scope={"to": "shop"}, classes={"money"})
    engine.request(pay)
    assert len(asked) == 3 and ALWAYS_ASK >= {"money", "delete", "message", "secrets", "untrusted"}


def test_actions_after_reading_web_or_file_content_always_ask(tmp_path):
    engine, asked = make_engine(tmp_path, answer=lambda p: (True, True))
    engine.request(shell("git pull"))                          # creates a rule
    engine.request(shell("git pull"), tainted=["fetch_webpage(https://evil.example)"])
    assert len(asked) == 2
    assert asked[1].can_remember is False and asked[1].tainted == ["fetch_webpage(https://evil.example)"]
    assert "untrusted" in asked[1].classes


def test_safe_mode_refuses_without_asking(tmp_path):
    engine, asked = make_engine(tmp_path, answer=lambda p: (True, True), on=False)
    with pytest.raises(Refused, match="safe mode"):
        engine.request(shell("dir"))
    assert asked == []


def test_denied_and_unanswered_requests_are_refused(tmp_path):
    engine, _ = make_engine(tmp_path, answer=lambda p: (False, False))
    with pytest.raises(Refused, match="said no"):
        engine.request(shell("dir"))
    silent, _ = make_engine(tmp_path, timeout=0.05)
    with pytest.raises(Refused, match="no answer"):
        silent.request(shell("dir"))


def test_there_is_no_ceiling_on_approved_actions(tmp_path):
    engine, asked = make_engine(tmp_path, answer=lambda p: (True, True))
    for _ in range(200):
        engine.request(shell("git status"))
    assert len(asked) == 1


class FakeProcess:
    def __init__(self):
        self.pid, self.killed = 4242, False

    def poll(self):
        return 0 if self.killed else None

    def kill(self):
        self.killed = True


def test_stop_denies_waiting_requests_kills_processes_and_blocks_the_old_turn(tmp_path, monkeypatch):
    import pocketagent.approvals as approvals
    monkeypatch.setattr(approvals, "kill_tree", lambda proc: proc.kill())
    engine, asked = make_engine(tmp_path)                  # nobody answers: the request waits
    process = FakeProcess()
    engine.track(process)
    generation, outcome = engine.generation, []

    def turn():
        try:
            engine.request(shell("dir"), generation=generation)
        except Exception as error:
            outcome.append(type(error))
    worker = threading.Thread(target=turn)
    worker.start()
    while not engine.pending:
        pass
    summary = engine.stop_everything(by="panel")
    worker.join(5)
    assert outcome == [Stopped] and process.killed
    assert summary == {"approvals": 1, "processes": 1}
    with pytest.raises(Stopped):
        engine.check(generation)              # the interrupted turn cannot go on
    engine.check(engine.generation)           # new turns can


def test_rules_can_be_listed_and_deleted_one_by_one(tmp_path):
    engine, asked = make_engine(tmp_path, answer=lambda p: (True, True))
    engine.request(shell("git status"))
    engine.request(shell("git log"))
    first, second = engine.rules.all()
    assert engine.rules.remove(first["id"]) and not engine.rules.remove(999)
    assert engine.rules.all() == [second]
    engine.request(shell("git status"))      # its rule is gone: asks again
    assert len(asked) == 3


def test_every_decision_goes_to_the_audit_log(tmp_path):
    engine, _ = make_engine(tmp_path, answer=lambda p: (True, True))
    engine.request(shell("git status"))
    engine.request(shell("git status"))
    engine.enabled.on = False
    with pytest.raises(Refused):
        engine.request(shell("git status"))
    decisions = [e["decision"] for e in engine.audit.recent() if e["event"] == "approval"]
    assert decisions == ["approved", "rule", "blocked"]
    assert (tmp_path / "audit.jsonl").exists()


def test_the_audit_log_is_read_from_its_end(tmp_path):
    """The panel asks for the last entries every two seconds; the log itself grows for ever."""
    log = AuditLog(tmp_path)
    with open(log.path, "w", encoding="utf-8") as f:
        for number in range(100_000):
            f.write(json.dumps({"event": "tool", "n": number, "text": "ğüşiöç"}) + "\n")
        f.write('{"event": "half writ')                  # a crash in the middle of a line
    entries = log.recent(40)
    assert [e["n"] for e in entries] == list(range(99_961, 100_000))
    assert AuditLog(tmp_path / "none").recent() == []
