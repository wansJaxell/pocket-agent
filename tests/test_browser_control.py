"""The agent's own browser window: Edge or Chrome driven over its DevTools connection. The browser is faked."""

import json
import socket
import threading

import pytest

from pocketagent import browser_control
from pocketagent.approvals import ApprovalEngine, AuditLog, RuleStore
from pocketagent.browser_control import BrowserError, BrowserSession, WebSocket
from pocketagent.tools import ToolContext, ToolRegistry


# ---------- the WebSocket client ----------
def server_frame(text: str) -> bytes:
    payload = text.encode()
    if len(payload) < 126:
        return bytes([0x81, len(payload)]) + payload
    return bytes([0x81, 126]) + len(payload).to_bytes(2, "big") + payload


def read_client_frame(conn) -> str:
    def take(n):
        data = b""
        while len(data) < n:
            data += conn.recv(n - len(data))
        return data
    first, second = take(2)
    assert first == 0x81 and second & 0x80                 # a final text frame, masked as clients must
    length = second & 0x7F
    if length == 126:
        length = int.from_bytes(take(2), "big")
    mask = take(4)
    return bytes(b ^ mask[i % 4] for i, b in enumerate(take(length))).decode()


def test_websocket_handshake_and_messages_in_both_directions():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port, got = listener.getsockname()[1], []

    def browser():
        conn, _ = listener.accept()
        request = conn.recv(4096).decode()
        key = next(line.split(": ")[1] for line in request.split("\r\n") if line.lower().startswith("sec-websocket-key"))
        conn.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      f"Sec-WebSocket-Accept: {browser_control.accept_key(key)}\r\n\r\n").encode())
        got.append(read_client_frame(conn))
        conn.sendall(bytes([0x89, 0]) + server_frame('{"id": 1, "result": {"ok": true}}' + " " * 200))  # ping first
        got.append(conn.recv(2))                            # the pong
        conn.close()
    thread = threading.Thread(target=browser)
    thread.start()
    ws = WebSocket(f"ws://127.0.0.1:{port}/devtools/page/ABC", timeout=5)
    ws.send('{"id": 1, "method": "Page.navigate"}')
    assert json.loads(ws.recv())["result"] == {"ok": True}
    thread.join(5)
    listener.close()
    assert got[0] == '{"id": 1, "method": "Page.navigate"}' and got[1][0] == 0x8A


# ---------- the session (what the agent can do in the page) ----------
class FakeConnection:
    """Answers DevTools commands like a page with a search box and a button would."""

    def __init__(self):
        self.sent = []
        self.ready = "complete"

    def command(self, method, params=None, timeout=30):
        self.sent.append((method, params or {}))
        if method == "Runtime.evaluate":
            js = params["expression"]
            if "document.readyState" in js:
                value = self.ready
            elif "data-pa-id]').forEach" in js:
                value = [{"id": 1, "tag": "input", "type": "search", "label": "Nereden"},
                         {"id": 2, "tag": "input", "type": "password", "label": "Şifre"},
                         {"id": 3, "tag": "button", "type": "submit", "label": "Uçuş ara"}]
            elif "scrollIntoView" in js:
                number = int(js.rsplit("(", 1)[1].rstrip(")"))
                value = None if number == 9 else {"x": 100.5, "y": 40, "tag": "button", "type": "submit",
                                                   "label": "Uçuş ara", "page": "https://flights.example/"}
            else:
                value = {"title": "Uçuşlar", "url": "https://flights.example/", "text": "İstanbul → Malé  12.400 TL"}
            return {"result": {"value": value}}
        if method == "Page.captureScreenshot":
            return {"data": "iVBORw0KGgo="}
        return {}


def session():
    return BrowserSession(connection=FakeConnection(), poll=0.01)


def test_going_to_a_page_waits_for_it_and_reads_it():
    s = session()
    page = s.goto("https://flights.example/")
    assert ("Page.navigate", {"url": "https://flights.example/"}) in s.connection.sent
    assert page["title"] == "Uçuşlar" and "12.400 TL" in page["text"]
    assert [e["label"] for e in page["elements"]] == ["Nereden", "Şifre", "Uçuş ara"]


def test_clicking_uses_real_mouse_events_at_the_element():
    s = session()
    s.click(3)
    mouse = [p for m, p in s.connection.sent if m == "Input.dispatchMouseEvent"]
    assert [m["type"] for m in mouse] == ["mousePressed", "mouseReleased"] and mouse[0]["x"] == 100.5
    with pytest.raises(BrowserError, match="no element"):
        s.click(9)


