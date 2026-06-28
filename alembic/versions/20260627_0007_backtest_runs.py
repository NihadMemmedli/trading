"""add persisted backtest runs

Revision ID: 20260627_0007
Revises: 20260627_0006
Create Date: 2026-06-27 01:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260627_0007"
down_revision: str | None = "20260627_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("exchange", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("timeframe", sa.String(length=16), nullable=False),
        sa.Column("start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("initial_capital", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("fee_bps", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("slippage_bps", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("strategy_name", sa.String(length=128), nullable=False),
        sa.Column("strategy_parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("dataset_hash", sa.String(length=64), nullable=True),
        sa.Column("config_hash", sa.String(length=64), nullable=True),
        sa.Column("result_hash", sa.String(length=64), nullable=True),
        sa.Column("report_hash", sa.String(length=64), nullable=True),
        sa.Column("metrics_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("report_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("artifact_path", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed')",
            name="backtest_run_status_valid",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_backtest_runs_status_created_at",
        "backtest_runs",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_backtest_runs_exchange_symbol_timeframe",
        "backtest_runs",
        ["exchange", "symbol", "timeframe"],
    )


def downgrade() -> None:
    op.drop_index("ix_backtest_runs_exchange_symbol_timeframe", table_name="backtest_runs")
    op.drop_index("ix_backtest_runs_status_created_at", table_name="backtest_runs")
    op.drop_table("backtest_runs")
