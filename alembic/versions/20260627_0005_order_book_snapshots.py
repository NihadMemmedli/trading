"""add public spot order book snapshots

Revision ID: 20260627_0005
Revises: 20260627_0004
Create Date: 2026-06-27 00:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260627_0005"
down_revision: str | None = "20260627_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "order_book_snapshots",
        sa.Column("pair_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("best_bid", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("best_ask", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("spread_bps", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("bids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("asks", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("aggregate_bid_depth", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("aggregate_ask_depth", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("imbalance", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_checksum", sa.String(length=64), nullable=False),
        sa.Column("quality_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "inserted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("best_bid > 0", name="order_book_best_bid_positive"),
        sa.CheckConstraint("best_ask > best_bid", name="order_book_spread_positive"),
        sa.CheckConstraint("spread_bps >= 0", name="order_book_spread_bps_nonnegative"),
        sa.CheckConstraint("aggregate_bid_depth >= 0", name="order_book_bid_depth_nonnegative"),
        sa.CheckConstraint("aggregate_ask_depth >= 0", name="order_book_ask_depth_nonnegative"),
        sa.ForeignKeyConstraint(["pair_id"], ["trading_pairs.id"]),
        sa.PrimaryKeyConstraint("pair_id", "source", "timestamp"),
    )
    op.create_index(
        "ix_order_book_pair_source_timestamp",
        "order_book_snapshots",
        ["pair_id", "source", "timestamp"],
    )
    op.create_index(
        "ix_order_book_pit_replay",
        "order_book_snapshots",
        ["pair_id", "source", "available_at", "timestamp"],
    )
    op.create_index("ix_order_book_available_at", "order_book_snapshots", ["available_at"])
    op.execute(
        "SELECT create_hypertable('order_book_snapshots', 'timestamp', if_not_exists => TRUE)"
    )


def downgrade() -> None:
    op.drop_index("ix_order_book_available_at", table_name="order_book_snapshots")
    op.drop_index("ix_order_book_pit_replay", table_name="order_book_snapshots")
    op.drop_index("ix_order_book_pair_source_timestamp", table_name="order_book_snapshots")
    op.drop_table("order_book_snapshots")
