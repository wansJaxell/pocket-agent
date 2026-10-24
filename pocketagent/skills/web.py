"""Read web pages and search the web (no API key needed)."""

import html
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse

import requests

from pocketagent.tools import tool

HEADERS = {"User-Agent": "Mozilla/5.0 (PocketAgent; +https://github.com/wansjaxell/pocket-agent)"}
MAX_BYTES = 2_000_000
MAX_TEXT = 8000


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head"}

    def __init__(self):
        super().__init__()
        self.parts, self._skipping = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skipping += 1
        elif tag in {"p", "br", "li", "h1", "h2", "h3", "tr", "div"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skipping:
            self._skipping -= 1

    def handle_data(self, data):
        if not self._skipping:
            self.parts.append(data)


def html_to_text(page: str) -> str:
    parser = _TextExtractor()
    parser.feed(page)
    text = "".join(parser.parts)
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


@tool(untrusted_output=True)
def fetch_webpage(url: str) -> str:
    """Download a web page and return its readable text.

    Args:
        url: full address starting with http:// or https://
    """
    if urlparse(url).scheme not in ("http", "https"):
        return "Only http:// and https:// addresses are allowed."
    try:
        response = requests.get(url, headers=HEADERS, timeout=15, stream=True)
        content = response.raw.read(MAX_BYTES, decode_content=True)
    except requests.RequestException as error:
        return f"Could not open {url}: {error}"
    if response.status_code >= 400:
        return f"{url} answered with HTTP {response.status_code}."
    page = content.decode(response.encoding or "utf-8", errors="replace")
    text = html_to_text(page) if "html" in response.headers.get("Content-Type", "html") else page
    return text[:MAX_TEXT] + ("\n...[page cut]" if len(text) > MAX_TEXT else "")


_RESULT = re.compile(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
                     r'class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL)


def _clean(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def parse_search_results(page: str, limit: int = 5) -> list[dict]:
    results = []
    for href, title, snippet in _RESULT.findall(page):
        if href.startswith("//duckduckgo.com/l/"):   # DuckDuckGo wraps links in a redirect
            href = unquote(parse_qs(urlparse(href).query).get("uddg", [href])[0])
        results.append({"title": _clean(title), "url": href, "snippet": _clean(snippet)})
        if len(results) >= limit:
            break
    return results


@tool(untrusted_output=True)
def web_search(query: str) -> str:
    """Search the web and return the top results (title, link, short text).

    Args:
        query: what to search for
    """
    try:
        response = requests.post("https://html.duckduckgo.com/html/", data={"q": query},
                                 headers=HEADERS, timeout=15)
        response.raise_for_status()
    except requests.RequestException as error:
        return f"Search failed: {error}"
    results = parse_search_results(response.text)
    if not results:
        return "No results found (the search page may have changed or blocked the request)."
    return "\n\n".join(f"{r['title']}\n{r['url']}\n{r['snippet']}" for r in results)
