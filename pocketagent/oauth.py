"""Sign in to OpenRouter from the browser (OAuth PKCE), so there is no API key to copy and paste.

1. The panel opens openrouter.ai/auth with a *challenge* (a hash of a random secret, the verifier).
2. After you log in, OpenRouter sends the browser back to the panel on localhost with a one-time code.
3. The panel trades code + verifier for an API key. Without the verifier, which never leaves
   this computer, a stolen or planted code is useless.
"""

import base64
import hashlib
import secrets
from urllib.parse import urlencode

import requests

from pocketagent.llm import BrainError

AUTH_URL = "https://openrouter.ai/auth"
EXCHANGE_URL = "https://openrouter.ai/api/v1/auth/keys"


def make_verifier() -> str:
    return secrets.token_urlsafe(48)


def challenge_for(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorize_url(callback_url: str, verifier: str) -> str:
    return AUTH_URL + "?" + urlencode({"callback_url": callback_url, "code_challenge": challenge_for(verifier),
                                       "code_challenge_method": "S256"})


def exchange_code(code: str, verifier: str, http=requests) -> str:
    """Trade the one-time code for an OpenRouter API key."""
    try:
        response = http.post(EXCHANGE_URL, timeout=20, json={
            "code": code, "code_verifier": verifier, "code_challenge_method": "S256"})
    except requests.RequestException as error:
        raise BrainError(f"cannot reach OpenRouter: {error}") from error
    if response.status_code >= 400:
        raise BrainError(f"OpenRouter refused the login (HTTP {response.status_code}): {response.text[:200]}",
                         status=response.status_code)
    key = response.json().get("key")
    if not key:
        raise BrainError("OpenRouter did not send a key")
    return key
