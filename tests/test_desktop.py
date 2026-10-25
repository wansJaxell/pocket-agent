"""Screenshot, clipboard and opening programs: computer use, each with the user's approval. The OS is faked."""

from types import SimpleNamespace

import pytest

from pocketagent.approvals import ApprovalEngine, AuditLog, RuleStore
from pocketagent.skills import desktop
from pocketagent.tools import ToolContext, ToolRegistry


@pytest.fixture
def ran(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        env = kwargs.get("env") or {}
        if env.get("PA_OUT"):
            with open(env["PA_OUT"], "wb") as f:
                f.write(b"\x89PNG-screen")
        return SimpleNamespace(returncode=0, stdout="kopyalanan metin\r\n", stderr="")
    monkeypatch.setattr(desktop, "run", fake_run)
    monkeypatch.setattr(desktop, "WINDOWS", True)
    return calls


def computer(tmp_path, answer=(True, False)):
    engine = ApprovalEngine(RuleStore(tmp_path), AuditLog(tmp_path), lambda: True, timeout=5)
    asked = []
    engine.notifiers.append(lambda p: asked.append(p) or engine.answer(p.id, *answer))
    ctx = ToolContext(workspace=tmp_path / "ws", approvals=engine, computer_use=True, generation=engine.generation)
    return ctx, asked


def tools():
    registry = ToolRegistry()
    registry.load_builtin()
    return registry


def test_a_screenshot_is_taken_after_approval_and_kept_in_the_workspace(tmp_path, ran):
    ctx, asked = computer(tmp_path)
    result = tools().call("take_screenshot", {}, ctx)
    assert "media/screenshot-" in result and "look_at_image" in result
    assert (tmp_path / "ws" / ctx.files[0]).read_bytes() == b"\x89PNG-screen"
    assert asked[0].action.kind == "screenshot" and asked[0].can_remember        # "allow + remember" is possible
    assert "CopyFromScreen" in ran[0][0][-1]


def test_reading_the_clipboard_asks_every_time(tmp_path, ran):
    ctx, asked = computer(tmp_path, answer=(True, True))
    for _ in range(2):
        assert tools().call("read_clipboard", {}, ctx) == "kopyalanan metin"
    assert len(asked) == 2 and asked[0].can_remember is False        # it may hold a copied password
    assert ctx.tainted_by                                             # and it is outside content


def test_writing_to_the_clipboard_passes_the_text_safely(tmp_path, ran):
    ctx, asked = computer(tmp_path)
    assert "clipboard" in tools().call("write_clipboard", {"text": "Merhaba 'dünya' $env:x"}, ctx)
    argv, kwargs = ran[0]
    assert kwargs["env"]["PA_TEXT"] == "Merhaba 'dünya' $env:x" and "Merhaba" not in argv[-1]


def test_programs_open_after_approval_with_a_narrow_rule(tmp_path, ran):
    ctx, asked = computer(tmp_path, answer=(True, True))
    tools().call("open_app", {"name": "Excel", "argument": "C:/Users/me/fiyatlar.xlsx"}, ctx)
    tools().call("open_app", {"name": "excel", "argument": "C:/Users/me/fiyatlar.xlsx"}, ctx)   # the rule covers it
    tools().call("open_app", {"name": "excel", "argument": "C:/Users/me/maas.xlsx"}, ctx)      # new file: asks
    assert len(asked) == 2 and asked[0].action.scope == {"program": "excel", "argument": "C:/Users/me/fiyatlar.xlsx"}
    argv, kwargs = ran[0]
    assert kwargs["env"]["PA_APP"] == "excel" and kwargs["env"]["PA_ARGS"] == "C:/Users/me/fiyatlar.xlsx"


def test_friendly_program_names(tmp_path, ran):
    ctx, _ = computer(tmp_path)
    tools().call("open_app", {"name": "Hesap Makinesi"}, ctx)
    tools().call("open_app", {"name": "word"}, ctx)
    assert [kwargs["env"]["PA_APP"] for _, kwargs in ran] == ["calc", "winword"]


@pytest.mark.parametrize("program", ["cmd", "powershell.exe", "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
                                     "wscript", "mshta", "regedit"])
def test_command_shells_cannot_be_opened_this_way(tmp_path, ran, program):
    ctx, asked = computer(tmp_path)
    assert "run_command" in tools().call("open_app", {"name": program, "argument": "/c del *.*"}, ctx)
    assert asked == [] and ran == []


def test_desktop_tools_are_hidden_in_safe_mode(tmp_path, ran):
    names = {s["function"]["name"] for s in tools().schemas(computer_use=False)}
    assert not {"take_screenshot", "read_clipboard", "write_clipboard", "open_app"} & names
    ctx = ToolContext(workspace=tmp_path / "ws")
    assert "safe mode" in tools().call("take_screenshot", {}, ctx) and ran == []
