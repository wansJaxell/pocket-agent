"""Changing brains: the agent can hand the conversation to another of the user's AI models."""

from pocketagent.approvals import Action
from pocketagent.tools import ToolContext, tool


@tool
def switch_brain(ctx: ToolContext, name: str = "") -> str:
    """Use another of the user's brains (AI models) from now on: when the user asks for another model, or when you cannot do the task well (e.g. pictures). Without a name, list the brains.

    Args:
        name: part of the brain's name, e.g. "gemini" or "gpt-oss"; empty to see the list
    """
    if ctx.brains is None:
        return "Switching brains is not available here."
    listing = "\n".join(ctx.brains.describe())
    if not name.strip():
        return "The user's brains, the first one answers:\n" + listing
    if ctx.tainted_by:       # a web page or file must not be able to change the user's settings
        ctx.approve(Action("brain", "Switch to another brain", {"brain": name}, scope={}, needs_computer_use=False))
    label = ctx.brains.prefer(name)
    if label is None:
        return f"There is no brain called '{name}'. The brains:\n{listing}"
    return f"Switched: {label} answers from now on, starting with the rest of this answer."
