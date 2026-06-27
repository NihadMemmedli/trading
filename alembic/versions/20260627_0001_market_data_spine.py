"""market data spine

Revision ID: 20260627_0001
Revises:
Create Date: 2026-06-27 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260627_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.create_table(
        "exchanges",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("market_type", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "assets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol"),
    )
    op.create_table(
        "ingestion_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exchange", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("timeframe", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("requested_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("rows_raw", sa.Integer(), nullable=False),
        sa.Column("rows_normalized", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ingestion_runs_exchange_symbol_timeframe",
        "ingestion_runs",
        ["exchange", "symbol", "timeframe"],
    )
    op.create_index(
        "ix_ingestion_runs_status_created_at", "ingestion_runs", ["status", "created_at"]
    )
    op.create_table(
        "trading_pairs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("exchange_id", sa.Integer(), nullable=False),
        sa.Column("base_asset_id", sa.Integer(), nullable=False),
        sa.Column("quote_asset_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("market_type", sa.String(length=32), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["base_asset_id"], ["assets.id"]),
        sa.ForeignKeyConstraint(["exchange_id"], ["exchanges.id"]),
        sa.ForeignKeyConstraint(["quote_asset_id"], ["assets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("exchange_id", "symbol", "market_type"),
    )
    op.create_index("ix_trading_pairs_exchange_symbol", "trading_pairs", ["exchange_id", "symbol"])
    op.create_table(
        "raw_artifacts",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("uri", sa.Text(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["run_id"], ["ingestion_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_raw_artifacts_run_id", "raw_artifacts", ["run_id"])
    op.create_table(
        "datasets",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("dataset_hash", sa.String(length=64), nullable=False),
        sa.Column("decision_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("artifact_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["artifact_id"], ["raw_artifacts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "dataset_hash"),
    )
    op.create_index("ix_datasets_hash", "datasets", ["dataset_hash"])
    op.create_table(
        "candles",
        sa.Column("pair_id", sa.Integer(), nullable=False),
        sa.Column("timeframe", sa.String(length=16), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("open", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("high", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("low", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("close", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("volume", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_checksum", sa.String(length=64), nullable=False),
        sa.Column("quality_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "inserted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "high >= open AND high >= close AND high >= low", name="ohlc_high_valid"
        ),
        sa.CheckConstraint("low <= open AND low <= close AND low <= high", name="ohlc_low_valid"),
        sa.CheckConstraint(
            "open >= 0 AND high >= 0 AND low >= 0 AND close >= 0", name="ohlc_nonnegative"
        ),
        sa.CheckConstraint("volume >= 0", name="volume_nonnegative"),
        sa.ForeignKeyConstraint(["pair_id"], ["trading_pairs.id"]),
        sa.PrimaryKeyConstraint("pair_id", "timeframe", "timestamp", "source"),
    )
    op.create_index("ix_candles_available_at", "candles", ["available_at"])
    op.create_index(
        "ix_candles_pair_timeframe_timestamp", "candles", ["pair_id", "timeframe", "timestamp"]
    )
    op.execute("SELECT create_hypertable('candles', 'timestamp', if_not_exists => TRUE)")


def downgrade() -> None:
    op.drop_index("ix_candles_pair_timeframe_timestamp", table_name="candles")
    op.drop_index("ix_candles_available_at", table_name="candles")
    op.drop_table("candles")
    op.drop_index("ix_datasets_hash", table_name="datasets")
    op.drop_table("datasets")
    op.drop_index("ix_raw_artifacts_run_id", table_name="raw_artifacts")
    op.drop_table("raw_artifacts")
    op.drop_index("ix_trading_pairs_exchange_symbol", table_name="trading_pairs")
    op.drop_table("trading_pairs")
    op.drop_index("ix_ingestion_runs_status_created_at", table_name="ingestion_runs")
    op.drop_index("ix_ingestion_runs_exchange_symbol_timeframe", table_name="ingestion_runs")
    op.drop_table("ingestion_runs")
    op.drop_table("assets")
    op.drop_table("exchanges")
