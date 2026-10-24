"""Encrypted storage for the API keys and the Telegram token ("locked" access mode).

    panel password --scrypt--> 64 bytes: 32 for AES-256-CTR, 32 for HMAC-SHA256
    vault = {v, kdf, salt, nonce, data, mac}    (the MAC covers all the rest: encrypt-then-MAC)

The password is never stored anywhere. While the app runs, the derived key stays in memory so
changed settings can be saved again. A wrong password fails the MAC check. A forgotten password
cannot be recovered: delete the vault and enter the keys again.
"""

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass

from pocketagent import aes


class WrongPassword(Exception):
    """The password is wrong, or the vault was changed."""


@dataclass
class VaultKey:
    enc: bytes      # AES-256 key
    mac: bytes      # HMAC-SHA256 key
    salt: bytes
    kdf: dict


def default_kdf() -> dict:
    if hasattr(hashlib, "scrypt"):     # needs OpenSSL 1.1+; true for python.org builds
        return {"name": "scrypt", "n": 2 ** 15, "r": 8, "p": 1}
    return {"name": "pbkdf2-sha256", "iterations": 600_000}


def derive(password: str, salt: bytes | None = None, kdf: dict | None = None) -> VaultKey:
    """Turn the password into encryption + MAC keys (slow on purpose, to make guessing expensive)."""
    salt, kdf = salt or os.urandom(16), kdf or default_kdf()
    secret = password.encode("utf-8")
    if kdf["name"] == "scrypt":
        raw = hashlib.scrypt(secret, salt=salt, n=kdf["n"], r=kdf["r"], p=kdf["p"],
                             maxmem=256 * kdf["r"] * kdf["n"] * kdf["p"], dklen=64)
    elif kdf["name"] == "pbkdf2-sha256":
        raw = hashlib.pbkdf2_hmac("sha256", secret, salt, kdf["iterations"], dklen=64)
    else:
        raise WrongPassword(f"unknown key derivation '{kdf['name']}'")
    return VaultKey(raw[:32], raw[32:], salt, dict(kdf))


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def _signed_part(blob: dict) -> bytes:
    return json.dumps({k: blob.get(k) for k in ("v", "kdf", "salt", "nonce", "data")}, sort_keys=True).encode()


def seal(key: VaultKey, secrets: dict) -> dict:
    nonce = os.urandom(16)            # a fresh random counter block on every save
    data = aes.ctr(key.enc, nonce, json.dumps(secrets, ensure_ascii=False).encode("utf-8"))
    blob = {"v": 1, "kdf": key.kdf, "salt": _b64(key.salt), "nonce": _b64(nonce), "data": _b64(data)}
    blob["mac"] = _b64(hmac.new(key.mac, _signed_part(blob), hashlib.sha256).digest())
    return blob


def open_vault(blob: dict, password: str) -> tuple[dict, VaultKey]:
    """Decrypt the vault; returns the secrets and the key (to save changes later)."""
    try:
        key = derive(password, _b64d(blob["salt"]), blob["kdf"])
        expected = hmac.new(key.mac, _signed_part(blob), hashlib.sha256).digest()
        valid = hmac.compare_digest(expected, _b64d(blob.get("mac", "")))
    except (KeyError, TypeError, ValueError) as error:
        raise WrongPassword(f"the vault is damaged: {error}") from None
    if not valid:
        raise WrongPassword("wrong password")
    plain = aes.ctr(key.enc, _b64d(blob["nonce"]), _b64d(blob["data"]))
    return json.loads(plain.decode("utf-8")), key
