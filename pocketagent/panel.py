"""The web panel: one page served by Python's own http.server, on 127.0.0.1 only.

A server on 127.0.0.1 cannot be reached from other computers, but web pages you visit can still
try to talk to it, so every request is checked:
  - the Host header must be 127.0.0.1:<port> or localhost:<port> (stops DNS-rebinding attacks)
  - every API call must carry the random token that is embedded in the page; other websites can
    neither read the page nor send that header (stops cross-site request forgery)
  - requests whose Origin is another website are refused, and POST bodies must be JSON
  - the page may not be shown inside another site's frame (stops clickjacking)
"""

import hmac
import html
import json
import os
import secrets
import socket
import socketserver
import threading
from dataclasses import dataclass
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from pocketagent.app import App, PanelError
from pocketagent.panel_page import render_page

MAX_BODY = 1_000_000


@dataclass
class Request:
    app: App
    panel: "PanelServer"
    body: dict
    query: dict
    session: str | None          # this browser's session cookie (locked mode)

    def text(self, key: str) -> str:
        value = self.body.get(key, "")
        return value if isinstance(value, str) else str(value)


# (method, path after /api/) -> function(request). A route may return {"_session": id} to sign
# this browser in (a cookie) or {"_session": None} to sign it out.
ROUTES = {
    ("GET", "state"): lambda r: r.app.state() if r.app.signed_in(r.session) else r.app.locked_state(),
    ("GET", "local"): lambda r: r.app.local_models(),
    ("GET", "models"): lambda r: r.app.models(r.query.get("provider", "")),
    ("GET", "job"): lambda r: r.app.job(r.query.get("id", "")),
    ("GET", "history"): lambda r: r.app.history(),
    ("POST", "key"): lambda r: r.app.save_key(r.text("provider"), r.text("key"), r.text("base_url")),
    ("POST", "brains/add"): lambda r: r.app.add_brain(r.text("provider"), r.text("model"), r.body.get("free") is not False),
    ("POST", "brains/move"): lambda r: r.app.move_brain(r.body.get("index"), r.body.get("delta", 0)),
    ("POST", "brains/remove"): lambda r: r.app.remove_brain(r.body.get("index")),
    ("POST", "brains/test"): lambda r: r.app.test_brain(r.body.get("index")),
    ("POST", "openrouter/start"): lambda r: {"url": r.app.openrouter_start(r.panel.callback_url)},
    ("POST", "telegram"): lambda r: r.app.telegram_connect(r.text("token")),
    ("POST", "telegram/disconnect"): lambda r: r.app.telegram_disconnect(),
    ("POST", "identity"): lambda r: r.app.set_identity(r.text("name"), r.text("personality")),
    ("POST", "language"): lambda r: r.app.set_language(r.text("language")),
    ("POST", "access"): lambda r: {"_session": r.app.set_access(r.text("mode"), r.text("password"))},
    ("POST", "unlock"): lambda r: {"_session": r.app.unlock(r.text("password"))},
    ("POST", "lock"): lambda r: (r.app.logout(r.session), {"_session": None})[1],
    ("POST", "vault/forget"): lambda r: r.app.forget_vault(),
    ("POST", "autostart"): lambda r: r.app.set_autostart(r.body.get("enabled") is True),
    ("POST", "chat"): lambda r: r.app.chat(r.text("text")),
    ("POST", "chat/reset"): lambda r: r.app.reset_chat(),
}

# what a browser may do before it gives the panel password (locked mode)
OPEN_WHEN_LOCKED = {("GET", "state"), ("POST", "unlock"), ("POST", "vault/forget"), ("POST", "language")}


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = os.name != "nt"     # on Windows this would let another program share the port

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows: no other program may bind this port
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        socketserver.TCPServer.server_bind(self)    # skips HTTPServer's slow reverse DNS lookup
        self.server_name, self.server_port = self.server_address[:2]


