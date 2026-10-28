"""admin flag and benchmark runs

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

JSON_T = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table(
        "benchmark_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("host", sa.String(length=100), nullable=False),
        sa.Column("hardware", JSON_T, nullable=False),
        sa.Column("results", JSON_T, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_benchmark_runs_created_at", "benchmark_runs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_benchmark_runs_created_at", table_name="benchmark_runs")
    op.drop_table("benchmark_runs")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("is_admin")
