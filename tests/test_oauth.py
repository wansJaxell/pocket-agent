from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from pocketagent.llm import BrainError
from pocketagent.oauth import authorize_url, challenge_for, exchange_code, make_verifier


def test_pkce_challenge_matches_the_rfc_7636_example():
    assert challenge_for("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_verifiers_are_long_and_random():
    first, second = make_verifier(), make_verifier()
    assert len(first) >= 43 and first != second


def test_authorize_url_sends_the_challenge_not_the_verifier():
    url = authorize_url("http://localhost:8765/oauth/openrouter", "secret-verifier")
    query = parse_qs(urlparse(url).query)
    assert url.startswith("https://openrouter.ai/auth?")
    assert query["callback_url"] == ["http://localhost:8765/oauth/openrouter"]
    assert query["code_challenge"] == [challenge_for("secret-verifier")]
    assert query["code_challenge_method"] == ["S256"]
    assert "secret-verifier" not in url


class FakePost:
    def __init__(self, body, status=200):
        self.body, self.status, self.sent = body, status, []

    def post(self, url, json, timeout):
        self.sent.append((url, json))
        return SimpleNamespace(status_code=self.status, json=lambda: self.body, text=str(self.body))


def test_exchange_code_returns_the_new_key():
    http = FakePost({"key": "sk-or-v1-new"})
    assert exchange_code("the-code", "the-verifier", http) == "sk-or-v1-new"
    assert http.sent == [("https://openrouter.ai/api/v1/auth/keys",
                          {"code": "the-code", "code_verifier": "the-verifier", "code_challenge_method": "S256"})]


def test_failed_exchange_is_explained():
    with pytest.raises(BrainError, match="HTTP 403"):
        exchange_code("used-code", "v", FakePost({"error": "invalid code"}, status=403))
