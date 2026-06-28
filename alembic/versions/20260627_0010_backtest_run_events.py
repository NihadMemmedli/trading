"""add backtest run events

Revision ID: 20260627_0010
Revises: 20260627_0009
Create Date: 2026-06-27 04:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260627_0010"
down_revision: str | None = "20260627_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backtest_run_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "level IN ('debug', 'info', 'warning', 'error')",
            name="backtest_event_level_valid",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["backtest_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_backtest_run_events_run_id_timestamp",
        "backtest_run_events",
        ["run_id", "timestamp"],
    )
    op.create_index(
        "ix_backtest_run_events_event_type_created_at",
        "backtest_run_events",
        ["event_type", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_backtest_run_events_event_type_created_at",
        table_name="backtest_run_events",
    )
    op.drop_index(
        "ix_backtest_run_events_run_id_timestamp",
        table_name="backtest_run_events",
    )
    op.drop_table("backtest_run_events")
