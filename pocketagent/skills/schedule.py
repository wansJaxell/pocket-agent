"""Scheduled tasks: do something later, once or again and again, and report the result then."""

from pocketagent.approvals import Action
from pocketagent.schedule import ScheduleError, parse_repeat
from pocketagent.skills.reminders import parse_when
from pocketagent.tools import ToolContext, tool


@tool
def schedule_task(ctx: ToolContext, task: str, when: str, repeat: str = "") -> str:
    """Do a task later, once or regularly (e.g. every weekday morning); the result is sent to the user then.

    Args:
        task: a complete instruction, e.g. "Check the weather in Istanbul and send me a short summary"
        when: first time: "in 10 minutes", "08:00" or "2026-11-01 09:00" (user's local time)
        repeat: "" for once, or "hourly", "daily", "weekdays", "weekly", "every 30 minutes", "every 2 hours"
    """
    if ctx.tasks is None:
        return "Scheduled tasks are not available here."
    try:
        start, repeat = parse_when(when), parse_repeat(repeat)
    except (ValueError, ScheduleError) as error:
        return str(error)
    if ctx.tainted_by:       # a web page or file must not be able to plant a standing task
        ctx.approve(Action("schedule", "Schedule a task", {"task": task, "first time": f"{start:%d %b %Y %H:%M}",
                                                            "repeat": repeat or "once"},
                           scope={}, needs_computer_use=False))
    item = ctx.tasks.add(task, start, repeat, ctx.chat_id, ctx.source)
    return (f"Scheduled task #{item['id']} for {start:%d %b %Y %H:%M}" + (f", then {repeat}" if repeat else "")
            + ". The user can see and cancel it in the panel (Safety) or with /tasks on Telegram.")


@tool
def list_tasks(ctx: ToolContext) -> str:
    """Show the scheduled tasks."""
    tasks = ctx.tasks.all() if ctx.tasks else []
    if not tasks:
        return "No scheduled tasks."
    return "\n".join(f"#{t['id']}: next {t['next'].replace('T', ' ')[:16]}, {t['repeat'] or 'once'}: {t['task']}"
                     for t in tasks)


@tool
def cancel_task(ctx: ToolContext, task_id: int) -> str:
    """Cancel a scheduled task.

    Args:
        task_id: the number shown by list_tasks
    """
    removed = ctx.tasks.remove(int(task_id)) if ctx.tasks else False
    return f"Task #{task_id} cancelled." if removed else f"There is no task #{task_id}."
