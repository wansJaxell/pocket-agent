"""Scheduled tasks: "every weekday at 08:00, summarise the weather" and the like (tasks.json).

At the time, the task runs like a message from the user, in the background job queue, and the
answer goes to the chat where it was scheduled. Actions on the computer still ask for approval.
If the computer was off, a missed task runs once when PocketAgent starts, then keeps its rhythm.
"""

import json
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path

MIN_MINUTES = 5          # free model quotas are small: a task every minute would use them up

_SYNONYMS = {"": "", "once": "", "bir kez": "", "bir defa": "", "tek sefer": "",
             "hourly": "hourly", "every hour": "hourly", "her saat": "hourly", "saatlik": "hourly",
             "daily": "daily", "every day": "daily", "her gün": "daily", "hergün": "daily", "günlük": "daily",
             "weekdays": "weekdays", "every weekday": "weekdays", "hafta içi": "weekdays", "hafta ici": "weekdays",
             "iş günleri": "weekdays", "weekly": "weekly", "every week": "weekly", "her hafta": "weekly",
             "haftalık": "weekly"}
_EVERY = re.compile(r"^(?:every|her)\s+(\d+)\s*(minutes?|mins?|dakika(?:da)?|hours?|saat(?:te)?)$")


class ScheduleError(ValueError):
    """A repeat the scheduler does not understand, or one that is too frequent."""


def parse_repeat(text: str) -> str:
    """"" (once), "hourly", "daily", "weekdays", "weekly", "every N minutes" or "every N hours"."""
    key = " ".join((text or "").lower().split())
    if key in _SYNONYMS:
        return _SYNONYMS[key]
    match = _EVERY.match(key)
    if not match:
        raise ScheduleError(f"unknown repeat '{text}': use once, hourly, daily, weekdays, weekly, "
                            "'every 30 minutes' or 'every 2 hours'")
    amount, unit = int(match.group(1)), match.group(2)
    if unit.startswith(("hour", "saat")):
        return "hourly" if amount == 1 else f"every {amount} hours"
    if amount < MIN_MINUTES:
        raise ScheduleError(f"tasks can repeat at most every {MIN_MINUTES} minutes")
    return f"every {amount} minutes"


def _once(moment: datetime, repeat: str) -> datetime:
    if repeat == "hourly":
        return moment + timedelta(hours=1)
    if repeat == "daily":
        return moment + timedelta(days=1)
    if repeat == "weekly":
        return moment + timedelta(days=7)
    if repeat == "weekdays":
        moment += timedelta(days=1)
        while moment.weekday() >= 5:          # Saturday, Sunday
            moment += timedelta(days=1)
        return moment
    amount, unit = repeat.split()[1:]
    return moment + (timedelta(minutes=int(amount)) if unit == "minutes" else timedelta(hours=int(amount)))


def next_run(previous: datetime, repeat: str, now: datetime) -> datetime | None:
    """The first time after now; None for a one-time task."""
    repeat = parse_repeat(repeat)
    if not repeat:
        return None
    moment = _once(previous, repeat)
    while moment <= now:
        moment = _once(moment, repeat)
    return moment


class TaskStore:
    def __init__(self, folder: Path):
        self.path = folder / "tasks.json"
        self._lock = threading.Lock()

    def all(self) -> list[dict]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, tasks: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(tasks, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def add(self, task: str, when: datetime, repeat: str, chat_id: str, source: str) -> dict:
        with self._lock:
            tasks = self.all()
            item = {"id": max((t["id"] for t in tasks), default=0) + 1, "task": task.strip(),
                    "repeat": parse_repeat(repeat), "next": when.isoformat(timespec="seconds"),
                    "chat_id": str(chat_id), "source": source,
                    "created": datetime.now().isoformat(timespec="seconds"), "last_run": ""}
            self._write(tasks + [item])
            return item

    def due(self, now: datetime) -> list[dict]:
        return [t for t in self.all() if datetime.fromisoformat(t["next"]) <= now]

    def advance(self, task_id: int, now: datetime) -> None:
        """Move a task to its next time (a one-time task is finished and removed)."""
        with self._lock:
            tasks, kept = self.all(), []
            for task in tasks:
                if task["id"] == task_id:
                    following = next_run(datetime.fromisoformat(task["next"]), task["repeat"], now)
                    if following is None:
                        continue
                    task.update(next=following.isoformat(timespec="seconds"),
                                last_run=now.isoformat(timespec="seconds"))
                kept.append(task)
            self._write(kept)

    def remove(self, task_id: int) -> bool:
        with self._lock:
            tasks = self.all()
            kept = [t for t in tasks if t["id"] != task_id]
            self._write(kept)
            return len(kept) != len(tasks)
