import time

import pytest
import requests
from conftest import FakeWeb, response

from pocketagent.app import App
from pocketagent.config import BrainConfig, Config
from pocketagent.llm import PROVIDERS
from pocketagent.panel import PanelServer


@pytest.fixture
def panel():
    web = FakeWeb(("POST", "/chat/completions", response({"choices": [{"message": {"content": "Selam!"}}]})),
                  ("POST", "openrouter.ai/api/v1/auth/keys", response({"key": "sk-or-v1-from-login"})))
    server = PanelServer(App(Config(), http=web), port=0)
    server.start(poll_interval=0.02)
    yield server
    server.stop()


@pytest.fixture
def client():
    session = requests.Session()
    session.trust_env = False          # never send loopback requests through a proxy
    return session


def api(client, panel, method, path, body=None, **headers):
    headers = {"X-Pocket-Token": panel.token, **headers}
    if method == "POST" and body is None:
        body = {}
    return client.request(method, panel.url + path, json=body, headers=headers, timeout=5)


def test_listens_only_on_this_computer(panel):
    assert panel.httpd.server_address[0] == "127.0.0.1"
    assert panel.url == f"http://127.0.0.1:{panel.port}/"


def test_the_page_is_served_with_its_token_and_strict_headers(panel, client):
    page = client.get(panel.url, timeout=5)
    assert page.status_code == 200 and "PocketAgent" in page.text and panel.token in page.text
    assert "frame-ancestors 'none'" in page.headers["Content-Security-Policy"]
    assert page.headers["X-Frame-Options"] == "DENY"


def test_the_api_needs_the_page_token(panel, client):
    assert client.get(panel.url + "api/state", timeout=5).status_code == 403
    assert api(client, panel, "GET", "api/state", **{"X-Pocket-Token": "guess"}).status_code == 403
    assert api(client, panel, "GET", "api/state").json()["app"] == "PocketAgent"


def test_other_host_names_are_refused_against_dns_rebinding(panel, client):
    page = client.get(panel.url, headers={"Host": f"evil.example:{panel.port}"}, timeout=5)
    assert page.status_code == 403 and panel.token not in page.text
    assert client.get(panel.url, headers={"Host": f"localhost:{panel.port}"}, timeout=5).status_code == 200


def test_requests_from_other_websites_are_refused(panel, client):
    reply = api(client, panel, "POST", "api/identity", {"name": "Hacked"}, Origin="https://evil.example")
    assert reply.status_code == 403
    assert api(client, panel, "GET", "api/state").json()["identity"]["name"] == "PocketAgent"


def test_posts_must_be_json(panel, client):
    reply = client.post(panel.url + "api/identity", data="name=x", timeout=5,
                         headers={"X-Pocket-Token": panel.token, "Content-Type": "application/x-www-form-urlencoded"})
    assert reply.status_code == 415


def test_problems_come_back_as_readable_json(panel, client):
    reply = api(client, panel, "POST", "api/key", {"provider": "no-such-provider", "key": "x"})
    assert reply.status_code == 400 and "provider" in reply.json()["error"]
    assert api(client, panel, "GET", "api/nothing-here").status_code == 404


def test_ping_answers_without_a_token_so_a_second_start_finds_the_first(panel, client):
    assert client.get(panel.url + "api/ping", timeout=5).json() == {"app": "PocketAgent"}


def test_openrouter_callback_without_a_login_in_progress_is_refused(panel, client):
    reply = client.get(panel.url + "oauth/openrouter?code=planted", timeout=5)
    assert reply.status_code == 400
    assert "openrouter" not in panel.app.config.keys


def test_openrouter_callback_finishes_the_login(panel, client):
    start = api(client, panel, "POST", "api/openrouter/start").json()
    assert f"localhost%3A{panel.port}%2Foauth%2Fopenrouter" in start["url"]
    page = client.get(panel.url + "oauth/openrouter?code=real-code", timeout=5)
    assert page.status_code == 200
    assert panel.app.config.keys["openrouter"] == "sk-or-v1-from-login"


def test_chat_round_trip(panel, client):
    panel.app.config.set_brains([BrainConfig("groq", PROVIDERS["groq"].base_url, "llama")])
    panel.app.config.keys["groq"] = "g"
    job = api(client, panel, "POST", "api/chat", {"text": "Merhaba"}).json()
    for _ in range(100):
        state = api(client, panel, "GET", f"api/job?id={job['id']}").json()
        if state["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert state["result"]["text"] == "Selam!" and state["result"]["brain"] == "Groq · llama"
    history = api(client, panel, "GET", "api/history").json()
    assert history[-1] == {"role": "assistant", "content": "Selam!"}


def test_the_stop_button_works_even_on_a_locked_panel(panel, client):
    panel.app.config.access = "locked"          # pretend: locked, and this browser has no session
    reply = api(client, panel, "POST", "api/stop")
    assert reply.status_code == 200 and reply.json()["approvals"] == 0
    assert api(client, panel, "POST", "api/computer_use", {"enabled": True}).status_code == 401
