"""Run commands on this computer, each one approved by the user first.

Hidden from the model until the user turns computer use on. Every command is shown to the user
with its folder; an approval can be saved as a rule for that exact command in that exact folder.
Deleting, passwords/keys, payments and messages always ask again. The output counts as
untrusted content: after it was read, the next action in the same turn needs a fresh approval.
"""

import os
import shutil
import subprocess
from pathlib import Path
from subprocess import Popen  # module-level name, so tests can replace it

from pocketagent.approvals import Action, classify_command, kill_tree
from pocketagent.tools import ToolContext, tool

MAX_OUTPUT = 20000
SHELL = "PowerShell" if os.name == "nt" else "sh"


UTF8 = "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "   # non-English output survives the pipe


def _argv(command: str) -> list[str]:
    if os.name == "nt":
        if shutil.which("pwsh"):            # PowerShell 7 understands && and || like other shells
            return ["pwsh", "-NoProfile", "-NonInteractive", "-Command", UTF8 + command]
        if "&&" in command or "||" in command:     # Windows PowerShell 5.1 does not; cmd.exe does
            return ["cmd", "/d", "/s", "/c", "chcp 65001 >nul & " + command]
        return ["powershell", "-NoProfile", "-NonInteractive", "-Command", UTF8 + command]
    return ["/bin/sh", "-c", command]


@tool(os_access=True, untrusted_output=True)
def run_command(ctx: ToolContext, command: str, folder: str = "", timeout_seconds: int = 300) -> str:
    """Run a command in the computer's shell (PowerShell on Windows: separate commands with ';'; sh elsewhere). The user approves every command first.

    Args:
        command: the exact command line to run
        folder: folder to run it in (default: the agent's workspace folder)
        timeout_seconds: stop the command after this many seconds (default 300)
    """
    where = Path(folder).expanduser().resolve() if folder.strip() else ctx.workspace.resolve()
    if not folder.strip():
        where.mkdir(parents=True, exist_ok=True)
    if not where.is_dir():
        return f"The folder '{where}' does not exist."
    params = {"command": command.strip(), "folder": str(where)}
    ctx.approve(Action("shell", f"Run a {SHELL} command", params, scope=dict(params),
                       classes=classify_command(command)))

    process = Popen(_argv(command), cwd=str(where), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, start_new_session=os.name != "nt")
    ctx.approvals.track(process)      # the stop button ends it
    timed_out = False
    try:
        output, _ = process.communicate(timeout=max(1, int(timeout_seconds)))
    except subprocess.TimeoutExpired:
        timed_out = True
        kill_tree(process)
        output, _ = process.communicate()
    finally:
        ctx.approvals.untrack(process)
    ctx.check_stop()
    text = (output or b"").decode("utf-8", errors="replace").strip()
    if len(text) > MAX_OUTPUT:
        text = text[:MAX_OUTPUT] + "\n...[output cut]"
    status = f"Exit code {process.returncode}" + (f" (stopped after {timeout_seconds} s)" if timed_out else "")
    return f"{status}\n{text or '(no output)'}"
