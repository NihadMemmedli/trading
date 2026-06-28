"""add research derivatives metrics

Revision ID: 20260627_0006
Revises: 20260627_0005
Create Date: 2026-06-27 00:50:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260627_0006"
down_revision: str | None = "20260627_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "derivatives_metrics",
        sa.Column("pair_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("funding_rate", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("open_interest", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("long_short_ratio", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("liquidation_long_volume", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("liquidation_short_volume", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_checksum", sa.String(length=64), nullable=False),
        sa.Column("quality_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "inserted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "open_interest IS NULL OR open_interest >= 0",
            name="open_interest_valid",
        ),
        sa.CheckConstraint(
            "long_short_ratio IS NULL OR long_short_ratio >= 0",
            name="long_short_ratio_valid",
        ),
        sa.CheckConstraint(
            "liquidation_long_volume IS NULL OR liquidation_long_volume >= 0",
            name="liquidation_long_volume_valid",
        ),
        sa.CheckConstraint(
            "liquidation_short_volume IS NULL OR liquidation_short_volume >= 0",
            name="liquidation_short_volume_valid",
        ),
        sa.ForeignKeyConstraint(["pair_id"], ["trading_pairs.id"]),
        sa.PrimaryKeyConstraint("pair_id", "source", "timestamp"),
    )
    op.create_index(
        "ix_derivatives_metrics_pair_source_timestamp",
        "derivatives_metrics",
        ["pair_id", "source", "timestamp"],
    )
    op.create_index(
        "ix_derivatives_metrics_pit_replay",
        "derivatives_metrics",
        ["pair_id", "source", "available_at", "timestamp"],
    )
    op.create_index(
        "ix_derivatives_metrics_available_at",
        "derivatives_metrics",
        ["available_at"],
    )
    op.execute(
        "SELECT create_hypertable('derivatives_metrics', 'timestamp', if_not_exists => TRUE)"
    )


def downgrade() -> None:
    op.drop_index("ix_derivatives_metrics_available_at", table_name="derivatives_metrics")
    op.drop_index("ix_derivatives_metrics_pit_replay", table_name="derivatives_metrics")
    op.drop_index(
        "ix_derivatives_metrics_pair_source_timestamp",
        table_name="derivatives_metrics",
    )
    op.drop_table("derivatives_metrics")
