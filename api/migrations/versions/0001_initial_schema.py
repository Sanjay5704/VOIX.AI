"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-27 23:50:06.073656
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# JSONB on Postgres (indexable, compact), plain JSON elsewhere.
JSON_T = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
# SQLite only autoincrements INTEGER primary keys.
BIGINT_PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=100), nullable=False),
        sa.Column("plan", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_users_email"), ["email"], unique=True)

    op.create_table(
        "workers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("engines", JSON_T, nullable=False),
        sa.Column("gpu", sa.String(length=200), nullable=True),
        sa.Column("version", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    with op.batch_alter_table("workers", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_workers_last_seen_at"), ["last_seen_at"], unique=False)

    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prefix"),
    )
    with op.batch_alter_table("api_keys", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_api_keys_user_id"), ["user_id"], unique=False)

    op.create_table(
        "audit_log",
        sa.Column("id", BIGINT_PK, autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target", sa.String(length=200), nullable=True),
        sa.Column("meta", JSON_T, nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_audit_log_user_id"), ["user_id"], unique=False)

    op.create_table(
        "voices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("engine", sa.String(length=32), nullable=False),
        sa.Column("engine_voice_id", sa.String(length=100), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "ready",
                "failed",
                name="voice_status",
                native_enum=False,
                length=32,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("source_key", sa.String(length=300), nullable=True),
        sa.Column("reference_key", sa.String(length=300), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("consent_statement", sa.Text(), nullable=True),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consent_ip", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("engine", "engine_voice_id", name="uq_voices_engine_voice"),
    )
    with op.batch_alter_table("voices", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_voices_owner_id"), ["owner_id"], unique=False)

    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("voice_id", sa.Uuid(), nullable=True),
        sa.Column(
            "type",
            sa.Enum(
                "synthesize",
                "prepare_voice",
                name="job_type",
                native_enum=False,
                length=32,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "succeeded",
                "failed",
                "canceled",
                name="job_status",
                native_enum=False,
                length=32,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("engine", sa.String(length=32), nullable=False),
        sa.Column("params", JSON_T, nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("result", JSON_T, nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["voice_id"], ["voices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["worker_id"], ["workers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_jobs_user_idempotency"),
    )
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.create_index(
            "ix_jobs_claim",
            ["status", "engine", "priority", "created_at"],
            unique=False,
        )
        batch_op.create_index("ix_jobs_status_lease", ["status", "lease_expires_at"], unique=False)
        batch_op.create_index("ix_jobs_user_created", ["user_id", "created_at"], unique=False)

    op.create_table(
        "usage_events",
        sa.Column("id", BIGINT_PK, autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("engine", sa.String(length=32), nullable=False),
        sa.Column("chars", sa.Integer(), nullable=False),
        sa.Column("audio_seconds", sa.Float(), nullable=False),
        sa.Column("queue_ms", sa.Integer(), nullable=False),
        sa.Column("processing_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("usage_events", schema=None) as batch_op:
        batch_op.create_index("ix_usage_user_created", ["user_id", "created_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("usage_events", schema=None) as batch_op:
        batch_op.drop_index("ix_usage_user_created")

    op.drop_table("usage_events")
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_index("ix_jobs_user_created")
        batch_op.drop_index("ix_jobs_status_lease")
        batch_op.drop_index("ix_jobs_claim")

    op.drop_table("jobs")
    with op.batch_alter_table("voices", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_voices_owner_id"))

    op.drop_table("voices")
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_audit_log_user_id"))

    op.drop_table("audit_log")
    with op.batch_alter_table("api_keys", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_api_keys_user_id"))

    op.drop_table("api_keys")
    with op.batch_alter_table("workers", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_workers_last_seen_at"))

    op.drop_table("workers")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_email"))

    op.drop_table("users")
