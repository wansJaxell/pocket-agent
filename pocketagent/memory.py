"""Small JSON stores: conversation history, long-term notes and reminders.

Plain JSON files keep everything local, readable and easy to back up.
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
