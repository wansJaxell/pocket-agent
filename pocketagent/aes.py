"""AES (FIPS-197) and CTR mode in pure Python.

Python's standard library has no AES and PocketAgent depends only on `requests`, so this is a
small, readable implementation, checked against the official NIST test vectors in
tests/test_crypto.py. It only encrypts a few short API keys, so speed does not matter.
Only the forward cipher is needed: CTR mode decrypts by encrypting the same counters again.
"""


def _xtime(a: int) -> int:
    """Multiply by x (that is, 2) in AES's finite field."""
    return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else a << 1


def _rotl8(x: int, shift: int) -> int:
    return ((x << shift) | (x >> (8 - shift))) & 0xFF


def _make_sbox() -> list[int]:
    """The S-box: multiplicative inverse in GF(2^8) followed by the affine transform."""
    sbox, p, q = [0] * 256, 1, 1
    while True:
        p = (p ^ (p << 1) ^ (0x1B if p & 0x80 else 0)) & 0xFF      # p * 3
        q = (q ^ (q << 1)) & 0xFF                                  # q / 3 ...
        q = (q ^ (q << 2)) & 0xFF
        q = (q ^ (q << 4)) & 0xFF
        if q & 0x80:
            q ^= 0x09
        sbox[p] = q ^ _rotl8(q, 1) ^ _rotl8(q, 2) ^ _rotl8(q, 3) ^ _rotl8(q, 4) ^ 0x63
        if p == 1:
            break
    sbox[0] = 0x63
    return sbox


SBOX = _make_sbox()


def _expand_key(key: bytes) -> list[list[int]]:
    """The round keys, 16 bytes each (11, 13 or 15 of them for 128, 192 or 256-bit keys)."""
    nk = len(key) // 4
    rounds = nk + 6
    words = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    rcon = 1
    for i in range(nk, 4 * (rounds + 1)):
        word = list(words[i - 1])
        if i % nk == 0:
            word = [SBOX[b] for b in word[1:] + word[:1]]
            word[0] ^= rcon
            rcon = _xtime(rcon)
        elif nk > 6 and i % nk == 4:
            word = [SBOX[b] for b in word]
        words.append([a ^ b for a, b in zip(words[i - nk], word)])
    return [sum(words[4 * r:4 * r + 4], []) for r in range(rounds + 1)]


def _mix_columns(state: list[int]) -> list[int]:
    out = []
    for c in range(4):
        col = state[4 * c:4 * c + 4]
        total = col[0] ^ col[1] ^ col[2] ^ col[3]
        out += [col[i] ^ total ^ _xtime(col[i] ^ col[(i + 1) % 4]) for i in range(4)]
    return out


class AES:
    def __init__(self, key: bytes):
        if len(key) not in (16, 24, 32):
            raise ValueError("AES keys are 16, 24 or 32 bytes long")
        self._round_keys = _expand_key(key)

    def encrypt_block(self, block: bytes) -> bytes:
        """Encrypt one 16-byte block. The state is column-major, like the input bytes."""
        state = [b ^ k for b, k in zip(block, self._round_keys[0])]
        last = len(self._round_keys) - 1
        for number in range(1, last + 1):
            state = [SBOX[b] for b in state]                                 # SubBytes
            state = [state[(i + 4 * (i % 4)) % 16] for i in range(16)]       # ShiftRows
            if number != last:
                state = _mix_columns(state)                                  # MixColumns
            state = [b ^ k for b, k in zip(state, self._round_keys[number])]  # AddRoundKey
        return bytes(state)


def ctr(key: bytes, counter: bytes, data: bytes) -> bytes:
    """Encrypt or decrypt (the same operation) with AES in counter mode.

    counter is the first 16-byte counter block; it is incremented as a 128-bit big-endian number.
    Never reuse a counter with the same key: the vault picks a random one on every save.
    """
    cipher, value, out = AES(key), int.from_bytes(counter, "big"), bytearray()
    for offset in range(0, len(data), 16):
        stream = cipher.encrypt_block(value.to_bytes(16, "big"))
        value = (value + 1) % (1 << 128)
        out += bytes(a ^ b for a, b in zip(data[offset:offset + 16], stream))
    return bytes(out)
