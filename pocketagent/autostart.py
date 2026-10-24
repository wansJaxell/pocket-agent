"""Start PocketAgent when you log in to Windows: a shortcut in your Startup folder.

The shortcut opens the normal PocketAgent window (minimized to the taskbar), never a hidden
process: you can always see that the agent is running, and close it.
Remove it from the panel, or delete PocketAgent.lnk from shell:startup.
"""

import os
import subprocess
import sys
from pathlib import Path

SHORTCUT = "PocketAgent.lnk"

# Windows has no standard-library API for .lnk files; PowerShell's WScript.Shell writes them.
# The paths travel in environment variables, so no quoting or injection problems in the script.
POWERSHELL = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:PA_LINK); "
              "$s.TargetPath = $env:PA_TARGET; $s.Arguments = $env:PA_ARGS; $s.WorkingDirectory = $env:PA_DIR; "
              "$s.WindowStyle = 7; $s.Description = 'PocketAgent: your local AI agent'; $s.Save()")


class AutostartError(Exception):
    pass


def supported() -> bool:
    return os.name == "nt"


def startup_folder() -> Path:
    return Path(os.environ.get("APPDATA", str(Path.home()))) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def shortcut_path() -> Path:
    return startup_folder() / SHORTCUT


def launch_command() -> tuple[str, str, str]:
    """(program, arguments, working folder) that start PocketAgent the way it is running now."""
    if getattr(sys, "frozen", False):            # PocketAgent.exe
        return sys.executable, "--autostart", str(Path(sys.executable).parent)
    return sys.executable, "-m pocketagent --autostart", str(Path.home())


def enable(run=subprocess.run) -> Path:
    if not supported():
        raise AutostartError("Starting with the computer is only available on Windows.")
    link = shortcut_path()
    link.parent.mkdir(parents=True, exist_ok=True)
    target, arguments, folder = launch_command()
    env = {**os.environ, "PA_LINK": str(link), "PA_TARGET": target, "PA_ARGS": arguments, "PA_DIR": folder}
    try:
        result = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", POWERSHELL], env=env,
                     capture_output=True, text=True, timeout=60,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as error:
        raise AutostartError(f"Could not run PowerShell: {error}") from None
    if result.returncode != 0 or not link.exists():
        raise AutostartError(f"Could not create the shortcut: {(result.stderr or '').strip()[:300]}")
    return link


def disable() -> None:
    shortcut_path().unlink(missing_ok=True)


def is_enabled() -> bool:
    return supported() and shortcut_path().exists()
