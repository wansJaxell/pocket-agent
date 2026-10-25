"""The approval engine: nothing touches the computer without the user's yes.

  - Computer use is off by default (safe mode: chat only). The user turns it on in the panel.
  - An approval opens a NARROW rule, not a category: the action kind plus its exact scope
    (for a command: the exact command and folder; for the browser: the site). A new folder,
    recipient or amount does not match, so it is asked again.
  - Some classes ALWAYS ask and can never become a rule: spending money, deleting files,
    sending a message to someone, passwords and keys, and any action that comes after the
    agent read untrusted content (a web page, a file, command output) in the same turn:
    instructions hidden in that content must not be able to trigger anything on their own.
  - There is deliberately no ceiling: an approved rule works as often as it is needed.
  - Stop (Telegram /dur, the panel's STOP button) denies every waiting request, ends running
    processes and cancels the interrupted turn at once.
  - Every decision is written to the audit log.
"""

import itertools
import json
import os
import re
import signal
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

ALWAYS_ASK = frozenset({"money", "delete", "message", "secrets", "untrusted"})


class Refused(Exception):
    """The action was not allowed (denied, no answer, safe mode)."""


class Stopped(Exception):
    """The user pressed stop: the current turn ends now."""


@dataclass
class Action:
    kind: str                       # "shell", "browser", ...
    summary: str                    # one line for the user
    params: dict                    # everything the user should see before saying yes
    scope: dict                     # what a saved rule must match exactly
    classes: set = field(default_factory=set)   # e.g. {"delete"}: see ALWAYS_ASK
    needs_computer_use: bool = True  # False: not an action on the computer (e.g. paying for an image)


_PATTERNS = {
    "delete": r"\bformat(?![-\w])|\b(rm|rmdir|rd|del|erase|unlink|shred|srm|sdelete|wipe|diskpart|mkfs\S*|truncate|"
              r"remove-item|ri|clear-content|clear-recyclebin|remove-\w+)\b|git\s+(clean|reset\s+--hard)|"
              r"\s-delete\b|cipher\s+/w|vssadmin\s+delete|wevtutil\s+cl|\bdd\s+if=",
    "secrets": r"passw|credential|cmdkey|ssh-keygen|\.ssh\b|id_rsa|id_ed25519|\bgpg\b|keychain|keyring|certutil|"
               r"secret|token|api[_-]?key|private.?key|\bvault\b|bitlocker|manage-bde|net\s+user|"
               r"securestring|get-credential|\.env\b|lsass|mimikatz|security\s+(find|add|delete)-",
    "message": r"send-mailmessage|sendmail|\bmail\s+-s|\bsmtp|api\.telegram\.org|sendmessage|slack\.com/api|"
               r"discord(app)?\.com/api/webhooks|twilio|whatsapp|outlook\.application",
    "money": r"\b(pay|payment|payments|purchase|checkout|charges?|buy|stripe|paypal|iyzico|wallet|bitcoin|"
             r"transfer|invoice)\b",
}


def classify_command(command: str) -> set[str]:
    """Best-effort: which always-ask classes a shell command belongs to.

    Even an unclassified command needs approval; classification only stops it becoming a rule.
    """
    text = command.lower()
    return {name for name, pattern in _PATTERNS.items() if re.search(pattern, text)}