class PanelServer:
    def __init__(self, app: App, port: int = 8765):
        self.app = app
        self.token = secrets.token_urlsafe(32)
        self.httpd = _Server(("127.0.0.1", port), self._handler())
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}/"
        self.hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        self.origins = {f"http://{host}" for host in self.hosts}
        self.cookie = f"pocketagent_{self.port}"    # cookies are per host, not per port
        self._thread: threading.Thread | None = None

    @property
    def callback_url(self) -> str:
        return f"http://localhost:{self.port}/oauth/openrouter"

    def start(self, poll_interval: float = 0.5) -> None:
        self._thread = threading.Thread(target=self.httpd.serve_forever, args=(poll_interval,),
                                        name="pocketagent-panel", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def _handler(panel):
        class Handler(BaseHTTPRequestHandler):
            server_version, sys_version = "PocketAgent", ""

            def log_message(self, format, *args):    # keep the console for the agent's own messages
                pass

            def do_GET(self):
                self._dispatch("GET")

            def do_POST(self):
                self._dispatch("POST")

            def _dispatch(self, method: str) -> None:
                url = urlparse(self.path)
                query = {k: v[0] for k, v in parse_qs(url.query).items()}
                origin = self.headers.get("Origin")
                if self.headers.get("Host", "") not in panel.hosts or (origin and origin not in panel.origins):
                    return self._json(403, {"error": "This panel only answers to itself."})
                if method == "GET" and url.path in ("/", "/index.html"):
                    return self._page()
                if method == "GET" and url.path == "/api/ping":
                    return self._json(200, {"app": "PocketAgent"})
                if method == "GET" and url.path == "/oauth/openrouter":
                    return self._openrouter_callback(query)
                if not url.path.startswith("/api/"):
                    return self._json(404, {"error": "Not found."})
                if not hmac.compare_digest(self.headers.get("X-Pocket-Token", ""), panel.token):
                    return self._json(403, {"error": "Missing or wrong panel token: reload the page."})
                name = (method, url.path[len("/api/"):])
                route = ROUTES.get(name)
                if route is None:
                    return self._json(404, {"error": "Not found."})
                cookie = SimpleCookie(self.headers.get("Cookie", "")).get(panel.cookie)
                session = cookie.value if cookie else None
                if name not in OPEN_WHEN_LOCKED and not panel.app.signed_in(session):
                    return self._json(401, {"error": "The panel is locked: enter the password.", "locked": True})
                body = {}
                if method == "POST":
                    if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                        return self._json(415, {"error": "Send JSON."})
                    length = int(self.headers.get("Content-Length") or 0)
                    if length > MAX_BODY:
                        return self._json(413, {"error": "Too large."})
                    try:
                        body = json.loads(self.rfile.read(length) or b"{}")
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        body = None
                    if not isinstance(body, dict):
                        return self._json(400, {"error": "Send a JSON object."})
                try:
                    result = route(Request(panel.app, panel, body, query, session))
                except PanelError as error:
                    return self._json(400, {"error": str(error)})
                except Exception as error:     # show the problem instead of a broken page
                    return self._json(500, {"error": f"{type(error).__name__}: {error}"})
                extra = []
                if isinstance(result, dict) and "_session" in result:
                    new = result.pop("_session")
                    extra.append(("Set-Cookie", f"{panel.cookie}={new}; HttpOnly; SameSite=Strict; Path=/" if new
                                  else f"{panel.cookie}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"))
                self._json(200, result or {"ok": True}, extra)

            def _headers(self, status: int, content_type: str, length: int, csp: str, extra=()) -> None:
                self.send_response(status)
                for header, value in extra:
                    self.send_header(header, value)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(length))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Security-Policy", csp)
                self.end_headers()

            def _json(self, status: int, data, extra=()) -> None:
                raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self._headers(status, "application/json; charset=utf-8", len(raw),
                              "default-src 'none'; frame-ancestors 'none'", extra)
                self.wfile.write(raw)

            def _html(self, status: int, page: str, nonce: str = "") -> None:
                raw = page.encode("utf-8")
                scripts = f"'nonce-{nonce}'" if nonce else "'none'"
                self._headers(status, "text/html; charset=utf-8", len(raw),
                              f"default-src 'none'; script-src {scripts}; style-src {scripts}; "
                              "connect-src 'self'; img-src 'self' data:; base-uri 'none'; "
                              "form-action 'none'; frame-ancestors 'none'")
                self.wfile.write(raw)

            def _page(self) -> None:
                nonce = secrets.token_urlsafe(16)
                self._html(200, render_page(panel.token, nonce, panel.app.config.language), nonce)

            def _openrouter_callback(self, query: dict) -> None:
                status, message = 200, "OpenRouter is connected. You can close this tab and go back to the panel."
                try:
                    if query.get("error"):
                        raise PanelError(f"OpenRouter: {query['error']}")
                    panel.app.openrouter_finish(query.get("code", ""))
                except PanelError as error:
                    status, message = 400, str(error)
                nonce = secrets.token_urlsafe(16)
                self._html(status, f"""<!doctype html><meta charset="utf-8"><title>PocketAgent</title>
<style nonce="{nonce}">body{{font:16px system-ui,sans-serif;margin:15vh auto;max-width:32rem;padding:0 16px}}</style>
<h1>{'✅' if status == 200 else '⚠️'} PocketAgent</h1><p>{html.escape(message)}</p>
<p><a href="/">Back to the panel</a></p>""", nonce)

        return Handler
