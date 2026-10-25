"""Small JSON stores: identity, conversation history, notes, decisions and reminders.

Plain JSON files keep everything local, readable and easy to back up. They belong to the agent,
not to the brain: switch to another model and it still knows its name, the user and past decisions.
"""

import json
import threading
from datetime import datetime
from pathlib import Path


class _JsonFile:
    def __init__(self, path: Path, empty):
        self.path, self._empty, self._lock = path, empty, threading.Lock()

    def read(self):
        if not self.path.exists():
            return self._empty()
        return json.loads(self.path.read_text(encoding="utf-8"))

    def write(self, data) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)   # write-then-rename: a crash never leaves a half-written file


class ConversationStore:
    """Recent messages per chat, so the agent remembers the conversation."""

    def __init__(self, folder: Path, keep: int = 20):
        self.file = _JsonFile(folder / "conversations.json", dict)
        self.keep = keep

    def get(self, chat_id: str) -> list[dict]:
        return self.file.read().get(str(chat_id), [])

    def add(self, chat_id: str, role: str, content: str) -> None:
        with self.file._lock:
            data = self.file.read()
            messages = data.setdefault(str(chat_id), [])
            messages.append({"role": role, "content": content})
            data[str(chat_id)] = messages[-self.keep:]
            self.file.write(data)

    def reset(self, chat_id: str) -> None:
        with self.file._lock:
            data = self.file.read()
            data.pop(str(chat_id), None)
            self.file.write(data)

    def drop_last_exchange(self, chat_id: str) -> str:
        """Forget the last question and its answer (to ask again); returns the question, or ""."""
        with self.file._lock:
            data = self.file.read()
            messages = data.get(str(chat_id), [])
            if len(messages) < 2 or messages[-1]["role"] != "assistant" or messages[-2]["role"] != "user":
                return ""
            data[str(chat_id)] = messages[:-2]
            self.file.write(data)
            return messages[-2]["content"]


class NoteStore:
    """Long-term facts the agent was asked to remember ("my daughter's name is ...")."""

    def __init__(self, folder: Path):
        self.file = _JsonFile(folder / "notes.json", list)

    def all(self) -> list[dict]:
        return self.file.read()

    def add(self, text: str) -> dict:
        with self.file._lock:
            notes = self.file.read()
            note = {"id": max((n["id"] for n in notes), default=0) + 1, "text": text.strip(),
                    "created": datetime.now().isoformat(timespec="minutes")}
            notes.append(note)
            self.file.write(notes)
            return note

    def remove(self, note_id: int) -> bool:
        with self.file._lock:
            notes = self.file.read()
            kept = [n for n in notes if n["id"] != note_id]
            self.file.write(kept)
            return len(kept) != len(notes)


class ReminderStore:
    def __init__(self, folder: Path):
        self.file = _JsonFile(folder / "reminders.json", list)

    def all(self) -> list[dict]:
        return self.file.read()

    def add(self, due: datetime, text: str, chat_id: str) -> dict:
        with self.file._lock:
            items = self.file.read()
            item = {"id": max((r["id"] for r in items), default=0) + 1, "due": due.isoformat(timespec="seconds"),
                    "text": text.strip(), "chat_id": str(chat_id)}
            items.append(item)
            self.file.write(items)
            return item

    def remove(self, reminder_id: int) -> bool:
        with self.file._lock:
            items = self.file.read()
            kept = [r for r in items if r["id"] != reminder_id]
            self.file.write(kept)
            return len(kept) != len(items)

    def pop_due(self, now: datetime | None = None) -> list[dict]:
        """Remove and return every reminder whose time has come."""
        now = now or datetime.now()
        with self.file._lock:
            items = self.file.read()
            due = [r for r in items if datetime.fromisoformat(r["due"]) <= now]
            if due:
                self.file.write([r for r in items if r not in due])
            return due


class IdentityStore:
    """Who the agent is: its name and the personality the user gave it (identity.json)."""

    def __init__(self, folder: Path, default_name: str = "PocketAgent"):
        self.file = _JsonFile(folder / "identity.json", dict)
        self.default_name = default_name

    def get(self) -> dict:
        data = self.file.read()
        return {"name": data.get("name") or self.default_name, "personality": data.get("personality", "")}

    def set(self, name: str, personality: str = "") -> dict:
        with self.file._lock:
            data = {"name": name.strip(), "personality": personality.strip(),
                    "updated": datetime.now().isoformat(timespec="seconds")}
            self.file.write(data)
        return self.get()


class DecisionLog:
    """Important decisions made with the user, one JSON object per line (decisions.jsonl).

    Append-only: a decision is never rewritten, so the log also shows how plans changed over time.
    """

    def __init__(self, folder: Path):
        self.path = folder / "decisions.jsonl"
        self._lock = threading.Lock()

    def add(self, decision: str, reason: str = "", source: str = "agent") -> dict:
        with self._lock:
            entry = {"id": len(self.all()) + 1, "time": datetime.now().isoformat(timespec="minutes"),
                     "decision": decision.strip(), "reason": reason.strip(), "source": source}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return entry

    def all(self) -> list[dict]:
        if not self.path.exists():
            return []
        entries = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:      # a half-written last line after a crash
                continue
        return entries

    def recent(self, limit: int = 15) -> list[dict]:
        return self.all()[-limit:]

    def search(self, keyword: str) -> list[dict]:
        keyword = keyword.lower()
        return [d for d in self.all() if keyword in (d["decision"] + " " + d.get("reason", "")).lower()]
