"""Decision log: important choices made with the user, kept across conversations and brains."""

from pocketagent.tools import ToolContext, tool


@tool
def record_decision(ctx: ToolContext, decision: str, reason: str = "") -> str:
    """Log an important decision made with the user (a plan, a rule, a preference), so it is kept for the future.

    Args:
        decision: one short sentence, e.g. "Weekly report every Monday at 9:00"
        reason: why it was decided, if known
    """
    entry = ctx.decisions.add(decision, reason)
    return f"Logged decision #{entry['id']}."


@tool
def list_decisions(ctx: ToolContext, keyword: str = "") -> str:
    """List logged decisions, optionally only those containing a keyword.

    Args:
        keyword: word to filter by; empty for the most recent decisions
    """
    entries = ctx.decisions.search(keyword) if keyword else ctx.decisions.recent(30)
    if not entries:
        return "No matching decisions."
    return "\n".join(f"#{d['id']} {d['time'][:10]}: {d['decision']}" + (f" ({d['reason']})" if d.get("reason") else "")
                     for d in entries)
