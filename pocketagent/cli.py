"""Command line: `pocketagent` (or double-click PocketAgent.exe).

    pocketagent            first run: setup; afterwards: Telegram bot + terminal chat
    pocketagent setup      run the setup wizard again
    pocketagent chat       chat in this terminal only
    pocketagent telegram   run only the Telegram bot
    pocketagent skills     list loaded skills and tools
    pocketagent doctor     check the brain and Telegram connections
"""

import argparse
import sys
import threading
import time

from pocketagent import __version__
from pocketagent import config as cfg
from pocketagent.agent import Agent
from pocketagent.llm import Brain
from pocketagent.memory import ConversationStore, NoteStore, ReminderStore
from pocketagent.tools import ToolRegistry


class Runtime:
    """Everything the agent needs, built from the saved config."""

    def __init__(self, config: cfg.Config, brain=None):
        self.config = config
        self.registry = ToolRegistry()
        self.registry.load_builtin()
        self.registry.load_folder(cfg.user_skills_dir())
        memory = cfg.memory_dir()
        self.conversations = ConversationStore(memory, keep=config.history_messages)
        self.notes = NoteStore(memory)
        self.reminders = ReminderStore(memory)
        self.agent = Agent(config, brain or Brain(config.brain), self.registry, self.conversations,
                           self.notes, self.reminders, cfg.workspace_dir())


def start_reminder_loop(runtime: Runtime, notify, stop: threading.Event) -> None:
    def loop():
        while not stop.is_set():
            for item in runtime.reminders.pop_due():
                notify(item["chat_id"], f"⏰ Reminder: {item['text']}")
            stop.wait(15)
    threading.Thread(target=loop, daemon=True).start()


def terminal_chat(runtime: Runtime, stop: threading.Event) -> None:
    print(f"\n{runtime.config.agent_name} · model {runtime.config.brain.model} · "
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
            answer = runtime.agent.ask("terminal", text, on_tool=lambda name, args, result:
                                       print(f"  🔧 {name}({', '.join(f'{k}={v!r}' for k, v in args.items())})"))
        except Exception as error:
            answer = f"⚠️ Could not reach the brain: {type(error).__name__}: {error}"
        print(f"\n{runtime.config.agent_name}: {answer}\n")


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
    import requests
    from pocketagent.setup_wizard import TELEGRAM_API, test_brain, ConsoleIO
    print(f"Config: {cfg.config_path()}")
    print(f"Brain: {config.brain.provider} · {config.brain.model} · {config.brain.base_url}")
    test_brain(config, ConsoleIO())
    if config.telegram.token:
        me = requests.get(TELEGRAM_API.format(token=config.telegram.token, method="getMe"), timeout=15).json()
        print("Telegram:", f"✓ @{me['result']['username']}" if me.get("ok") else f"✗ {me}")
    else:
        print("Telegram: not configured")


def run(config: cfg.Config, mode: str) -> None:
    from pocketagent.telegram_bot import TelegramBot

    runtime = Runtime(config)
    stop = threading.Event()
    bot = None
    if mode in ("all", "telegram") and config.telegram_ready:
        bot = TelegramBot(config.telegram.token, config.telegram.owner_chat_id, runtime.agent,
                          runtime.registry, runtime.conversations)
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


def main(argv=None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")   # old Windows consoles cannot print every emoji
    parser = argparse.ArgumentParser(prog="pocketagent", description="A small, local-first AI agent.")
    parser.add_argument("--version", action="version", version=f"PocketAgent {__version__}")
    parser.add_argument("command", nargs="?", default="start",
                        choices=["start", "setup", "chat", "telegram", "skills", "doctor"])
    args = parser.parse_args(argv)

    try:
        config = cfg.load()
        if args.command == "setup" or (args.command in ("start", "chat", "telegram") and not config.brain_ready):
            from pocketagent.setup_wizard import run_setup
            config = run_setup(config)
            if not config.brain_ready or args.command == "setup":
                return
        if args.command == "skills":
            list_skills(Runtime(config))
        elif args.command == "doctor":
            doctor(config)
        else:
            run(config, {"start": "all", "chat": "chat", "telegram": "telegram"}[args.command])
    except KeyboardInterrupt:
        print("\nBye!")
    except Exception as error:
        print(f"\n⚠️ {type(error).__name__}: {error}")
        if getattr(sys, "frozen", False):          # double-clicked .exe: keep the window open
            input("Press Enter to close...")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
