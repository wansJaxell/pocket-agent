"""Hand work to a specialist: an image, a voice recording, or a long text or program.

The agent writes the prompt; the specialist (set up in the panel) makes the result, which is
saved in the workspace's media folder and shown in the panel or sent on Telegram.
Paid specialists ask for approval every time, like any spending.
"""

from datetime import datetime

from pocketagent.approvals import Action
from pocketagent.media import MediaError
from pocketagent.skills.files import _safe_path
from pocketagent.tools import ToolContext, tool

NOT_SET_UP = ("No {kind} specialist is set up. Tell the user they can choose one in the panel "
              "(Setup → Specialists); some are free.")


def save_media(ctx: ToolContext, kind: str, data: bytes, extension: str) -> str:
    """Save a result in workspace/media and remember it for the answer; returns the workspace path."""
    folder = _safe_path(ctx, "media")
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path, number = folder / f"{kind}-{stamp}{extension}", 1
    while path.exists():
        number += 1
        path = folder / f"{kind}-{stamp}-{number}{extension}"
    path.write_bytes(data)
    relative = path.relative_to(ctx.workspace.resolve()).as_posix()
    ctx.files.append(relative)
    return relative


def _ask_if_paid(ctx: ToolContext, kind: str, params: dict) -> None:
    if ctx.studio.paid(kind):
        ctx.approve(Action(kind, f"Create {'an image' if kind == 'image' else 'audio'} with a paid model",
                           {"service": ctx.studio.describe(kind), **params}, scope={}, classes={"money"},
                           needs_computer_use=False))


@tool
def create_image(ctx: ToolContext, prompt: str, size: str = "1024x1024") -> str:
    """Make an image with the image specialist. Write a detailed prompt in English: subject, style, colours, light, composition.

    Args:
        prompt: the full image description, in English
        size: "1024x1024" (square), "1792x1024" (wide) or "1024x1792" (tall)
    """
    if ctx.studio is None or not ctx.studio.ready("image"):
        return NOT_SET_UP.format(kind="image")
    _ask_if_paid(ctx, "image", {"prompt": prompt, "size": size})
    try:
        data, extension = ctx.studio.image(prompt, size)
    except MediaError as error:
        return f"The image specialist could not make it: {error}"
    path = save_media(ctx, "image", data, extension)
    return f"Image saved as {path} (by {ctx.studio.describe('image')}). The user sees it with your answer."


@tool
def create_speech(ctx: ToolContext, text: str, voice: str = "") -> str:
    """Turn a text into a spoken audio file with the speech specialist.

    Args:
        text: exactly what should be said
        voice: optional voice name; empty for the one chosen in the panel
    """
    if ctx.studio is None or not ctx.studio.ready("speech"):
        return NOT_SET_UP.format(kind="speech")
    _ask_if_paid(ctx, "speech", {"text": text[:200]})
    try:
        data, extension = ctx.studio.speech(text, voice)
    except MediaError as error:
        return f"The speech specialist could not make it: {error}"
    path = save_media(ctx, "speech", data, extension)
    return f"Audio saved as {path} (by {ctx.studio.describe('speech')}). The user gets it with your answer."


@tool(untrusted_output=True)
def ask_specialist(ctx: ToolContext, task: str, save_as: str = "") -> str:
    """Hand a long writing or coding task to the writer specialist (another model) and get its result.

    Args:
        task: a complete, self-contained instruction: the specialist sees nothing else
        save_as: optional file path in the workspace for the result, e.g. "code/app.py" or "docs/report.md"
    """
    if ctx.studio is None or not ctx.studio.ready("writer"):
        return NOT_SET_UP.format(kind="writer")
    try:
        target = _safe_path(ctx, save_as) if save_as.strip() else None
        result = ctx.studio.write(task)
    except PermissionError as error:
        return f"Not saved: {error}."
    except MediaError as error:
        return f"The writer specialist could not do it: {error}"
    if target is None:
        return result
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(result, encoding="utf-8")
    relative = target.relative_to(ctx.workspace.resolve()).as_posix()
    ctx.files.append(relative)
    return f"The specialist ({ctx.studio.describe('writer')}) wrote {len(result)} characters, saved as {relative}:\n\n{result}"
