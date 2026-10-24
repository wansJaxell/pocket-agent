from pathlib import Path

from pocketagent.tools import ToolContext, ToolRegistry, build_tool, tool


@tool
def book_table(people: int, time: str, note: str = "", vegan: bool | None = None) -> str:
    """Book a restaurant table.

    Args:
        people: how many guests
        time: for example "19:30"
        note: anything the restaurant should know
        vegan: whether a vegan menu is needed
    """
    return f"{people}@{time}"


def ctx(tmp_path):
    return ToolContext(workspace=Path(tmp_path))


def test_schema_comes_from_signature_and_docstring():
    t = build_tool(book_table, "test")
    assert t.description == "Book a restaurant table."
    props = t.parameters["properties"]
    assert props["people"] == {"type": "integer", "description": "how many guests"}
    assert props["vegan"]["type"] == "boolean"          # Optional[bool] -> boolean
    assert t.parameters["required"] == ["people", "time"]


def test_ctx_parameter_is_hidden_from_the_model():
    @tool
    def needs_context(ctx: ToolContext, text: str) -> str:
        """Example."""
        return text
    t = build_tool(needs_context, "test")
    assert "ctx" not in t.parameters["properties"]
    assert t.wants_context


def test_call_runs_tool_and_ignores_unknown_arguments(tmp_path):
    registry = ToolRegistry()
    registry.tools["book_table"] = build_tool(book_table, "test")
    assert registry.call("book_table", {"people": 4, "time": "20:00", "made_up": 1}, ctx(tmp_path)) == "4@20:00"


def test_errors_are_returned_to_the_model_not_raised(tmp_path):
    registry = ToolRegistry()
    registry.tools["book_table"] = build_tool(book_table, "test")
    assert "no tool called" in registry.call("fly_to_moon", {}, ctx(tmp_path))
    assert "missing argument" in registry.call("book_table", {"people": 2}, ctx(tmp_path))


def test_crashing_tool_and_long_output_are_handled(tmp_path):
    @tool
    def broken() -> str:
        """Always fails."""
        raise RuntimeError("boom")

    @tool
    def chatty() -> str:
        """Too long."""
        return "x" * 10000
    registry = ToolRegistry()
    registry.tools["broken"] = build_tool(broken, "test")
    registry.tools["chatty"] = build_tool(chatty, "test")
    assert "RuntimeError: boom" in registry.call("broken", {}, ctx(tmp_path))
    assert "[cut" in registry.call("chatty", {}, ctx(tmp_path))


def test_user_skill_folder_is_loaded_and_broken_files_reported(tmp_path):
    folder = tmp_path / "skills"
    folder.mkdir()
    (folder / "dice.py").write_text(
        "from pocketagent.tools import tool\n\n@tool\ndef roll(sides: int = 6) -> str:\n"
        "    '''Roll a die.'''\n    return '4'\n", encoding="utf-8")
    (folder / "broken.py").write_text("this is not python", encoding="utf-8")
    registry = ToolRegistry()
    registry.load_folder(folder)
    assert registry.tools["roll"].skill == "user:dice"
    assert registry.errors and registry.errors[0].startswith("broken.py")


def test_all_builtin_skills_load():
    registry = ToolRegistry()
    registry.load_builtin()
    assert {"calculate", "get_current_time", "read_file", "write_file", "web_search",
            "remember", "set_reminder"} <= set(registry.tools)
