"""Identity, notes and decisions belong to the agent, not to the brain: they survive a brain change."""

from conftest import FakeBrain, call, say

from pocketagent.memory import DecisionLog, IdentityStore
from pocketagent.skills.decisions import list_decisions, record_decision
from pocketagent.tools import ToolContext


def test_identity_file_keeps_name_and_personality(home, tmp_path):
    store = IdentityStore(tmp_path, default_name="PocketAgent")
    assert store.get() == {"name": "PocketAgent", "personality": ""}
    store.set("Robi", "Kısa ve esprili cevap verir.")
    assert IdentityStore(tmp_path).get() == {"name": "Robi", "personality": "Kısa ve esprili cevap verir."}
    assert (tmp_path / "identity.json").exists()


def test_decision_log_is_an_append_only_jsonl_file(tmp_path):
    log = DecisionLog(tmp_path)
    log.add("Use Groq first, Gemini as backup", "Groq is faster")
    log.add("Reports go into the reports/ folder")
    lines = (tmp_path / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert [d["decision"] for d in log.recent()] == ["Use Groq first, Gemini as backup",
                                                     "Reports go into the reports/ folder"]
    assert log.recent(1)[0]["decision"] == "Reports go into the reports/ folder"
    assert [d["reason"] for d in log.search("groq")] == ["Groq is faster"]


def test_decision_tools(tmp_path):
    ctx = ToolContext(workspace=tmp_path, decisions=DecisionLog(tmp_path))
    assert "Logged decision #1" in record_decision(ctx, "Weekly report every Monday", "the user asked")
    assert "Weekly report every Monday (the user asked)" in list_decisions(ctx)
    assert list_decisions(ctx, "holiday") == "No matching decisions."


def test_a_new_brain_gets_the_same_identity_notes_and_decisions(make_runtime):
    runtime, first = make_runtime(call("record_decision", decision="Answer in Turkish", reason="user prefers it"),
                                  say("Tamam."))
    runtime.identity.set("Robi", "Friendly and brief.")
    runtime.notes.add("The user's name is Aykut")
    runtime.agent.ask("1", "Bundan sonra Türkçe cevap ver")

    second = FakeBrain(say("Merhaba Aykut!"))        # the user switches to another brain
    runtime.agent.brain = second
    runtime.agent.ask("1", "Merhaba")
    for brain in (first, second):
        system = brain.calls[-1]["messages"][0]["content"]
        assert system.startswith("You are Robi,")
        assert "Friendly and brief." in system and "The user's name is Aykut" in system
    assert "Answer in Turkish (user prefers it)" in second.calls[0]["messages"][0]["content"]
