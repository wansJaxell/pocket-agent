import json

import pytest

from pocketagent import aes, vault

FAST = {"name": "scrypt", "n": 2 ** 10, "r": 8, "p": 1}      # tests only: the real default is much slower


# ---------- AES against the official test vectors ----------
def test_aes_128_fips_197_appendix_c1():
    cipher = aes.AES(bytes(range(16)))
    assert cipher.encrypt_block(bytes.fromhex("00112233445566778899aabbccddeeff")).hex() == \
        "69c4e0d86a7b0430d8cdb78070b4c55a"


def test_aes_256_fips_197_appendix_c3():
    cipher = aes.AES(bytes(range(32)))
    assert cipher.encrypt_block(bytes.fromhex("00112233445566778899aabbccddeeff")).hex() == \
        "8ea2b7ca516745bfeafc49904b496089"


def test_aes_256_ctr_nist_sp800_38a_f55():
    key = bytes.fromhex("603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4")
    counter = bytes.fromhex("f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff")
    plain = bytes.fromhex("6bc1bee22e409f96e93d7e117393172a" "ae2d8a571e03ac9c9eb76fac45af8e51"
                          "30c81c46a35ce411e5fbc1191a0a52ef" "f69f2445df4f9b17ad2b417be66c3710")
    secret = bytes.fromhex("601ec313775789a5b7a7f504bbf3d228" "f443e3ca4d62b59aca84e990cacaf5c5"
                           "2b0930daa23de94ce87017ba2d84988d" "dfc9c58db67aada613c2dd08457941a6")
    assert aes.ctr(key, counter, plain) == secret
    assert aes.ctr(key, counter, secret) == plain                 # the same operation decrypts
    assert aes.ctr(key, counter, plain[:21]) == secret[:21]       # partial last block


def test_aes_refuses_bad_key_sizes():
    with pytest.raises(ValueError):
        aes.AES(b"short")


# ---------- the vault ----------
def test_vault_round_trip_without_plaintext_on_disk():
    secrets = {"keys": {"groq": "gsk_secret_value"}, "telegram_token": "123:ABC"}
    key = vault.derive("correct horse", kdf=FAST)
    blob = vault.seal(key, secrets)
    assert "gsk_secret_value" not in json.dumps(blob) and "123:ABC" not in json.dumps(blob)
    data, again = vault.open_vault(blob, "correct horse")
    assert data == secrets and again.enc == key.enc
    assert vault.seal(key, secrets)["nonce"] != blob["nonce"]     # a fresh nonce on every save


def test_wrong_password_is_refused():
    blob = vault.seal(vault.derive("right", kdf=FAST), {"keys": {}})
    with pytest.raises(vault.WrongPassword):
        vault.open_vault(blob, "wrong")


def test_any_change_to_the_vault_is_detected():
    blob = vault.seal(vault.derive("pw", kdf=FAST), {"keys": {"a": "b"}})
    data = bytearray(vault._b64d(blob["data"]))
    data[0] ^= 1
    with pytest.raises(vault.WrongPassword):
        vault.open_vault({**blob, "data": vault._b64(bytes(data))}, "pw")
    with pytest.raises(vault.WrongPassword):
        vault.open_vault({**blob, "kdf": {**FAST, "n": 2 ** 11}}, "pw")


def test_default_key_derivation_is_strong():
    kdf = vault.default_kdf()
    assert (kdf["name"] == "scrypt" and kdf["n"] >= 2 ** 15) or kdf["iterations"] >= 600_000
