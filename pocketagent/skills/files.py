"""Read and write files, only inside the agent's workspace folder."""

from pathlib import Path

from pocketagent.tools import ToolContext, tool

MAX_READ_CHARS = 20000


def _safe_path(ctx: ToolContext, relative: str) -> Path:
    """Resolve a path and refuse anything outside the workspace (e.g. '../../Windows')."""
    root = ctx.workspace.resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = (root / relative).resolve()
    if target != root and root not in target.parents:
        raise PermissionError(f"'{relative}' is outside the workspace folder")
    return target


@tool(untrusted_output=True)
def list_files(ctx: ToolContext, folder: str = ".") -> str:
    """List files in the workspace folder.

    Args:
        folder: sub-folder inside the workspace, "." for the top level
    """
    path = _safe_path(ctx, folder)
    if not path.is_dir():
        return f"'{folder}' is not a folder."
    entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    if not entries:
        return "The folder is empty."
    return "\n".join(f"{'[dir] ' if p.is_dir() else ''}{p.name}" +
                     ("" if p.is_dir() else f" ({p.stat().st_size} bytes)") for p in entries)


@tool(untrusted_output=True)
def read_file(ctx: ToolContext, path: str) -> str:
    """Read a text file from the workspace.

    Args:
        path: file path inside the workspace, e.g. "notes/todo.txt"
    """
    target = _safe_path(ctx, path)
    if not target.is_file():
        return f"File '{path}' does not exist."
    text = target.read_text(encoding="utf-8", errors="replace")
    return text if len(text) <= MAX_READ_CHARS else text[:MAX_READ_CHARS] + "\n...[file cut]"


@tool
def write_file(ctx: ToolContext, path: str, content: str, append: bool = False) -> str:
    """Create or update a text file in the workspace.

    Args:
        path: file path inside the workspace, e.g. "reports/summary.md"
        content: the text to write
        append: true to add to the end of the file instead of replacing it
    """
    target = _safe_path(ctx, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a" if append else "w", encoding="utf-8") as f:
        f.write(content)
    return f"Saved {len(content)} characters to {path}."
