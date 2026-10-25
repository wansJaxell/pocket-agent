"""Web pages on the computer, each step approved by the user.

open_in_browser shows a page in the user's own browser. The browser_* tools drive the agent's own
browser window (Edge or Chrome with a separate profile, see browser_control.py): it sees pages as
they look after their JavaScript ran, and can click and type.

Hidden from the model until the user turns computer use on. Going to a site is approved per site.
Clicks and typing come after reading a page, so they are always asked again. Passwords are never
typed by the agent: the user types them in the open window.
"""

import re
import webbrowser
from urllib.parse import urlparse

from pocketagent.approvals import Action
from pocketagent.browser_control import BrowserError
from pocketagent.skills.specialists import save_media
from pocketagent.tools import ToolContext, tool

MAX_PAGE_TEXT = 6000
_FLAGS = {"money": r"satın al|öde|ödeme|sipariş|sepet|rezervasyon|buy|pay|checkout|purchase|order|book now",
          "delete": r"\bsil\b|kaldır|delete|remove|erase",
          "message": r"gönder|paylaş|yayınla|send|post|publish|tweet|reply",
          "secrets": r"şifre|parola|password|passcode|pin\b"}


def _site(url: str) -> str:
    parts = urlparse(url)
    return f"{parts.scheme}://{parts.netloc.lower()}"


def _flags(*texts: str) -> set:
    text = " ".join(texts).lower()
    return {name for name, pattern in _FLAGS.items() if re.search(pattern, text)}


def _element(e: dict) -> str:
    kind = f"{e['tag']}/{e['type']}" if e.get("tag") == "input" and e.get("type") else e.get("tag", "?")
    return f"{kind}: {e.get('label') or '(no label)'}"


def _summary(page: dict) -> str:
    text = page.get("text", "")
    lines = [f"{page.get('title') or '(no title)'} - {page.get('url', '')}", "",
             text[:MAX_PAGE_TEXT] + (f"\n...[{len(text) - MAX_PAGE_TEXT} more characters]" if len(text) > MAX_PAGE_TEXT else "")]
    elements = page.get("elements") or []
    if elements:
        lines += ["", "Elements you can click or type into (use the number):"]
        lines += [f"[{e['id']}] {_element(e)}" for e in elements[:80]]
    return "\n".join(lines)


@tool(os_access=True)
def open_in_browser(ctx: ToolContext, url: str) -> str:
    """Show a web page to the user in their own browser (with their approval). You cannot read pages opened this way: to read a page, use browser_go.

    Args:
        url: full address starting with http:// or https://
    """
    parts = urlparse(url.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return "Only http:// and https:// addresses can be opened."
    ctx.approve(Action("browser", "Open a page in your browser", {"url": url.strip()}, scope={"site": _site(url.strip())}))
    webbrowser.open(url.strip())
    return f"Opened {url.strip()} in the user's browser."


@tool(os_access=True, untrusted_output=True)
def browser_go(ctx: ToolContext, url: str) -> str:
    """Open a page in the agent's own browser window and read it as it looks after loading (prices, timetables, search results).

    Args:
        url: full address starting with http:// or https://
    """
    url = url.strip()
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return "Only http:// and https:// addresses can be opened."
    ctx.approve(Action("browser_go", "Open a page in the agent's browser window", {"url": url},
                       scope={"site": _site(url)}))
    try:
        return _summary(ctx.browser.goto(url))
    except BrowserError as error:
        return f"The browser could not open the page: {error}"


@tool(os_access=True, untrusted_output=True)
def browser_read(ctx: ToolContext) -> str:
    """Read the page that is open in the agent's browser window again (text and numbered elements)."""
    try:
        return _summary(ctx.browser.read())
    except BrowserError as error:
        return str(error)


@tool(os_access=True, untrusted_output=True)
def browser_click(ctx: ToolContext, element: int) -> str:
    """Click an element of the open page (the user approves each click), then read the page.

    Args:
        element: the element's number from the page listing
    """
    try:
        info = ctx.browser.describe(int(element))
    except BrowserError as error:
        return str(error)
    ctx.approve(Action("browser_click", "Click in the agent's browser window",
                       {"page": info.get("page", ""), "element": _element(info)},
                       scope={"site": _site(info.get("page", "")), "element": info.get("label", "")},
                       classes=_flags(info.get("label", ""), info.get("page", ""))))
    try:
        ctx.browser.click(int(element))
        return _summary(ctx.browser.read())
    except BrowserError as error:
        return f"The click did not work: {error}"


@tool(os_access=True, untrusted_output=True)
def browser_type(ctx: ToolContext, element: int, text: str, submit: bool = False) -> str:
    """Type into a field of the open page (the user approves it), optionally pressing Enter, then read the page.

    Args:
        element: the field's number from the page listing
        text: what to type
        submit: true to press Enter afterwards (e.g. to search)
    """
    try:
        info = ctx.browser.describe(int(element))
    except BrowserError as error:
        return str(error)
    if info.get("type") == "password":
        return ("This is a password field: the user types passwords themselves in the open browser window. "
                "Ask them to do it, then continue.")
    ctx.approve(Action("browser_type", "Type in the agent's browser window",
                       {"page": info.get("page", ""), "element": _element(info), "text": text[:200]},
                       scope={"site": _site(info.get("page", "")), "element": info.get("label", ""), "text": text},
                       classes=_flags(info.get("label", ""))))
    try:
        ctx.browser.type(int(element), text, bool(submit))
        return _summary(ctx.browser.read())
    except BrowserError as error:
        return f"Typing did not work: {error}"


@tool(os_access=True, untrusted_output=True)
def browser_scroll(ctx: ToolContext, direction: str = "down") -> str:
    """Scroll the open page down or up, then read it.

    Args:
        direction: "down" or "up"
    """
    try:
        ctx.browser.scroll(direction)
        return _summary(ctx.browser.read())
    except BrowserError as error:
        return str(error)


@tool(os_access=True)
def browser_screenshot(ctx: ToolContext) -> str:
    """Take a picture of the page open in the agent's browser window (not of the user's screen)."""
    try:
        data = ctx.browser.screenshot()
    except BrowserError as error:
        return str(error)
    path = save_media(ctx, "browser", data, ".png")
    return f"Page picture saved as {path}. Use look_at_image on it to see it."
