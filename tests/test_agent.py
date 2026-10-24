from conftest import call, say

from pocketagent.agent import parse_text_tool_call
from pocketagent.llm import Reply


def test_answers_directly_without_tools(make_runtime):
    runtime, brain = make_runtime(say("Merhaba! Nasıl yardımcı olabilirim?"))
    assert runtime.agent.ask("1", "Merhaba") == "Merhaba! Nasıl yardımcı olabilirim?"
    assert brain.calls[0]["tools"]                     # tools were offered to the model


def test_runs_native_tool_call_and_feeds_result_back(make_runtime):
    runtime, brain = make_runtime(call("calculate", expression="1250*0.18"), say("KDV 225 TL."))
    used = []
    answer = runtime.agent.ask("1", "1250 TL'nin %18 KDV'si?", on_tool=lambda n, a, r: used.append((n, r)))
    assert answer == "KDV 225 TL."
    assert used == [("calculate", "225")]
    second_request = brain.calls[1]["messages"]
    assert second_request[-1] == {"role": "tool", "tool_call_id": "call_calculate", "content": "225"}


def test_text_mode_tool_call_for_small_models(make_runtime):
    runtime, brain = make_runtime(
        say('```json\n{"tool": "calculate", "arguments": {"expression": "6*7"}}\n```'),
        say("The answer is 42."), native_tools=False)
    assert runtime.agent.ask("1", "6 times 7?") == "The answer is 42."
    assert brain.calls[0]["tools"]                      # the brain describes them in text (see test_llm)
    assert "Result of calculate:\n42" in brain.calls[1]["messages"][-1]["content"]


def test_thinking_is_removed_from_the_answer(make_runtime):
    runtime, _ = make_runtime(say("<think>user greets me...</think>\nHi there!"))
    assert runtime.agent.ask("1", "hi") == "Hi there!"


def test_stops_after_max_steps(make_runtime):
    runtime, _ = make_runtime(*[call("get_current_time")] * 8)
    assert "stopped after 8 steps" in runtime.agent.ask("1", "loop forever")


def test_history_keeps_only_question_and_final_answer(make_runtime):
    runtime, brain = make_runtime(call("calculate", expression="2+2"), say("4"), say("You asked 2+2."))
    runtime.agent.ask("1", "2+2?")
    runtime.agent.ask("1", "What did I ask?")
    history = [m for m in brain.calls[2]["messages"] if m["role"] != "system"]
    assert history == [{"role": "user", "content": "2+2?"}, {"role": "assistant", "content": "4"},
                       {"role": "user", "content": "What did I ask?"}]


def test_saved_notes_appear_in_the_system_prompt(make_runtime):
    runtime, brain = make_runtime(say("ok"))
    runtime.notes.add("The user's name is Aykut")
    runtime.agent.ask("1", "hello")
    assert "The user's name is Aykut" in brain.calls[0]["messages"][0]["content"]


def test_parse_text_tool_call_ignores_normal_json_answers():
    known = {"calculate": object()}
    assert parse_text_tool_call('Here is your JSON: {"name": "Elif", "age": 7}', known) is None
    assert parse_text_tool_call('{"tool": "unknown_tool", "arguments": {}}', known) is None
    found = parse_text_tool_call('Sure. {"tool": "calculate", "arguments": {"expression": "1+1"}}', known)
    assert found.name == "calculate" and found.arguments == {"expression": "1+1"}


def test_run_reports_tools_and_the_brain_that_answered(make_runtime):
    runtime, _ = make_runtime(call("calculate", expression="2+2"),
                              Reply(content="4", brain="Groq · llama", skipped=["OpenRouter · x: HTTP 429"]))
    answer = runtime.agent.run("1", "2+2?")
    assert (answer.text, answer.tools, answer.brain) == ("4", ["calculate"], "Groq · llama")
    assert answer.skipped == ["OpenRouter · x: HTTP 429"]
