"""Shortcuts on Windows: start PocketAgent when you log in, and a PocketAgent icon on the desktop.

The shortcuts open the normal PocketAgent window (the startup one minimized to the taskbar), never a
hidden process: you can always see that the agent is running, and close it.
Remove the startup one from the panel, or delete PocketAgent.lnk from shell:startup.
"""

import os
import subprocess
import sys
from pathlib import Path

SHORTCUT = "PocketAgent.lnk"
PROJECT = Path(__file__).resolve().parent.parent     # the folder that holds the pocketagent package

# Windows has no standard-library API for .lnk files; PowerShell's WScript.Shell writes them.
# The paths travel in environment variables, so no quoting or injection problems in the script.
POWERSHELL = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:PA_LINK); "
              "$s.TargetPath = $env:PA_TARGET; $s.Arguments = $env:PA_ARGS; $s.WorkingDirectory = $env:PA_DIR; "
              "$s.WindowStyle = [int]$env:PA_STYLE; $s.Description = 'PocketAgent: your local AI agent'; $s.Save()")
DESKTOP = "[Environment]::GetFolderPath('Desktop')"   # also right when OneDrive moved the desktop


class AutostartError(Exception):
    pass


def supported() -> bool:
    return os.name == "nt"


def startup_folder() -> Path:
    return Path(os.environ.get("APPDATA", str(Path.home()))) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def shortcut_path() -> Path:
    return startup_folder() / SHORTCUT


def launch_command(autostart: bool = True) -> tuple[str, str, str]:
    """(program, arguments, working folder) that start PocketAgent the way it is running now."""
    flag = "--autostart" if autostart else ""
    if getattr(sys, "frozen", False):            # PocketAgent.exe
        return sys.executable, flag, str(Path(sys.executable).parent)
    # from the source folder: python must start there to find the package
    return sys.executable, f"-m pocketagent {flag}".strip(), str(PROJECT)


def _powershell(script: str, env: dict, run) -> subprocess.CompletedProcess:
    try:
        return run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], env=env,
                   capture_output=True, text=True, timeout=60,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as error:
        raise AutostartError(f"Could not run PowerShell: {error}") from None


def make_shortcut(link: Path, autostart: bool, minimized: bool, run=subprocess.run) -> Path:
    if not supported():
        raise AutostartError("Shortcuts are only available on Windows.")
    link.parent.mkdir(parents=True, exist_ok=True)
    target, arguments, folder = launch_command(autostart)
    env = {**os.environ, "PA_LINK": str(link), "PA_TARGET": target, "PA_ARGS": arguments, "PA_DIR": folder,
           "PA_STYLE": "7" if minimized else "1"}
    result = _powershell(POWERSHELL, env, run)
    if result.returncode != 0 or not link.exists():
        raise AutostartError(f"Could not create the shortcut: {(result.stderr or '').strip()[:300]}")
    return link


def enable(run=subprocess.run) -> Path:
    if not supported():
        raise AutostartError("Starting with the computer is only available on Windows.")
    return make_shortcut(shortcut_path(), autostart=True, minimized=True, run=run)


def disable() -> None:
    shortcut_path().unlink(missing_ok=True)


def is_enabled() -> bool:
    return supported() and shortcut_path().exists()


def desktop_folder(run=subprocess.run) -> Path:
    if not supported():
        raise AutostartError("Shortcuts are only available on Windows.")
    result = _powershell(DESKTOP, dict(os.environ), run)
    folder = (result.stdout or "").strip()
    if result.returncode != 0 or not folder:
        raise AutostartError("Could not find the desktop folder.")
    return Path(folder)


def desktop_shortcut(run=subprocess.run) -> Path:
    """A PocketAgent icon on the desktop that always starts this copy of the program."""
    return make_shortcut(desktop_folder(run) / SHORTCUT, autostart=False, minimized=False, run=run)
