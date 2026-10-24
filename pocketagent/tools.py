"""The skill system.

A *skill* is a Python file with one or more *tools*: plain functions marked with @tool.
The function name, type hints and docstring are turned into the JSON schema the model
sees, so writing a new tool is just writing a normal, documented function:

    from pocketagent.tools import tool

    @tool
    def roll_dice(sides: int = 6) -> str:
        '''Roll a die.

        Args:
            sides: number of sides
        '''
        import random
        return str(random.randint(1, sides))

Tools that need the agent's workspace, memory or notifier take a `ctx` parameter
(a ToolContext); it is filled in automatically and never shown to the model.
"""

import importlib
import importlib.util
import inspect
import json
import pkgutil
import re
import types
import typing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

MAX_RESULT_CHARS = 6000
_JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}


@dataclass
class ToolContext:
    workspace: Path
    memory: Any = None        # NoteStore
    reminders: Any = None     # ReminderStore
    chat_id: str = "terminal"


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    func: Callable
    skill: str
    wants_context: bool

    def schema(self) -> dict:
        return {"type": "function",
                "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


def tool(func: Callable) -> Callable:
    """Mark a function as a tool the agent may call."""
    func.__pocket_tool__ = True
    return func


def _parse_docstring(doc: str) -> tuple[str, dict[str, str]]:
    """Google-style docstring -> (summary, {param: description})."""
    doc = inspect.cleandoc(doc or "")
    summary, _, rest = doc.partition("\n\n")
    params = {}
    if "Args:" in doc:
        block = doc.split("Args:", 1)[1]
        for line in block.splitlines():
            match = re.match(r"\s*(\w+)\s*(\([^)]*\))?:\s*(.+)", line)
            if match:
                params[match.group(1)] = match.group(3).strip()
            elif re.match(r"\s*(Returns?|Raises?):", line):
                break
    return " ".join(summary.split()), params


def _json_type(annotation) -> str:
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):   # Optional[int] / int | None
        inner = [a for a in typing.get_args(annotation) if a is not type(None)]
        return _json_type(inner[0]) if inner else "string"
    return _JSON_TYPES.get(origin or annotation, "string")


def build_tool(func: Callable, skill: str) -> Tool:
    summary, param_docs = _parse_docstring(func.__doc__)
    hints = typing.get_type_hints(func)
    properties, required, wants_context = {}, [], False
    for name, param in inspect.signature(func).parameters.items():
        if name == "ctx":
            wants_context = True
            continue
        prop = {"type": _json_type(hints.get(name, str))}
        if name in param_docs:
            prop["description"] = param_docs[name]
        properties[name] = prop
        if param.default is inspect.Parameter.empty:
            required.append(name)
    return Tool(name=func.__name__, description=summary or func.__name__,
                parameters={"type": "object", "properties": properties, "required": required},
                func=func, skill=skill, wants_context=wants_context)


class ToolRegistry:
    def __init__(self):
        self.tools: dict[str, Tool] = {}
        self.errors: list[str] = []       # skills that failed to load

    # ---------- loading ----------
    def add_module(self, module, skill: str) -> int:
        count = 0
        for _, obj in inspect.getmembers(module, inspect.isfunction):
            if getattr(obj, "__pocket_tool__", False):
                self.tools[obj.__name__] = build_tool(obj, skill)
                count += 1
        return count

    def load_builtin(self) -> None:
        import pocketagent.skills as package
        for info in pkgutil.iter_modules(package.__path__):
            module = importlib.import_module(f"pocketagent.skills.{info.name}")
            self.add_module(module, info.name)

    def load_folder(self, folder: Path) -> None:
        """Load user skills: every *.py file in the folder (only add skills you trust)."""
        if not folder.is_dir():
            return
        for path in sorted(folder.glob("*.py")):
            try:
                spec = importlib.util.spec_from_file_location(f"pocketagent_user_{path.stem}", path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                self.add_module(module, f"user:{path.stem}")
            except Exception as error:   # a broken skill must not stop the agent
                self.errors.append(f"{path.name}: {type(error).__name__}: {error}")

    # ---------- for the model ----------
    def schemas(self) -> list[dict]:
        return [t.schema() for t in self.tools.values()]

    def describe_for_prompt(self) -> str:
        """Text description of the tools, for models without native tool calling."""
        from pocketagent.llm import describe_tools
        return describe_tools(self.schemas())

    # ---------- running ----------
    def call(self, name: str, arguments: dict, ctx: ToolContext) -> str:
        t = self.tools.get(name)
        if t is None:
            return f"Error: there is no tool called '{name}'. Available: {', '.join(self.tools)}"
        allowed = t.parameters["properties"]
        missing = [p for p in t.parameters["required"] if p not in arguments]
        if missing:
            return f"Error: missing argument(s) for {name}: {', '.join(missing)}"
        kwargs = {k: v for k, v in arguments.items() if k in allowed}
        if t.wants_context:
            kwargs["ctx"] = ctx
        try:
            result = t.func(**kwargs)
        except Exception as error:   # report the problem to the model instead of crashing
            return f"Error while running {name}: {type(error).__name__}: {error}"
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
        if len(text) > MAX_RESULT_CHARS:
            text = text[:MAX_RESULT_CHARS] + f"\n...[cut, {len(text) - MAX_RESULT_CHARS} more characters]"
        return text
