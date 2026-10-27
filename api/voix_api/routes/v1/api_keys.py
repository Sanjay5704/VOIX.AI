from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select

from voix_api.db import utcnow
from voix_api.errors import ApiError, not_found
from voix_api.models import ApiKey
from voix_api.schemas import ApiKeyCreatedOut, ApiKeyCreateIn, ApiKeyOut
from voix_api.security.credentials import generate_api_key
from voix_api.security.deps import DbDep, PrincipalDep, client_ip
from voix_api.services import audit

router = APIRouter(prefix="/api-keys", tags=["api keys"])

MAX_ACTIVE_KEYS = 10


@router.post("", response_model=ApiKeyCreatedOut, status_code=status.HTTP_201_CREATED)
def create_api_key(
    body: ApiKeyCreateIn, request: Request, db: DbDep, principal: PrincipalDep
) -> ApiKeyCreatedOut:
    active = db.scalars(
        select(ApiKey.id).where(ApiKey.user_id == principal.user_id, ApiKey.revoked_at.is_(None))
    ).all()
    if len(active) >= MAX_ACTIVE_KEYS:
        raise ApiError(
            409,
            "too_many_keys",
            f"At most {MAX_ACTIVE_KEYS} active API keys; revoke one first",
        )

    new = generate_api_key()
    key = ApiKey(
        user_id=principal.user_id,
        name=body.name,
        prefix=new.prefix,
        key_hash=new.key_hash,
    )
    db.add(key)
    db.flush()
    audit.record(
        db,
        "api_key.create",
        user_id=principal.user_id,
        target=str(key.id),
        ip=client_ip(request),
    )
    db.commit()
    return ApiKeyCreatedOut(**ApiKeyOut.model_validate(key).model_dump(), key=new.plaintext)


@router.get("", response_model=list[ApiKeyOut])
def list_api_keys(db: DbDep, principal: PrincipalDep) -> list[ApiKey]:
    return list(
        db.scalars(
            select(ApiKey).where(ApiKey.user_id == principal.user_id).order_by(ApiKey.created_at.desc())
        )
    )


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_api_key(key_id: uuid.UUID, request: Request, db: DbDep, principal: PrincipalDep) -> Response:
    key = db.get(ApiKey, key_id)
    if key is None or key.user_id != principal.user_id:
        raise not_found("API key")
    if key.revoked_at is None:
        key.revoked_at = utcnow()
        audit.record(
            db,
            "api_key.revoke",
            user_id=principal.user_id,
            target=str(key.id),
            ip=client_ip(request),
        )
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
