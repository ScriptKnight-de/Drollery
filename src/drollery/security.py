"""Password hashing, tokens, TOTP two-factor codes and a small login throttle. Standard library only."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
from collections import defaultdict
from urllib.parse import quote

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1
MIN_PASSWORD = 10


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


# ------------------------------------------------------------- passwords

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, dk = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(dk)
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                             dklen=len(expected), maxmem=128 * int(n) * int(r) * 2 + (1 << 20))
        return hmac.compare_digest(got, expected)
    except (ValueError, TypeError):
        return False


def password_problem(password: str, username: str = "") -> str:
    """Return a human-readable reason the password is unacceptable, or '' if fine."""
    if len(password) < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters"
    if username and password.lower() == username.lower():
        return "The password must not be the same as the username"
    if len(set(password)) < 4:
        return "That password is too repetitive"
    return ""


# ---------------------------------------------------------------- tokens

def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def safe_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


# ------------------------------------------------------------------ TOTP

def new_totp_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


def _hotp(secret: str, counter: int, digits: int = 6) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    code = (struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** digits
    return f"{code:0{digits}d}"


def totp_now(secret: str, at: float | None = None) -> str:
    return _hotp(secret, int((at if at is not None else time.time()) // 30))


def totp_verify(secret: str, code: str, last_step: int = 0, window: int = 1) -> int | None:
    """Return the matched 30-second step, or None. Steps <= last_step are rejected (no code reuse)."""
    code = "".join(ch for ch in code if ch.isdigit())
    if len(code) != 6:
        return None
    now_step = int(time.time() // 30)
    for step in range(now_step - window, now_step + window + 1):
        if step > last_step and hmac.compare_digest(_hotp(secret, step), code):
            return step
    return None


def totp_uri(secret: str, username: str, issuer: str = "Drollery") -> str:
    label = quote(f"{issuer}:{username}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30"


def new_backup_codes(n: int = 8) -> list[str]:
    return [f"{secrets.token_hex(3)}-{secrets.token_hex(3)}" for _ in range(n)]


def backup_hash(code: str) -> str:
    return hashlib.sha256("".join(ch for ch in code.lower() if ch.isalnum()).encode()).hexdigest()


# -------------------------------------------------------------- throttle

class Throttle:
    """Counts failures per key in a sliding window; in-memory, which is right for one worker process."""

    def __init__(self, limit: int = 5, window: int = 900):
        self.limit, self.window = limit, window
        self.hits: dict[str, list[float]] = defaultdict(list)

    def _prune(self, key: str) -> list[float]:
        cutoff = time.time() - self.window
        self.hits[key] = [t for t in self.hits[key] if t > cutoff]
        return self.hits[key]

    def blocked(self, key: str) -> bool:
        return len(self._prune(key)) >= self.limit

    def fail(self, key: str) -> None:
        self._prune(key).append(time.time())

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self.hits.clear()
        else:
            self.hits.pop(key, None)


login_throttle = Throttle(limit=5, window=900)      # per ip + username
ip_throttle = Throttle(limit=30, window=900)        # per ip, any username
