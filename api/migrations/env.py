"""Alembic environment: uses DATABASE_URL from voix_api settings."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from voix_api import models  # noqa: F401  (registers tables on Base.metadata)
from voix_api.config import get_settings
from voix_api.db import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    return config.attributes.get("database_url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Tests may hand us an open connection; otherwise connect from settings.
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    with create_engine(_url(), poolclass=pool.NullPool).connect() as connection:
        _run(connection)


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
