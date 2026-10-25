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

Tools that act on the computer are marked @tool(os_access=True): they are hidden and refused
until the user turns computer use on, and they ask for approval with ctx.approve(Action(...)).
Tools whose output comes from outside (web pages, files, command output) are marked
untrusted_output=True: after one of them ran, every action in that turn needs a fresh approval.
"""

import importlib
import importlib.util
import inspect
import json
import pkgutil
import re
import types
import typing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from pocketagent.approvals import Refused, Stopped

MAX_RESULT_CHARS = 6000
_JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}


@dataclass
class ToolContext:
    workspace: Path
    memory: Any = None        # NoteStore
    reminders: Any = None     # ReminderStore
    chat_id: str = "terminal"
    decisions: Any = None     # DecisionLog
    approvals: Any = None     # ApprovalEngine
    audit: Any = None         # AuditLog
    source: str = ""          # where the request came from: panel, telegram, terminal
    computer_use: bool = False
    generation: int | None = None                        # for the stop button (see ApprovalEngine)
    tainted_by: list = field(default_factory=list)      # untrusted content read during this turn
    studio: Any = None        # media.Studio: the specialists (image, speech, writer)
    tasks: Any = None         # schedule.TaskStore
    browser: Any = None       # browser_control.BrowserControl: the agent's browser window
    files: list = field(default_factory=list)           # workspace files made for the answer

    def approve(self, action) -> str:
        """Ask the user (or a saved rule) before acting on the computer; raises Refused or Stopped."""
        if self.approvals is None:
            raise Refused("there is no approval engine, so nothing may run on the computer")
        return self.approvals.request(action, tainted=self.tainted_by, source=self.source,
                                      generation=self.generation)

    def check_stop(self) -> None:
        if self.approvals is not None:
            self.approvals.check(self.generation)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    func: Callable
    skill: str
    wants_context: bool
    os_access: bool = False          # acts on the computer: needs computer use + approval
    untrusted_output: bool = False   # returns outside content (web, files, command output)

    def schema(self) -> dict:
        return {"type": "function",
                "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


def tool(func: Callable | None = None, *, os_access: bool = False, untrusted_output: bool = False):
    """Mark a function as a tool the agent may call: @tool, or @tool(os_access=True, ...)."""
    def mark(f: Callable) -> Callable:
        f.__pocket_tool__ = True
        f.__pocket_os_access__, f.__pocket_untrusted__ = os_access, untrusted_output
        return f
    return mark(func) if func is not None else mark


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
                func=func, skill=skill, wants_context=wants_context,
                os_access=getattr(func, "__pocket_os_access__", False),
                untrusted_output=getattr(func, "__pocket_untrusted__", False))


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
    def schemas(self, computer_use: bool = True) -> list[dict]:
        """The tools the model may see; tools that act on the computer only when computer use is on."""
        return [t.schema() for t in self.tools.values() if computer_use or not t.os_access]

    def describe_for_prompt(self) -> str:
        """Text description of the tools, for models without native tool calling."""
        from pocketagent.llm import describe_tools
        return describe_tools(self.schemas())

    # ---------- running ----------
    def call(self, name: str, arguments: dict, ctx: ToolContext) -> str:
        """Run a tool for the model. Every call is written to the audit log (when there is one)."""
        t = self.tools.get(name)
        after_untrusted = bool(ctx.tainted_by)       # was this call made after reading outside content?
        text = self._call(t, name, arguments, ctx)
        if t is not None and t.untrusted_output:
            first = next(iter(arguments.values()), "")
            ctx.tainted_by.append(f"{name}({str(first)[:80]})")
        if ctx.audit is not None:
            ctx.audit.write("tool", tool=name, args=arguments, result=text, source=ctx.source,
                            tainted=after_untrusted)
        return text

    def _call(self, t: Tool | None, name: str, arguments: dict, ctx: ToolContext) -> str:
        if t is None:
            return f"Error: there is no tool called '{name}'. Available: {', '.join(self.tools)}"
        if t.os_access and not ctx.computer_use:
            return ("Not done: computer use is off (safe mode). Tell the user they can turn it on in the panel "
                    "if they want you to act on the computer.")
        allowed = t.parameters["properties"]
        missing = [p for p in t.parameters["required"] if p not in arguments]
        if missing:
            return f"Error: missing argument(s) for {name}: {', '.join(missing)}"
        kwargs = {k: v for k, v in arguments.items() if k in allowed}
        if t.wants_context:
            kwargs["ctx"] = ctx
        try:
            result = t.func(**kwargs)
        except Stopped:
            raise                    # the user pressed stop: end the whole turn
        except Refused as error:
            return f"Not done: {error}. Do not try again unless the user asks."
        except Exception as error:   # report the problem to the model instead of crashing
            return f"Error while running {name}: {type(error).__name__}: {error}"
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
        if len(text) > MAX_RESULT_CHARS:
            text = text[:MAX_RESULT_CHARS] + f"\n...[cut, {len(text) - MAX_RESULT_CHARS} more characters]"
        return text
