"""Command line: `pocketagent` (or double-click PocketAgent.exe).

    pocketagent            opens the panel in your browser; runs Telegram and reminders in the background
    pocketagent setup      terminal setup (for computers without a browser)
    pocketagent chat       chat in this terminal only
    pocketagent telegram   run only the Telegram bot (no panel)
    pocketagent skills     list loaded skills and tools
    pocketagent doctor     check the brain and Telegram connections
"""

import argparse
import getpass
import os
import signal
import subprocess
import sys
import threading
import time
import webbrowser

import requests

from pocketagent import __version__, vault
from pocketagent import config as cfg
from pocketagent.app import App, Runtime, start_reminder_loop

__all__ = ["main", "Runtime", "start_reminder_loop"]


def terminal_chat(runtime: Runtime, stop: threading.Event) -> None:
    print(f"\n{runtime.config.agent_name} · {len(runtime.config.brains())} brain(s) · "
          f"{len(runtime.registry.tools)} tools")
    print("Type your message. Commands: /skills  /reset  /exit\n")
    while not stop.is_set():
        try:
            text = input("You: ").strip()
        except EOFError:
            break
        if not text:
            continue
        if text in ("/exit", "/quit"):
            break
        if text == "/reset":
            runtime.conversations.reset("terminal")
            print("Conversation cleared.\n")
            continue
        if text == "/skills":
            list_skills(runtime)
            continue
        try:
            answer = runtime.agent.run("terminal", text, on_tool=lambda name, args, result:
                                       print(f"  🔧 {name}({', '.join(f'{k}={v!r}' for k, v in args.items())})"))
            reply = answer.text + (f"\n  🧠 {answer.brain}" if answer.brain else "")
        except Exception as error:
            reply = f"⚠️ Could not reach the brain: {type(error).__name__}: {error}"
        print(f"\n{runtime.config.agent_name}: {reply}\n")


def list_skills(runtime: Runtime) -> None:
    by_skill: dict[str, list] = {}
    for t in runtime.registry.tools.values():
        by_skill.setdefault(t.skill, []).append(t)
    for skill, tools in sorted(by_skill.items()):
        print(f"[{skill}]")
        for t in tools:
            print(f"  {t.name}: {t.description}")
    for error in runtime.registry.errors:
        print(f"  ✗ could not load {error}")
    print(f"\nAdd your own skills as .py files in: {cfg.user_skills_dir()}\n")


def doctor(config: cfg.Config) -> None:
    from pocketagent.setup_wizard import TELEGRAM_API, ConsoleIO, test_brain
    print(f"Config: {cfg.config_path()}")
    for number, brain in enumerate(config.brains(), 1):
        print(f"Brain {number}: {brain.provider} · {brain.model} · {brain.base_url}")
    test_brain(config, ConsoleIO())
    if config.telegram.token:
        me = requests.get(TELEGRAM_API.format(token=config.telegram.token, method="getMe"), timeout=15).json()
        print("Telegram:", f"✓ @{me['result']['username']}" if me.get("ok") else f"✗ {me}")
    else:
        print("Telegram: not configured")


def console_approver(engine):
    """Approval requests from the terminal chat are answered in the terminal."""
    def ask(pending):
        if pending.source != "terminal":
            return
        print(f"\n  🔐 Approval needed: {pending.action.summary}")
        for key, value in pending.action.params.items():
            print(f"     {key}: {value}")
        if pending.classes:
            print(f"     ⚠️ always asks: {', '.join(pending.classes)}")
        if pending.tainted:
            print(f"     ⚠️ after reading: {', '.join(pending.tainted)}")
        choices = "[y] once  [r] remember  [n] no" if pending.can_remember else "[y] once  [n] no"
        answer = input(f"     {choices}: ").strip().lower()
        engine.answer(pending.id, answer in ("y", "yes", "e", "evet", "r"), answer == "r", by="terminal")
    return ask


def run(config: cfg.Config, mode: str) -> None:
    """Terminal chat and/or the Telegram bot, without the panel."""
    from pocketagent.jobs import JobQueue
    from pocketagent.telegram_bot import TelegramBot

    runtime = Runtime(config)
    stop = threading.Event()
    bot = None
    runtime.approvals.notifiers.append(console_approver(runtime.approvals))

    def emergency_stop(by):
        summary = runtime.approvals.stop_everything(by)
        config.computer_use = False
        cfg.save(config)
        return summary
    if mode in ("all", "telegram") and config.telegram_ready:
        bot = TelegramBot(config.telegram.token, config.telegram.owner_chat_id, runtime.agent,
                          runtime.registry, runtime.conversations, jobs=JobQueue(),
                          approvals=runtime.approvals, on_stop=emergency_stop, language=lambda: config.language)
        runtime.approvals.notifiers.append(bot.ask_approval)
        runtime.approvals.resolved.append(bot.approval_resolved)
        threading.Thread(target=bot.run_forever, args=(stop,), daemon=True).start()
        print("Telegram bot is running: message your bot from any device.")
    elif mode == "telegram":
        print("Telegram is not set up yet. Run: pocketagent setup")
        return

    def notify(chat_id, text):
        if bot and str(chat_id) != "terminal":
            bot.send(chat_id, text)
        else:
            print(f"\n{text}\nYou: ", end="", flush=True)
    start_reminder_loop(runtime, notify, stop)

    try:
        if mode == "telegram":
            print("Press Ctrl+C to stop.")
            while True:
                time.sleep(1)
        else:
            terminal_chat(runtime, stop)
    finally:
        stop.set()


