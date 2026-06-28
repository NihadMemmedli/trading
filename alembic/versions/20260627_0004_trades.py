"""add public spot trades

Revision ID: 20260627_0004
Revises: 20260627_0003
Create Date: 2026-06-27 00:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260627_0004"
down_revision: str | None = "20260627_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trades",
        sa.Column("pair_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trade_id", sa.String(length=128), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("price", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("amount", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_checksum", sa.String(length=64), nullable=False),
        sa.Column("quality_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "inserted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("side IN ('buy', 'sell')", name="trade_side_valid"),
        sa.CheckConstraint("price >= 0", name="trade_price_nonnegative"),
        sa.CheckConstraint("amount >= 0", name="trade_amount_nonnegative"),
        sa.ForeignKeyConstraint(["pair_id"], ["trading_pairs.id"]),
        sa.PrimaryKeyConstraint("pair_id", "source", "timestamp", "trade_id"),
    )
    op.create_index(
        "ix_trades_pair_source_trade_id",
        "trades",
        ["pair_id", "source", "trade_id"],
    )
    op.create_index(
        "ix_trades_pair_source_timestamp",
        "trades",
        ["pair_id", "source", "timestamp"],
    )
    op.create_index(
        "ix_trades_pit_replay",
        "trades",
        ["pair_id", "source", "available_at", "timestamp"],
    )
    op.create_index("ix_trades_available_at", "trades", ["available_at"])
    op.execute("SELECT create_hypertable('trades', 'timestamp', if_not_exists => TRUE)")


def downgrade() -> None:
    op.drop_index("ix_trades_available_at", table_name="trades")
    op.drop_index("ix_trades_pit_replay", table_name="trades")
    op.drop_index("ix_trades_pair_source_timestamp", table_name="trades")
    op.drop_index("ix_trades_pair_source_trade_id", table_name="trades")
    op.drop_table("trades")
