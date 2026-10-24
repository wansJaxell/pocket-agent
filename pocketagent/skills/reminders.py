"""Reminders: the agent messages you when the time comes (Telegram or terminal)."""

import re
from datetime import datetime, timedelta

from pocketagent.tools import ToolContext, tool

_RELATIVE = re.compile(r"^in\s+(\d+)\s*(minute|min|hour|hr|day)s?$", re.IGNORECASE)
_CLOCK = re.compile(r"^(\d{1,2}):(\d{2})$")


def parse_when(when: str, now: datetime | None = None) -> datetime:
    """'in 10 minutes', 'in 2 hours', '18:30' (next occurrence) or '2026-10-25 09:00'."""
    now = now or datetime.now()
    text = when.strip()
    match = _RELATIVE.match(text)
    if match:
        amount, unit = int(match.group(1)), match.group(2).lower()
        step = {"minute": "minutes", "min": "minutes", "hour": "hours", "hr": "hours", "day": "days"}[unit]
        return now + timedelta(**{step: amount})
    match = _CLOCK.match(text)
    if match:
        due = now.replace(hour=int(match.group(1)), minute=int(match.group(2)), second=0, microsecond=0)
        return due if due > now else due + timedelta(days=1)
    try:
        return datetime.fromisoformat(text.replace("T", " "))
    except ValueError:
        raise ValueError(f"cannot understand the time '{when}'. Use 'in 10 minutes', "
                         "'18:30' or '2026-10-25 09:00'.") from None


@tool
def set_reminder(ctx: ToolContext, when: str, text: str) -> str:
    """Remind the user about something at a given time.

    Args:
        when: "in 10 minutes", "in 2 hours", "18:30" or "2026-10-25 09:00" (user's local time)
        text: what to remind the user about
    """
    try:
        due = parse_when(when)
    except ValueError as error:
        return str(error)
    item = ctx.reminders.add(due, text, ctx.chat_id)
    return f"Reminder #{item['id']} set for {due:%d %b %Y %H:%M}."


@tool
def list_reminders(ctx: ToolContext) -> str:
    """Show upcoming reminders."""
    items = sorted(ctx.reminders.all(), key=lambda r: r["due"])
    if not items:
        return "No reminders."
    return "\n".join(f"#{r['id']}: {r['due'].replace('T', ' ')[:16]}: {r['text']}" for r in items)


@tool
def cancel_reminder(ctx: ToolContext, reminder_id: int) -> str:
    """Cancel a reminder.

    Args:
        reminder_id: the number shown by list_reminders
    """
    return (f"Reminder #{reminder_id} cancelled." if ctx.reminders.remove(reminder_id)
            else f"There is no reminder #{reminder_id}.")
