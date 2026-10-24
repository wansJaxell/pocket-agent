"""First-run setup: finds a brain, tests it, and connects Telegram with as little typing as possible.

What is automatic:
  - finds Ollama / LM Studio running on this computer and lists their models
  - tests the chosen model, and whether it supports native tool calling
  - checks the Telegram token and captures *your* chat as the only allowed owner
What needs you (Telegram rules): creating the bot with @BotFather and pasting its token.
"""

import time

import requests

from pocketagent.config import Config, save
from pocketagent.llm import PROVIDERS, Brain

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"

MODEL_TIPS = """Model tips for local use (download with: ollama pull <name>):
  8 GB graphics card  -> qwen3.5:9b or granite4.2:8b  (fit in the GPU: fast)
  16 GB+ GPU or RAM   -> gpt-oss:20b or qwen3:30b      (mixture-of-experts: bigger, slower if they spill)
Larger dense models (32B) need about 20 GB of graphics memory to run well."""


class ConsoleIO:
    def say(self, text: str = "") -> None:
        print(text)

    def ask(self, prompt: str, default: str = "") -> str:
        suffix = f" [{default}]" if default else ""
        answer = input(f"{prompt}{suffix}: ").strip()
        return answer or default


def detect_local_models(http=requests) -> dict[str, list[str]]:
    """Which local model servers are running, and which models they have."""
    found = {}
    try:
        tags = http.get("http://localhost:11434/api/tags", timeout=2).json()
        found["ollama"] = [m["name"] for m in tags.get("models", [])]
    except Exception:
        pass
    try:
        models = http.get("http://localhost:1234/v1/models", timeout=2).json()
        found["lmstudio"] = [m["id"] for m in models.get("data", [])]
    except Exception:
        pass
    return found


TIME_TOOL = {"type": "function", "function": {
    "name": "get_current_time", "description": "Get the current date and time.",
    "parameters": {"type": "object", "properties": {}, "required": []}}}


def test_brain(config: Config, io, brain_factory=Brain) -> bool:
    """Check the model answers, then check native tool calling (falls back to text tools)."""
    io.say("\nTesting the brain...")
    try:
        brain = brain_factory(config.brain)
        reply = brain.chat([{"role": "user", "content": "Reply with the single word OK."}])
        io.say(f"  ✓ Model answered: {reply.content.strip()[:60]!r}")
    except Exception as error:
        io.say(f"  ✗ Could not reach the model: {type(error).__name__}: {error}")
        return False
    try:
        config.brain.native_tools = True
        reply = brain.chat([{"role": "user", "content": "What time is it now? Use your tool."}], [TIME_TOOL])
        config.brain.native_tools = bool(reply.tool_calls)
    except Exception:
        config.brain.native_tools = False
    io.say("  ✓ Native tool calling works." if config.brain.native_tools else
           "  • No native tool calling: tools will be described in the prompt instead (works, a bit less reliable).")
    return True


def choose_brain(config: Config, io, http=requests) -> None:
    io.say("\n=== Step 1/2: the brain (AI model) ===")
    local = detect_local_models(http)
    options = [(f"{PROVIDERS[p].label}: {model}", p, model) for p, models in local.items() for model in models]
    options += [(PROVIDERS[p].label, p, None) for p in ("nvidia", "openrouter", "groq", "custom")]

    if not local:
        io.say("No local model server found. For a free, private brain install Ollama from https://ollama.com,")
        io.say("then run: ollama pull qwen3.5:9b   and start this setup again. Or pick a free cloud API below.")
    elif not any(local.values()):
        io.say("A local server is running but has no models yet. Example: ollama pull qwen3.5:9b")
    io.say(MODEL_TIPS + "\n")
    for number, (label, _, _) in enumerate(options, 1):
        io.say(f"  {number}) {label}")

    while True:
        choice = io.ask("Choose a number", "1")
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            break
        io.say("Please type one of the numbers above.")
    _, provider_key, model = options[int(choice) - 1]
    provider = PROVIDERS[provider_key]

    config.brain.provider = provider_key
    config.brain.base_url = provider.base_url or io.ask("API base URL (ends with /v1)")
    if provider.needs_key:
        if provider.key_url:
            io.say(f"Get a free API key at {provider.key_url}")
        config.brain.api_key = io.ask("Paste your API key")
    else:
        config.brain.api_key = ""
    config.brain.model = model or io.ask("Model name", provider.suggested_model)


def wait_for_owner(token: str, http=requests, wait_seconds: int = 180) -> int | None:
    """Return the chat id of the first person who messages the bot from now on."""
    url = TELEGRAM_API.format(token=token, method="getUpdates")
    old = http.post(url, json={"offset": -1, "timeout": 0}, timeout=15).json().get("result", [])
    offset = old[-1]["update_id"] + 1 if old else None      # skip messages sent before setup
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        updates = http.post(url, json={"offset": offset, "timeout": 20}, timeout=30).json().get("result", [])
        for update in updates:
            offset = update["update_id"] + 1
            chat = update.get("message", {}).get("chat", {})
            if chat.get("id"):
                http.post(url, json={"offset": offset, "timeout": 0}, timeout=15)   # mark as read
                return chat["id"]
    return None


def setup_telegram(config: Config, io, http=requests) -> None:
    io.say("\n=== Step 2/2: Telegram (talk to your agent from any phone) ===")
    if io.ask("Connect Telegram now? (y/n)", "y").lower() not in ("y", "yes", "e", "evet"):
        io.say("Skipped. You can run `pocketagent setup` later.")
        return
    io.say("1. In Telegram, open @BotFather and send /newbot")
    io.say("2. Choose a name, then a username ending in 'bot'")
    io.say("3. Copy the token it sends you (looks like 123456789:ABCdef...)")
    for _ in range(3):
        token = io.ask("Paste the bot token")
        try:
            me = http.get(TELEGRAM_API.format(token=token, method="getMe"), timeout=15).json()
        except requests.RequestException as error:
            io.say(f"  ✗ Could not reach Telegram: {error}")
            continue
        if me.get("ok"):
            break
        io.say("  ✗ Telegram did not accept this token. Copy it again from @BotFather.")
    else:
        io.say("Telegram skipped for now.")
        return

    username = me["result"]["username"]
    io.say(f"  ✓ Bot @{username} found.")
    io.say(f"Now open https://t.me/{username} on your phone and press START. Waiting up to 3 minutes...")
    owner = wait_for_owner(token, http)
    if owner is None:
        io.say("  ✗ No message arrived. Run `pocketagent setup` again when you are ready.")
        return
    config.telegram.token, config.telegram.owner_chat_id = token, owner
    http.post(TELEGRAM_API.format(token=token, method="sendMessage"), timeout=15, json={
        "chat_id": owner, "text": f"✅ {config.agent_name} is connected. Only this chat can talk to me."})
    io.say("  ✓ Connected. Only your chat can use the agent.")


def run_setup(config: Config, io=None, http=requests, brain_factory=Brain) -> Config:
    io = io or ConsoleIO()
    io.say("Welcome to PocketAgent setup. This takes about 2 minutes.")
    for _ in range(3):
        choose_brain(config, io, http)
        if test_brain(config, io, brain_factory):
            break
        io.say("Let's try again (check that the model server is running and the key is correct).")
    else:
        io.say("Setup stopped: no working brain yet.")
        return config
    save(config)
    setup_telegram(config, io, http)
    path = save(config)
    io.say(f"\nAll set. Settings saved in {path}")
    return config