def kill_tree(process) -> None:
    """End a process and everything it started."""
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True, timeout=15)
        else:
            os.killpg(process.pid, signal.SIGKILL)     # started with start_new_session=True
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        process.kill()
    except OSError:
        pass


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class RuleStore:
    """Saved approvals (approval_rules.json). Each one matches one kind + one exact scope."""

    def __init__(self, folder: Path):
        self.path = folder / "approval_rules.json"
        self._lock = threading.Lock()

    def all(self) -> list[dict]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, rules: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(rules, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def match(self, action: Action) -> dict | None:
        return next((r for r in self.all() if r["kind"] == action.kind and r["scope"] == action.scope), None)

    def add(self, action: Action) -> dict:
        with self._lock:
            rules = self.all()
            rule = {"id": max((r["id"] for r in rules), default=0) + 1, "kind": action.kind,
                    "scope": action.scope, "summary": action.summary, "created": _now()}
            self._write(rules + [rule])
            return rule

    def remove(self, rule_id: int) -> bool:
        with self._lock:
            rules = self.all()
            kept = [r for r in rules if r["id"] != rule_id]
            self._write(kept)
            return len(kept) != len(rules)


def _short(value, limit: int = 300):
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "…"
    if isinstance(value, dict):
        return {k: _short(v, limit) for k, v in value.items()}
    return value


def tail_lines(path: Path, limit: int, block: int = 64 * 1024) -> list[str]:
    """The last `limit` lines of a file, read from its end: the panel asks every two seconds."""
    with open(path, "rb") as f:
        position = f.seek(0, os.SEEK_END)
        data = b""
        while position > 0 and data.count(b"\n") <= limit:
            step = min(block, position)
            position -= step
            f.seek(position)
            data = f.read(step) + data
    # the first line may be cut in the middle (even inside a character): it is past the limit then
    return data.decode("utf-8", errors="replace").splitlines()[-limit:]


class AuditLog:
    """Everything the agent did and every decision, one JSON object per line (audit.jsonl)."""

    def __init__(self, folder: Path, echo: bool = False):
        self.path = folder / "audit.jsonl"
        self.echo = echo              # also print each entry in the (visible) PocketAgent window
        self._lock = threading.Lock()

    def write(self, event: str, **details) -> dict:
        entry = {"time": _now(), "event": event, **_short(details)}
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        if self.echo:
            shown = json.dumps(_short(details, 120), ensure_ascii=False, default=str)
            print(f"[{entry['time'][11:]}] {event}: {shown[:300]}")
        return entry

    def recent(self, limit: int = 50) -> list[dict]:
        if not self.path.exists():
            return []
        entries = []
        for line in tail_lines(self.path, limit):
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries


@dataclass
class Pending:
    id: str
    action: Action
    classes: list
    tainted: list               # untrusted content read earlier in the turn
    source: str                 # panel, telegram, terminal
    can_remember: bool
    created: str = field(default_factory=_now)
    approved: bool = False
    remember: bool = False
    by: str = ""
    event: threading.Event = field(default_factory=threading.Event, repr=False)

    def as_dict(self) -> dict:
        return {"id": self.id, "kind": self.action.kind, "summary": self.action.summary,
                "params": self.action.params, "classes": self.classes, "tainted": self.tainted,
                "source": self.source, "can_remember": self.can_remember, "created": self.created}


class ApprovalEngine:
    def __init__(self, rules: RuleStore, audit: AuditLog, enabled: Callable[[], bool], timeout: float = 600):
        self.rules, self.audit, self.enabled, self.timeout = rules, audit, enabled, timeout
        self.pending: dict[str, Pending] = {}
        self.notifiers: list[Callable[[Pending], None]] = []      # show a new request (panel, Telegram, ...)
        self.resolved: list[Callable[[Pending], None]] = []       # a request was answered or ended
        self.generation = 0          # bumped by stop: turns started before it may not continue
        self._processes: set = set()
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    # ---------- stop ----------
    def check(self, generation: int | None) -> None:
        if generation is not None and generation != self.generation:
            raise Stopped("stopped by the user")

    def track(self, process) -> None:
        with self._lock:
            self._processes.add(process)

    def untrack(self, process) -> None:
        with self._lock:
            self._processes.discard(process)

    def stop_everything(self, by: str) -> dict:
        with self._lock:
            self.generation += 1
            waiting, processes = list(self.pending.values()), list(self._processes)
            self._processes.clear()
        for pending in waiting:
            pending.approved, pending.by = False, f"stop ({by})"
            pending.event.set()
        for process in processes:
            kill_tree(process)
        summary = {"approvals": len(waiting), "processes": len(processes)}
        self.audit.write("stop", by=by, **summary)
        return summary

    # ---------- asking ----------
    def _new_pending(self, action: Action, classes: set, tainted: list, source: str) -> Pending:
        return Pending(str(next(self._ids)), action, sorted(classes), list(tainted), source,
                       can_remember=not (set(classes) & ALWAYS_ASK))

    def _log(self, action: Action, decision: str, **details) -> None:
        self.audit.write("approval", kind=action.kind, summary=action.summary, params=action.params,
                         decision=decision, **details)

    def request(self, action: Action, tainted=(), source: str = "", generation: int | None = None) -> str:
        """Block until the user decides. Returns how it was allowed; raises Refused or Stopped."""
        self.check(generation)
        if action.needs_computer_use and not self.enabled():
            self._log(action, "blocked", source=source)
            raise Refused("computer use is off (safe mode); the user can turn it on in the panel")
        classes = set(action.classes) | ({"untrusted"} if tainted else set())
        if not classes & ALWAYS_ASK:
            rule = self.rules.match(action)
            if rule:
                self._log(action, "rule", rule=rule["id"], source=source)
                return f"rule #{rule['id']}"

        pending = self._new_pending(action, classes, list(tainted), source)
        with self._lock:
            self.pending[pending.id] = pending
        for notify in list(self.notifiers):
            try:
                notify(pending)
            except Exception as error:      # one broken channel must not block the others
                self.audit.write("notify_failed", error=f"{type(error).__name__}: {error}")
        answered = pending.event.wait(self.timeout)
        with self._lock:
            self.pending.pop(pending.id, None)
        for listener in list(self.resolved):
            try:
                listener(pending)
            except Exception:
                pass
        details = {"source": source, "classes": pending.classes, "tainted": pending.tainted, "by": pending.by}
        if generation is not None and generation != self.generation:
            self._log(action, "stopped", **details)
            raise Stopped("stopped by the user")
        if not answered:
            self._log(action, "timeout", **details)
            raise Refused("no answer in time")
        if not pending.approved:
            self._log(action, "denied", **details)
            raise Refused("the user said no")
        rule = self.rules.add(action) if pending.remember and pending.can_remember else None
        self._log(action, "approved", rule=rule and rule["id"], **details)
        return "approved"

    def answer(self, pending_id: str, approve: bool, remember: bool = False, by: str = "panel") -> bool:
        """The user's answer; False if the request is no longer waiting."""
        with self._lock:
            pending = self.pending.get(str(pending_id))
            if pending is None or pending.event.is_set():
                return False
            pending.approved, pending.remember, pending.by = bool(approve), bool(remember), by
            pending.event.set()
        return True

    def waiting(self) -> list[dict]:
        with self._lock:
            return [p.as_dict() for p in self.pending.values() if not p.event.is_set()]
