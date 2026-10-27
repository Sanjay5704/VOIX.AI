"""Test fixtures.

Database: Postgres when TEST_DATABASE_URL is set (schema built by running the
Alembic migrations, so they are tested too), otherwise a throwaway SQLite file
(schema from metadata).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from voix_api.config import Settings, get_settings
from voix_api.db import Base, init_engine, session_factory
from voix_api.main import create_app
from voix_api.models import User
from voix_api.security.credentials import hash_password
from voix_api.services.storage import LocalStorage, get_storage

API_DIR = Path(__file__).resolve().parents[1]
WORKER_TOKEN = "test-worker-token"


def _database_url(tmp_path: Path) -> str:
    return os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{(tmp_path / 'test.sqlite3').as_posix()}"


def _build_schema(url: str) -> None:
    engine = init_engine(url)
    if url.startswith("postgresql"):
        from alembic import command
        from alembic.config import Config

        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
        cfg = Config(str(API_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(API_DIR / "migrations"))
        cfg.attributes["database_url"] = url
        command.upgrade(cfg, "head")
    else:
        Base.metadata.create_all(engine)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        database_url=_database_url(tmp_path),
        local_storage_dir=tmp_path / "storage",
        worker_token=WORKER_TOKEN,
        enabled_engines=["mock", "kokoro", "xtts"],
        clone_engine="mock",
        rate_limit_jobs_per_minute=100,
        lease_seconds=60,
        retry_backoff_seconds=0,
    )


@pytest.fixture
def app(settings: Settings):
    _build_schema(settings.database_url)
    application = create_app(settings)
    storage = LocalStorage(settings.local_storage_dir)
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_storage] = lambda: storage
    application.state.storage = storage
    return application


@pytest.fixture
def client(app) -> Iterator[TestClient]:
    with TestClient(app) as c:  # runs lifespan: engine init + system voice seeding
        yield c


@pytest.fixture
def db(client) -> Iterator[Session]:
    with session_factory()() as session:
        yield session


@pytest.fixture
def worker_headers() -> dict[str, str]:
    return {"X-Worker-Token": WORKER_TOKEN}


def register(client: TestClient, email: str | None = None, password: str = "correct horse battery") -> dict:
    email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
    resp = client.post("/v1/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
def user(client) -> dict:
    data = register(client)
    data["headers"] = {"Authorization": f"Bearer {data['access_token']}"}
    return data


def voice_id(client: TestClient, headers: dict, engine: str = "mock") -> str:
    voices = client.get("/v1/voices", headers=headers).json()
    return next(v["id"] for v in voices if v["engine"] == engine and v["is_system"])


def make_user(db: Session, plan: str = "free") -> User:
    user = User(
        email=f"{uuid.uuid4().hex[:10]}@example.com", password_hash=hash_password("x" * 10), plan=plan
    )
    db.add(user)
    db.commit()
    return user
