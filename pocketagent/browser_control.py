"""The agent's own browser window: Edge (or Chrome) driven over its DevTools connection.

It reads pages the way you see them, after their JavaScript ran, and can click and type.
  - a visible window, with a separate PocketAgent profile: none of your own logins or passwords
  - started on first use; the STOP button closes it
  - the agent never types into password fields: you log in yourself in the open window
Only the standard library: the DevTools connection is a WebSocket, written out here.
"""

import base64
import hashlib
import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"       # fixed by the WebSocket standard (RFC 6455)
CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]

PAGE_JS = ("({title: document.title, url: location.href, "
           "text: (document.body ? document.body.innerText : '').slice(0, 20000)})")
SETTLE_JS = "document.body ? document.body.innerText.length : 0"
ELEMENTS_JS = r"""(() => {
  document.querySelectorAll('[data-pa-id]').forEach(e => e.removeAttribute('data-pa-id'));
  const items = [];
  const found = document.querySelectorAll('a[href], button, input, select, textarea, [role=button], [role=link], [role=tab], [role=option], summary');
  for (const e of found) {
    const r = e.getBoundingClientRect();
    if (r.width < 2 || r.height < 2 || e.disabled || e.type === 'hidden') continue;
    if (getComputedStyle(e).visibility === 'hidden') continue;
    items.push(e);
    if (items.length >= 150) break;
  }
  return items.map((e, i) => {
    e.setAttribute('data-pa-id', i + 1);
    const label = (e.innerText || e.value || e.placeholder || e.getAttribute('aria-label') || e.title || e.name || '')
      .trim().replace(/\s+/g, ' ').slice(0, 80);
    return {id: i + 1, tag: e.tagName.toLowerCase(), type: e.type || '', label};
  });
})()"""
LOCATE_JS = r"""(n => {
  const e = document.querySelector('[data-pa-id="' + n + '"]');
  if (!e) return null;
  e.scrollIntoView({block: 'center', inline: 'center'});
  const r = e.getBoundingClientRect();
  const label = (e.innerText || e.value || e.placeholder || e.getAttribute('aria-label') || e.title || e.name || '')
    .trim().replace(/\s+/g, ' ').slice(0, 80);
  return {x: r.left + r.width / 2, y: r.top + r.height / 2, tag: e.tagName.toLowerCase(), type: e.type || '',
          label, page: location.href};
})"""
FOCUS_JS = "(n => { const e = document.querySelector('[data-pa-id=\"' + n + '\"]'); if (!e) return false; " \
           "e.focus(); if (e.select) e.select(); return true; })"


class BrowserError(Exception):
    """The browser could not be started, or did not do what was asked."""


def accept_key(key: str) -> str:
    return base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()