def unlock_in_terminal(config: cfg.Config, ask=getpass.getpass, tries: int = 3) -> bool:
    """Locked mode without the panel: ask for the panel password here."""
    if not config.locked:
        return True
    for _ in range(tries):
        try:
            cfg.unlock(config, ask("Panel password (keys are encrypted): "))
            return True
        except vault.WrongPassword:
            print("Wrong password.")
    return False


def running_instance(port: int) -> dict | None:
    """The PocketAgent already answering on this port ({"app", "version", "pid"}), if any."""
    session = requests.Session()
    session.trust_env = False                      # never ask a proxy about 127.0.0.1
    try:
        info = session.get(f"http://127.0.0.1:{port}/api/ping", timeout=2).json()
    except Exception:
        return None
    return info if isinstance(info, dict) and info.get("app") == "PocketAgent" else None


def start_plan(info: dict | None) -> str:
    """"start" (nothing running), "open" (this version runs already) or "replace" (an older one runs)."""
    if info is None:
        return "start"
    return "open" if info.get("version") == __version__ else "replace"


def port_owner(port: int, run=subprocess.run) -> int | None:
    """The process listening on a port (for versions before 0.4, which did not say their process id)."""
    if os.name == "nt":
        argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                f"(Get-NetTCPConnection -LocalPort {int(port)} -State Listen).OwningProcess"]
    else:
        argv = ["lsof", "-ti", f"tcp:{int(port)}", "-sTCP:LISTEN"]
    try:
        output = run(argv, capture_output=True, text=True, timeout=30).stdout or ""
    except (OSError, subprocess.SubprocessError):
        return None
    numbers = [int(word) for word in output.split() if word.isdigit()]
    return numbers[0] if numbers else None


def stop_instance(info: dict, port: int, run=subprocess.run, pause: float = 0.5) -> bool:
    """Close an older PocketAgent so this version can take its place; True when the port is free."""
    pid = info.get("pid") or port_owner(port, run)
    if not pid:
        return False
    if os.name == "nt":
        run(["taskkill", "/PID", str(int(pid)), "/T", "/F"], capture_output=True, timeout=30)
    else:
        try:
            os.kill(int(pid), signal.SIGTERM)
        except OSError:
            return False
    for _ in range(40):
        if running_instance(port) is None:
            return True
        time.sleep(pause)
    return False


def serve(config: cfg.Config, open_browser: bool = True, port: int | None = None) -> None:
    """Start the panel (only on 127.0.0.1), Telegram and reminders; open the panel in the browser.

    In locked mode nothing secret is known until the password is typed into the panel.
    """
    from pocketagent.panel import PanelServer

    port = port or config.panel_port
    running = running_instance(port)
    plan = start_plan(running)
    if plan == "open":
        print(f"PocketAgent {__version__} is already running: http://127.0.0.1:{port}/")
        if open_browser:
            webbrowser.open(f"http://127.0.0.1:{port}/")
        return
    if plan == "replace":
        print(f"An older PocketAgent ({running.get('version') or 'before 0.4'}) is running: "
              f"closing it and starting {__version__}.")
        if not stop_instance(running, port):
            print("Could not close it: close the old PocketAgent window yourself, then start again.")
            return
    app = App(config)
    try:
        server = PanelServer(app, port=port)
    except OSError:
        server = PanelServer(app, port=0)              # the usual port is taken by another program
    server.start()
    server.app.start_services()
    print(f"PocketAgent {__version__} panel: {server.url}  (only this computer can open it)")
    print("Keep this window open while you use the agent. Press Ctrl+C to stop.")
    if config.locked:
        print("The panel is locked: open it and enter your password to start the agent.")
    if open_browser:
        webbrowser.open(server.url)
    try:
        while True:
            time.sleep(1)
    finally:
        server.app.stop_services()
        server.stop()


def main(argv=None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")   # old Windows consoles cannot print every emoji
    parser = argparse.ArgumentParser(prog="pocketagent", description="A small, local-first AI agent.")
    parser.add_argument("--version", action="version", version=f"PocketAgent {__version__}")
    parser.add_argument("command", nargs="?", default="start",
                        choices=["start", "setup", "chat", "telegram", "skills", "doctor"])
    parser.add_argument("--no-browser", action="store_true", help="do not open the panel in the browser")
    parser.add_argument("--port", type=int, default=None, help="panel port (default 8765)")
    parser.add_argument("--autostart", action="store_true",
                        help="started with Windows: open the browser only if the panel needs the password")
    args = parser.parse_args(argv)

    try:
        config = cfg.load()
        if args.command in ("setup", "chat", "telegram", "doctor") and not unlock_in_terminal(config):
            return
        if args.command == "setup" or (args.command in ("chat", "telegram") and not config.brain_ready):
            from pocketagent.setup_wizard import run_setup
            config = run_setup(config)
            if not config.brain_ready or args.command == "setup":
                return
        if args.command == "start":
            serve(config, port=args.port,
                  open_browser=not args.no_browser and (not args.autostart or config.locked))
        elif args.command == "skills":
            list_skills(Runtime(config))
        elif args.command == "doctor":
            doctor(config)
        else:
            run(config, {"chat": "chat", "telegram": "telegram"}[args.command])
    except KeyboardInterrupt:
        print("\nBye!")
    except Exception as error:
        print(f"\n⚠️ {type(error).__name__}: {error}")
        if getattr(sys, "frozen", False):          # double-clicked .exe: keep the window open
            input("Press Enter to close...")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