def test_typing_inserts_text_and_can_press_enter():
    s = session()
    s.type(1, "İstanbul", submit=True)
    assert ("Input.insertText", {"text": "İstanbul"}) in s.connection.sent
    keys = [p for m, p in s.connection.sent if m == "Input.dispatchKeyEvent"]
    assert keys[0]["key"] == "Enter" and keys[0]["type"] == "keyDown"


def test_the_browser_is_found_on_this_computer(monkeypatch, tmp_path):
    edge = tmp_path / "msedge.exe"
    edge.write_bytes(b"MZ")
    monkeypatch.setattr(browser_control, "CANDIDATES", [str(tmp_path / "missing.exe"), str(edge)])
    monkeypatch.setattr(browser_control.shutil, "which", lambda name: None)
    assert browser_control.find_browser() == str(edge)


# ---------- the tools and their approvals ----------
class FakeBrowser:
    """The high-level browser the tools use."""

    def __init__(self):
        self.calls = []
        self.page = {"title": "Uçuşlar", "url": "https://flights.example/search", "text": "İstanbul → Malé 12.400 TL",
                     "elements": [{"id": 1, "tag": "input", "type": "search", "label": "Nereden"},
                                  {"id": 2, "tag": "input", "type": "password", "label": "Şifre"},
                                  {"id": 3, "tag": "button", "type": "submit", "label": "Satın al"}]}

    def goto(self, url):
        self.calls.append(("goto", url))
        return self.page

    def read(self):
        return self.page

    def describe(self, element):
        return next(e for e in self.page["elements"] if e["id"] == element) | {"page": self.page["url"]}

    def click(self, element):
        self.calls.append(("click", element))

    def type(self, element, text, submit=False):
        self.calls.append(("type", element, text, submit))

    def scroll(self, direction):
        self.calls.append(("scroll", direction))

    def screenshot(self):
        return b"\x89PNG-page"


def computer(tmp_path, answer=(True, True)):
    engine = ApprovalEngine(RuleStore(tmp_path), AuditLog(tmp_path), lambda: True, timeout=5)
    asked = []
    engine.notifiers.append(lambda p: asked.append(p) or engine.answer(p.id, *answer))
    browser = FakeBrowser()
    ctx = ToolContext(workspace=tmp_path / "ws", approvals=engine, computer_use=True, generation=engine.generation,
                      browser=browser)
    return ctx, asked, browser


def tools():
    registry = ToolRegistry()
    registry.load_builtin()
    return registry


def test_going_to_a_site_is_approved_per_site_and_the_page_is_outside_content(tmp_path):
    ctx, asked, browser = computer(tmp_path)
    result = tools().call("browser_go", {"url": "https://flights.example/search"}, ctx)
    assert "12.400 TL" in result and "[3] button: Satın al" in result
    assert asked[0].action.scope == {"site": "https://flights.example"} and ctx.tainted_by
    assert "Only http" in tools().call("browser_go", {"url": "file:///C:/secret.txt"}, ctx)


def test_every_click_after_reading_a_page_asks_and_buying_is_flagged(tmp_path):
    ctx, asked, browser = computer(tmp_path)
    tools().call("browser_go", {"url": "https://flights.example/search"}, ctx)
    tools().call("browser_click", {"element": 3}, ctx)
    tools().call("browser_click", {"element": 3}, ctx)
    clicks = [p for p in asked if p.action.kind == "browser_click"]
    assert len(clicks) == 2 and "money" in clicks[0].classes and not clicks[0].can_remember
    assert clicks[0].action.params["element"] == "button: Satın al"
    assert browser.calls.count(("click", 3)) == 2


def test_the_agent_never_types_into_password_fields(tmp_path):
    ctx, asked, browser = computer(tmp_path)
    result = tools().call("browser_type", {"element": 2, "text": "hunter2"}, ctx)
    assert "themselves" in result and not any(c[0] == "type" for c in browser.calls)
    tools().call("browser_type", {"element": 1, "text": "İstanbul", "submit": True}, ctx)
    assert ("type", 1, "İstanbul", True) in browser.calls


def test_reading_scrolling_and_page_screenshots_need_no_extra_approval(tmp_path):
    ctx, asked, browser = computer(tmp_path)
    assert "12.400 TL" in tools().call("browser_read", {}, ctx)
    tools().call("browser_scroll", {"direction": "down"}, ctx)
    assert "media/browser-" in tools().call("browser_screenshot", {}, ctx)
    assert asked == [] and ("scroll", "down") in browser.calls


def test_browser_tools_are_hidden_in_safe_mode():
    names = {s["function"]["name"] for s in tools().schemas(computer_use=False)}
    assert not {"browser_go", "browser_click", "browser_type", "browser_read"} & names
