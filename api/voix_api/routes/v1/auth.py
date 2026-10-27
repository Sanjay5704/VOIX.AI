from __future__ import annotations

from fastapi import APIRouter, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from voix_api.errors import ApiError
from voix_api.models import User
from voix_api.schemas import LoginIn, RegisterIn, TokenOut, UserOut
from voix_api.security.credentials import (
    burn_password_check,
    hash_password,
    issue_access_token,
    verify_password,
)
from voix_api.security.deps import DbDep, PrincipalDep, SettingsDep, client_ip
from voix_api.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_response(user: User, settings) -> TokenOut:
    token, ttl = issue_access_token(user.id, settings)
    return TokenOut(access_token=token, expires_in=ttl, user=UserOut.model_validate(user))


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, request: Request, db: DbDep, settings: SettingsDep) -> TokenOut:
    email = body.email.lower()
    user = User(email=email, password_hash=hash_password(body.password), plan="free")
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "email_taken", "An account with this email already exists") from None
    audit.record(db, "user.register", user_id=user.id, target=str(user.id), ip=client_ip(request))
    db.commit()
    return _token_response(user, settings)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: DbDep, settings: SettingsDep) -> TokenOut:
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None:
        burn_password_check(body.password)
        ok = False
    else:
        ok = verify_password(body.password, user.password_hash) and user.is_active
    if not ok:
        audit.record(
            db,
            "user.login_failed",
            user_id=user.id if user else None,
            ip=client_ip(request),
            email=body.email.lower(),
        )
        db.commit()
        raise ApiError(401, "invalid_credentials", "Incorrect email or password")
    audit.record(db, "user.login", user_id=user.id, ip=client_ip(request))
    db.commit()
    return _token_response(user, settings)


@router.get("/me", response_model=UserOut)
def me(principal: PrincipalDep) -> UserOut:
    return UserOut.model_validate(principal.user)
