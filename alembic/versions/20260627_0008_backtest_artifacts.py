"""add persisted backtest artifacts

Revision ID: 20260627_0008
Revises: 20260627_0007
Create Date: 2026-06-27 02:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260627_0008"
down_revision: str | None = "20260627_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backtest_trades",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("fill_price", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("fee", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("slippage", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("side IN ('buy', 'sell')", name="backtest_trade_side_valid"),
        sa.CheckConstraint("quantity >= 0", name="backtest_trade_quantity_nonnegative"),
        sa.CheckConstraint("fill_price >= 0", name="backtest_trade_fill_price_nonnegative"),
        sa.CheckConstraint("fee >= 0", name="backtest_trade_fee_nonnegative"),
        sa.CheckConstraint("slippage >= 0", name="backtest_trade_slippage_nonnegative"),
        sa.ForeignKeyConstraint(["run_id"], ["backtest_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_backtest_trades_run_id_timestamp",
        "backtest_trades",
        ["run_id", "timestamp"],
    )

    op.create_table(
        "backtest_equity_points",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("equity", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("equity >= 0", name="backtest_equity_point_equity_nonnegative"),
        sa.ForeignKeyConstraint(["run_id"], ["backtest_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_backtest_equity_points_run_id_timestamp",
        "backtest_equity_points",
        ["run_id", "timestamp"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_backtest_equity_points_run_id_timestamp",
        table_name="backtest_equity_points",
    )
    op.drop_table("backtest_equity_points")
    op.drop_index("ix_backtest_trades_run_id_timestamp", table_name="backtest_trades")
    op.drop_table("backtest_trades")
