"""Long-term memory: facts the user asks the agent to remember."""

from pocketagent.tools import ToolContext, tool


@tool
def remember(ctx: ToolContext, fact: str) -> str:
    """Save a fact about the user or their work for future conversations.

    Args:
        fact: one short sentence, e.g. "The user's daughter is called Elif"
    """
    note = ctx.memory.add(fact)
    return f"Saved as note #{note['id']}."


@tool
def recall(ctx: ToolContext, keyword: str = "") -> str:
    """List saved notes, optionally only those containing a keyword.

    Args:
        keyword: word to filter by; empty for all notes
    """
    notes = [n for n in ctx.memory.all() if keyword.lower() in n["text"].lower()]
    if not notes:
        return "No matching notes."
    return "\n".join(f"#{n['id']}: {n['text']}" for n in notes)


@tool
def forget(ctx: ToolContext, note_id: int) -> str:
    """Delete a saved note.

    Args:
        note_id: the number shown by recall
    """
    return f"Note #{note_id} deleted." if ctx.memory.remove(note_id) else f"There is no note #{note_id}."
