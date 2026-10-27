from __future__ import annotations

import uuid
from datetime import timedelta

import jwt
from sqlalchemy import select

from voix_api.db import utcnow
from voix_api.models import ApiKey, AuditLog

from .conftest import register


def test_register_login_me(client):
    reg = register(client, email="Ada@Example.com")
    assert reg["user"]["email"] == "ada@example.com"  # normalised

    login = client.post(
        "/v1/auth/login", json={"email": "ADA@example.com", "password": "correct horse battery"}
    )
    assert login.status_code == 200
    me = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    assert me.status_code == 200 and me.json()["email"] == "ada@example.com"


def test_duplicate_email_rejected(client):
    register(client, email="dup@example.com")
    resp = client.post("/v1/auth/register", json={"email": "dup@example.com", "password": "another password"})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "email_taken"


def test_wrong_password_and_unknown_user_look_identical(client):
    register(client, email="bob@example.com")
    wrong = client.post("/v1/auth/login", json={"email": "bob@example.com", "password": "nope nope nope"})
    unknown = client.post("/v1/auth/login", json={"email": "ghost@example.com", "password": "nope nope nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_password_policy(client):
    assert (
        client.post("/v1/auth/register", json={"email": "a@example.com", "password": "short"}).status_code
        == 422
    )
    too_long = "é" * 40  # 80 bytes > bcrypt's 72-byte limit
    assert (
        client.post("/v1/auth/register", json={"email": "b@example.com", "password": too_long}).status_code
        == 422
    )


def test_missing_and_bad_credentials(client):
    assert client.get("/v1/auth/me").status_code == 401
    assert client.get("/v1/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    assert client.get("/v1/auth/me", headers={"X-API-Key": "not-a-key"}).status_code == 401


def test_expired_and_forged_jwt_rejected(client, settings, user):
    secret = settings.jwt_secret.get_secret_value()
    past = utcnow() - timedelta(hours=2)
    sub = user["user"]["id"]
    expired = jwt.encode(
        {"sub": sub, "iat": past, "exp": past + timedelta(minutes=1), "typ": "access"}, secret
    )
    forged = jwt.encode(
        {"sub": sub, "iat": utcnow(), "exp": utcnow() + timedelta(hours=1), "typ": "access"}, "x"
    )
    for token in (expired, forged):
        assert client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_api_key_lifecycle(client, db, user):
    created = client.post("/v1/api-keys", json={"name": "ci"}, headers=user["headers"])
    assert created.status_code == 201
    body = created.json()
    key = body["key"]
    assert key.startswith("vx_live_") and body["prefix"] in key

    # Only the hash is stored.
    row = db.get(ApiKey, uuid.UUID(body["id"]))
    assert key not in (row.key_hash, row.prefix) and len(row.key_hash) == 64

    # The key authenticates, and listing never returns the secret.
    assert client.get("/v1/auth/me", headers={"X-API-Key": key}).json()["id"] == user["user"]["id"]
    listed = client.get("/v1/api-keys", headers=user["headers"]).json()
    assert "key" not in listed[0] and listed[0]["last_used_at"] is not None

    # A tampered secret with a valid prefix fails.
    assert client.get("/v1/auth/me", headers={"X-API-Key": key[:-2] + "xx"}).status_code == 401

    assert client.delete(f"/v1/api-keys/{body['id']}", headers=user["headers"]).status_code == 204
    revoked = client.get("/v1/auth/me", headers={"X-API-Key": key})
    assert revoked.status_code == 401 and "revoked" in revoked.json()["error"]["message"]

    actions = set(db.scalars(select(AuditLog.action)))
    assert {"user.register", "api_key.create", "api_key.revoke"} <= actions


def test_cannot_revoke_someone_elses_key(client, user):
    other = register(client)
    key = client.post("/v1/api-keys", json={"name": "x"}, headers=user["headers"]).json()
    resp = client.delete(
        f"/v1/api-keys/{key['id']}", headers={"Authorization": f"Bearer {other['access_token']}"}
    )
    assert resp.status_code == 404


def test_worker_endpoints_require_worker_token(client, user):
    body = {"worker_name": "w1", "engines": ["mock"]}
    assert client.post("/internal/jobs/claim", json=body).status_code == 401
    assert (
        client.post("/internal/jobs/claim", json=body, headers={"X-Worker-Token": "wrong"}).status_code == 401
    )
    # A user's JWT is not a worker credential.
    assert client.post("/internal/jobs/claim", json=body, headers=user["headers"]).status_code == 401
