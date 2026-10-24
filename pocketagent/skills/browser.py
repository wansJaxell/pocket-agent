"""Open web pages in the user's own browser, each site approved by the user first.

Hidden from the model until the user turns computer use on. An approval can be saved as a rule
for one site (scheme + host); a new site is asked again. To *read* a page, the agent uses
fetch_webpage instead, which never touches the user's browser or its logins.
"""

import webbrowser
from urllib.parse import urlparse

from pocketagent.approvals import Action
from pocketagent.tools import ToolContext, tool


@tool(os_access=True)
def open_in_browser(ctx: ToolContext, url: str) -> str:
    """Open a web page in the user's own browser (with the user's approval for that site).

    Args:
        url: full address starting with http:// or https://
    """
    parts = urlparse(url.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return "Only http:// and https:// addresses can be opened."
    site = f"{parts.scheme}://{parts.netloc.lower()}"
    ctx.approve(Action("browser", "Open a page in your browser", {"url": url.strip()}, scope={"site": site}))
    webbrowser.open(url.strip())
    return f"Opened {url.strip()} in the user's browser."
