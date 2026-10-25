"""The desktop: take a screenshot, read or fill the clipboard, open programs. Each needs approval.

Hidden from the model until the user turns computer use on. Text travels to PowerShell in
environment variables, never inside the script, so nothing in it can run as a command.
"""

import os
import re
import subprocess
import tempfile
from pathlib import Path

from pocketagent.approvals import Action, classify_command
from pocketagent.skills.specialists import save_media
from pocketagent.tools import ToolContext, tool

run = subprocess.run      # module-level, so tests can replace it

SCREENSHOT = ("Add-Type -AssemblyName System.Windows.Forms, System.Drawing; "
              "Add-Type -Name Dpi -Namespace PA -MemberDefinition "
              "'[DllImport(\"user32.dll\")] public static extern bool SetProcessDPIAware();'; "
              "[PA.Dpi]::SetProcessDPIAware() | Out-Null; "
              "$b = [System.Windows.Forms.SystemInformation]::VirtualScreen; "
              "$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height; "
              "$g = [System.Drawing.Graphics]::FromImage($bmp); "
              "$g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size); "
              "$bmp.Save($env:PA_OUT, [System.Drawing.Imaging.ImageFormat]::Png); $g.Dispose(); $bmp.Dispose()")
READ_CLIPBOARD = "[Console]::OutputEncoding = [Text.Encoding]::UTF8; Get-Clipboard -Raw"
WRITE_CLIPBOARD = "Set-Clipboard -Value $env:PA_TEXT"
OPEN_APP = ("if ($env:PA_ARGS) { Start-Process -FilePath $env:PA_APP -ArgumentList $env:PA_ARGS } "
            "else { Start-Process -FilePath $env:PA_APP }")

FRIENDLY = {"word": "winword", "excel": "excel", "powerpoint": "powerpnt", "outlook": "outlook",
            "edge": "msedge", "chrome": "chrome", "firefox": "firefox", "notepad": "notepad",
            "not defteri": "notepad", "calculator": "calc", "hesap makinesi": "calc", "paint": "mspaint",
            "explorer": "explorer", "dosya gezgini": "explorer", "file explorer": "explorer",
            "spotify": "spotify", "vlc": "vlc"}
# programs that run commands or scripts: those go through run_command, where each command is shown
SHELLS = {"cmd", "powershell", "pwsh", "wt", "bash", "sh", "wsl", "wscript", "cscript", "mshta", "rundll32",
          "regsvr32", "reg", "regedit", "schtasks", "msiexec", "certutil", "bitsadmin", "python", "pythonw", "node"}


def _powershell(script: str, **env) -> subprocess.CompletedProcess:
    return run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
               env={**os.environ, **env}, capture_output=True, text=True, timeout=60,
               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _windows_only() -> str:
    return "" if os.name == "nt" else "This works on Windows for now."


@tool(os_access=True)
def take_screenshot(ctx: ToolContext) -> str:
    """Take a screenshot of the whole screen (with the user's approval). Then use look_at_image to see what is on it."""
    if _windows_only():
        return _windows_only()
    ctx.approve(Action("screenshot", "Take a screenshot of your screen", {"screen": "all screens"}, scope={}))
    handle, path = tempfile.mkstemp(suffix=".png")
    os.close(handle)
    try:
        result = _powershell(SCREENSHOT, PA_OUT=path)
        data = Path(path).read_bytes() if result.returncode == 0 else b""
    finally:
        Path(path).unlink(missing_ok=True)
    if not data:
        return f"The screenshot failed: {(result.stderr or '').strip()[:200]}"
    saved = save_media(ctx, "screenshot", data, ".png")
    return f"Screenshot saved as {saved}. Use look_at_image on it to see what is on the screen."


@tool(os_access=True, untrusted_output=True)
def read_clipboard(ctx: ToolContext) -> str:
    """Read the text the user copied (the clipboard), with their approval each time."""
    if _windows_only():
        return _windows_only()
    # it may hold a copied password, so this is asked every time and never becomes a rule
    ctx.approve(Action("clipboard", "Read what you copied (the clipboard)", {"clipboard": "read"}, scope={},
                       classes={"secrets"}))
    result = _powershell(READ_CLIPBOARD)
    if result.returncode != 0:
        return f"Could not read the clipboard: {(result.stderr or '').strip()[:200]}"
    return (result.stdout or "").rstrip("\r\n") or "(The clipboard is empty or holds no text.)"


@tool(os_access=True)
def write_clipboard(ctx: ToolContext, text: str) -> str:
    """Put text on the user's clipboard, ready to paste (with their approval).

    Args:
        text: the text to copy
    """
    if _windows_only():
        return _windows_only()
    ctx.approve(Action("clipboard_write", "Put text on your clipboard", {"text": text[:300]}, scope={}))
    result = _powershell(WRITE_CLIPBOARD, PA_TEXT=text)
    return "The text is on the clipboard: the user can paste it." if result.returncode == 0 else \
        f"Could not fill the clipboard: {(result.stderr or '').strip()[:200]}"


@tool(os_access=True)
def open_app(ctx: ToolContext, name: str, argument: str = "") -> str:
    """Open a program (e.g. "excel", "notepad", "calculator", "chrome") or a file or folder with its program, with the user's approval.

    Args:
        name: a program name, or the full path of a program, file or folder
        argument: optional, e.g. a file to open with the program
    """
    if _windows_only():
        return _windows_only()
    program = FRIENDLY.get(" ".join(name.lower().split()), name.strip())
    base = re.sub(r"\.(exe|com|bat|cmd|ps1|vbs|js|msc)$", "", Path(program.replace("\\", "/")).name.lower())
    if base in SHELLS or program.lower().endswith((".bat", ".cmd", ".ps1", ".vbs", ".js")):
        return ("Command shells and scripts are not opened this way: use run_command, where the user sees "
                "and approves each command.")
    ctx.approve(Action("app", f"Open {name}", {"program": program, "argument": argument},
                       scope={"program": program.lower(), "argument": argument},
                       classes=classify_command(argument) if argument else set()))
    result = _powershell(OPEN_APP, PA_APP=program, PA_ARGS=argument)
    if result.returncode != 0:
        return f"Could not open {name}: {(result.stderr or '').strip()[:200]}"
    return f"Opened {name}" + (f" with {argument}" if argument else "") + "."
