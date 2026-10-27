"""Password hashing, JWT issue/verify, API-key generation and hashing."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta

import bcrypt
import jwt

from voix_api.config import Settings
from voix_api.db import utcnow

API_KEY_PREFIX = "vx_live_"


# --- Passwords --------------------------------------------------------------


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


# A real hash to compare against when the email doesn't exist, so a login for
# an unknown user costs the same bcrypt time as a wrong password.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def burn_password_check(password: str) -> None:
    verify_password(password, _DUMMY_HASH)


# --- JWT --------------------------------------------------------------------


def issue_access_token(user_id: uuid.UUID, settings: Settings) -> tuple[str, int]:
    ttl = settings.jwt_ttl_minutes * 60
    now = utcnow()
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
        "typ": "access",
    }
    token = jwt.encode(
        payload,
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return token, ttl


def decode_access_token(token: str, settings: Settings) -> uuid.UUID | None:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp", "iat"]},
        )
        if payload.get("typ") != "access":
            return None
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError):
        return None


# --- API keys ---------------------------------------------------------------


@dataclass(frozen=True)
class NewApiKey:
    prefix: str
    plaintext: str
    key_hash: str


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def generate_api_key() -> NewApiKey:
    """`vx_live_<prefix>_<secret>`: the prefix is stored for lookup, the whole
    key only as sha256. High-entropy secrets don't need a slow KDF."""
    prefix = secrets.token_hex(4)
    plaintext = f"{API_KEY_PREFIX}{prefix}_{secrets.token_urlsafe(32)}"
    return NewApiKey(prefix=prefix, plaintext=plaintext, key_hash=sha256_hex(plaintext))


def parse_api_key_prefix(plaintext: str) -> str | None:
    if not plaintext.startswith(API_KEY_PREFIX):
        return None
    rest = plaintext[len(API_KEY_PREFIX) :]
    prefix, sep, secret = rest.partition("_")
    if not sep or len(prefix) != 8 or not secret:
        return None
    return prefix


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