def find_browser() -> str | None:
    for path in CANDIDATES:
        if path and os.path.isfile(path):
            return path
    for name in ("msedge", "microsoft-edge", "google-chrome", "chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


class WebSocket:
    """A minimal WebSocket client (text frames, ping/pong) for the browser on 127.0.0.1."""

    def __init__(self, url: str, timeout: float = 30):
        parsed = urlparse(url)
        self.sock = socket.create_connection((parsed.hostname, parsed.port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {parsed.path} HTTP/1.1\r\nHost: {parsed.hostname}:{parsed.port}\r\n"
                           "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        self._buffer = b""
        while b"\r\n\r\n" not in self._buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise BrowserError("the browser closed the connection")
            self._buffer += chunk
        head, self._buffer = self._buffer.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n")[0] or accept_key(key).encode() not in head:
            raise BrowserError("the browser refused the connection")

    def _read(self, size: int) -> bytes:
        while len(self._buffer) < size:
            chunk = self.sock.recv(max(65536, size - len(self._buffer)))
            if not chunk:
                raise BrowserError("the browser closed the connection")
            self._buffer += chunk
        data, self._buffer = self._buffer[:size], self._buffer[size:]
        return data

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        header = bytearray([0x80 | opcode])
        if len(payload) < 126:
            header.append(0x80 | len(payload))
        elif len(payload) < 65536:
            header += bytes([0x80 | 126]) + len(payload).to_bytes(2, "big")
        else:
            header += bytes([0x80 | 127]) + len(payload).to_bytes(8, "big")
        mask = os.urandom(4)                       # clients must mask what they send
        header += mask
        self.sock.sendall(bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def send(self, text: str) -> None:
        self._send_frame(0x1, text.encode("utf-8"))

    def recv(self) -> str:
        message = bytearray()
        while True:
            first, second = self._read(2)
            opcode, length = first & 0x0F, second & 0x7F
            if length == 126:
                length = int.from_bytes(self._read(2), "big")
            elif length == 127:
                length = int.from_bytes(self._read(8), "big")
            mask = self._read(4) if second & 0x80 else b""
            payload = self._read(length)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x8:
                raise BrowserError("the browser closed the connection")
            if opcode == 0x9:                       # ping: answer with pong
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            message += payload
            if first & 0x80:
                return message.decode("utf-8", errors="replace")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class Connection:
    """DevTools commands over the WebSocket: send {id, method, params}, wait for the same id."""

    def __init__(self, websocket: WebSocket):
        self.ws, self._id = websocket, 0

    def command(self, method: str, params: dict | None = None, timeout: float = 30) -> dict:
        self._id += 1
        ident = self._id
        self.ws.send(json.dumps({"id": ident, "method": method, "params": params or {}}))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            message = json.loads(self.ws.recv())
            if message.get("id") == ident:
                if "error" in message:
                    raise BrowserError(message["error"].get("message", "the browser refused"))
                return message.get("result", {})
        raise BrowserError("the browser did not answer in time")


class BrowserSession:
    """What the agent can do in the page."""

    def __init__(self, connection, poll: float = 0.3):
        self.connection, self.poll = connection, poll

    def evaluate(self, expression: str):
        result = self.connection.command("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                                              "awaitPromise": True})
        return (result.get("result") or {}).get("value")

    def _settle(self, timeout: float = 30) -> None:
        """Wait until the page has loaded, then until its text stops changing: travel and shop pages
        fetch their prices after loading. At least 4 polls, at most about 8 seconds after loading."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and self.evaluate("document.readyState") != "complete":
            time.sleep(self.poll)
        previous, unchanged = object(), 0
        for number in range(int(8 / max(self.poll, 0.01)) + 1):
            current = self.evaluate(SETTLE_JS)
            unchanged = unchanged + 1 if current == previous else 0
            if unchanged >= 3 and number >= 4:
                return
            previous = current
            time.sleep(self.poll)

    def read(self) -> dict:
        page = self.evaluate(PAGE_JS) or {}
        return {"title": page.get("title", ""), "url": page.get("url", ""), "text": page.get("text", ""),
                "elements": self.evaluate(ELEMENTS_JS) or []}

    def goto(self, url: str) -> dict:
        self.connection.command("Page.navigate", {"url": url})
        self._settle()
        return self.read()

    def describe(self, element: int) -> dict:
        info = self.evaluate(f"{LOCATE_JS}({int(element)})")
        if not info:
            raise BrowserError(f"there is no element [{element}] on the page any more: read the page again")
        return info

    def click(self, element: int) -> None:
        info = self.describe(element)
        for kind in ("mousePressed", "mouseReleased"):
            self.connection.command("Input.dispatchMouseEvent", {"type": kind, "x": info["x"], "y": info["y"],
                                                                 "button": "left", "clickCount": 1})
        self._settle(timeout=10)

    def type(self, element: int, text: str, submit: bool = False) -> None:
        self.describe(element)
        self.evaluate(f"{FOCUS_JS}({int(element)})")
        self.connection.command("Input.insertText", {"text": text})
        if submit:
            for kind in ("keyDown", "keyUp"):
                self.connection.command("Input.dispatchKeyEvent", {"type": kind, "key": "Enter", "code": "Enter",
                                                                   "windowsVirtualKeyCode": 13, "text": "\r"})
            self._settle(timeout=10)

    def scroll(self, direction: str = "down") -> None:
        step = -1 if direction.lower() in ("up", "yukarı", "yukari") else 1
        self.evaluate(f"window.scrollBy(0, (window.innerHeight || 800) * 0.8 * {step})")
        time.sleep(self.poll)

    def screenshot(self) -> bytes:
        return base64.b64decode(self.connection.command("Page.captureScreenshot", {"format": "png"})["data"])


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def launch(profile: Path, executable: str | None = None, wait: float = 20) -> tuple[subprocess.Popen, str]:
    """Start the browser with its own profile; returns the process and the page's DevTools address."""
    executable = executable or find_browser()
    if not executable:
        raise BrowserError("Edge or Chrome was not found on this computer")
    port = free_port()
    profile.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen([executable, f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
                                "--no-first-run", "--no-default-browser-check", "about:blank"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    session = requests.Session()
    session.trust_env = False
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        try:
            pages = [t for t in session.get(f"http://127.0.0.1:{port}/json/list", timeout=2).json()
                     if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
            if pages:
                return process, pages[0]["webSocketDebuggerUrl"]
        except (requests.RequestException, ValueError):
            pass
        time.sleep(0.3)
    process.kill()
    raise BrowserError("the browser started but did not open its DevTools connection")


class BrowserControl:
    """The browser the tools use: started on first use, restarted if it was closed."""

    def __init__(self, profile: Path, track=None, launcher=launch):
        self.profile, self.track, self.launcher = profile, track, launcher
        self.process, self.session = None, None

    def _alive(self) -> bool:
        return bool(self.session and self.process and self.process.poll() is None)

    def _start(self) -> BrowserSession:
        if not self._alive():
            self.process, address = self.launcher(self.profile)
            if self.track:
                self.track(self.process)            # the STOP button closes the browser too
            self.session = BrowserSession(Connection(WebSocket(address)))
        return self.session

    def _open(self) -> BrowserSession:
        if not self._alive():
            raise BrowserError("no page is open yet: use browser_go first")
        return self.session

    def goto(self, url: str) -> dict:
        return self._start().goto(url)

    def read(self) -> dict:
        return self._open().read()

    def describe(self, element: int) -> dict:
        return self._open().describe(element)

    def click(self, element: int) -> None:
        self._open().click(element)

    def type(self, element: int, text: str, submit: bool = False) -> None:
        self._open().type(element, text, submit)

    def scroll(self, direction: str) -> None:
        self._open().scroll(direction)

    def screenshot(self) -> bytes:
        return self._open().screenshot()
