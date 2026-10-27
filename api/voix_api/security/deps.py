"""FastAPI auth dependencies.

`get_principal` is the single entry point for user auth: it accepts either a
dashboard JWT (`Authorization: Bearer ...`) or a developer API key
(`X-API-Key: vx_live_...`). Worker endpoints use `require_worker` instead.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated, Literal

from fastapi import Depends, Header, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from voix_api.config import Settings, get_settings
from voix_api.db import get_db, utcnow
from voix_api.errors import ApiError
from voix_api.models import ApiKey, User
from voix_api.security.credentials import (
    constant_time_equals,
    decode_access_token,
    parse_api_key_prefix,
    sha256_hex,
)

# auto_error=False: we decide which of the two schemes applies ourselves.
_bearer = HTTPBearer(auto_error=False, description="JWT from /v1/auth/login")
_api_key = APIKeyHeader(name="X-API-Key", auto_error=False, description="API key (vx_live_...)")

_LAST_USED_RESOLUTION = timedelta(minutes=1)

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[Session, Depends(get_db)]


@dataclass
class Principal:
    user: User
    via: Literal["jwt", "api_key"]
    api_key_id: uuid.UUID | None = None

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id


def _unauthorized(message: str) -> ApiError:
    return ApiError(401, "unauthorized", message, headers={"WWW-Authenticate": "Bearer"})


def get_principal(
    db: DbDep,
    settings: SettingsDep,
    bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    api_key: Annotated[str | None, Depends(_api_key)],
) -> Principal:
    if api_key:
        return _principal_from_api_key(db, api_key)
    if bearer:
        user_id = decode_access_token(bearer.credentials, settings)
        if user_id is None:
            raise _unauthorized("Invalid or expired token")
        user = db.get(User, user_id)
        if user is None or not user.is_active:
            raise _unauthorized("User not found or disabled")
        return Principal(user=user, via="jwt")
    raise _unauthorized("Missing credentials: send a Bearer token or X-API-Key")


def _principal_from_api_key(db: Session, plaintext: str) -> Principal:
    prefix = parse_api_key_prefix(plaintext)
    if prefix is None:
        raise _unauthorized("Malformed API key")
    key = db.scalar(select(ApiKey).where(ApiKey.prefix == prefix))
    if key is None or not constant_time_equals(key.key_hash, sha256_hex(plaintext)):
        raise _unauthorized("Invalid API key")
    if key.revoked_at is not None:
        raise _unauthorized("API key has been revoked")
    if not key.user.is_active:
        raise _unauthorized("User disabled")

    now = utcnow()
    # Throttle the write: a busy key shouldn't update its row on every request.
    if key.last_used_at is None or now - key.last_used_at > _LAST_USED_RESOLUTION:
        key.last_used_at = now
        db.commit()
    return Principal(user=key.user, via="api_key", api_key_id=key.id)


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def require_worker(
    settings: SettingsDep,
    x_worker_token: Annotated[str | None, Header()] = None,
) -> None:
    expected = settings.worker_token.get_secret_value()
    if not x_worker_token or not constant_time_equals(x_worker_token, expected):
        raise ApiError(401, "unauthorized", "Invalid worker token")


def client_ip(request: Request) -> str | None:
    # Behind a PaaS proxy the real client is the first X-Forwarded-For hop.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return request.client.host if request.client else None
