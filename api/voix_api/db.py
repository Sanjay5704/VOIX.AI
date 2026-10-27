"""Database engine/session wiring and shared column types."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on every backend.

    Postgres stores `timestamptz` natively; SQLite drops tzinfo, so values are
    normalised to UTC on the way in and re-tagged as UTC on the way out.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        value = value.astimezone(UTC)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def init_engine(url: str) -> Engine:
    """(Re)create the global engine. Called at app startup and by tests."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()

    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    _engine = create_engine(url, **kwargs)

    if url.startswith("sqlite"):

        @event.listens_for(_engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Database engine not initialised; call init_engine() first")
    return _engine


def session_factory() -> sessionmaker[Session]:
    if _SessionLocal is None:
        raise RuntimeError("Database engine not initialised; call init_engine() first")
    return _SessionLocal


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, rolled back on error."""
    db = session_factory()()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
