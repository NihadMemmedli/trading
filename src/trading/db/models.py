"""Market-data database models."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from trading.db.base import Base


class Exchange(Base):
    __tablename__ = "exchanges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    market_type: Mapped[str] = mapped_column(String(32), nullable=False, default="spot")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    pairs: Mapped[list[TradingPair]] = relationship(back_populates="exchange")


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TradingPair(Base):
    __tablename__ = "trading_pairs"
    __table_args__ = (
        UniqueConstraint("exchange_id", "symbol", "market_type"),
        Index("ix_trading_pairs_exchange_symbol", "exchange_id", "symbol"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exchange_id: Mapped[int] = mapped_column(ForeignKey("exchanges.id"), nullable=False)
    base_asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), nullable=False)
    quote_asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    market_type: Mapped[str] = mapped_column(String(32), nullable=False, default="spot")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    exchange: Mapped[Exchange] = relationship(back_populates="pairs")
    base_asset: Mapped[Asset] = relationship(foreign_keys=[base_asset_id])
    quote_asset: Mapped[Asset] = relationship(foreign_keys=[quote_asset_id])


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (
        Index("ix_ingestion_runs_status_created_at", "status", "created_at"),
        Index("ix_ingestion_runs_exchange_symbol_timeframe", "exchange", "symbol", "timeframe"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    exchange: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requested_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requested_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=500)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    rows_raw: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_normalized: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    artifacts: Mapped[list[RawArtifact]] = relationship(back_populates="run")


class RawArtifact(Base):
    __tablename__ = "raw_artifacts"
    __table_args__ = (Index("ix_raw_artifacts_run_id", "run_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingestion_runs.id"), nullable=True
    )
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    run: Mapped[IngestionRun | None] = relationship(back_populates="artifacts")


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (
        UniqueConstraint("name", "dataset_hash"),
        Index("ix_datasets_hash", "dataset_hash"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    dataset_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    artifact_id: Mapped[int | None] = mapped_column(ForeignKey("raw_artifacts.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Candle(Base):
    __tablename__ = "candles"
    __table_args__ = (
        CheckConstraint("high >= open AND high >= close AND high >= low", name="ohlc_high_valid"),
        CheckConstraint("low <= open AND low <= close AND low <= high", name="ohlc_low_valid"),
        CheckConstraint(
            "open >= 0 AND high >= 0 AND low >= 0 AND close >= 0", name="ohlc_nonnegative"
        ),
        CheckConstraint("volume >= 0", name="volume_nonnegative"),
        Index("ix_candles_pair_timeframe_timestamp", "pair_id", "timeframe", "timestamp"),
        Index(
            "ix_candles_pit_replay",
            "pair_id",
            "timeframe",
            "source",
            "available_at",
            "timestamp",
        ),
        Index("ix_candles_available_at", "available_at"),
    )

    pair_id: Mapped[int] = mapped_column(ForeignKey("trading_pairs.id"), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(16), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), primary_key=True)
    open: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    quality_flags: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    inserted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    pair: Mapped[TradingPair] = relationship()


class Trade(Base):
    __tablename__ = "trades"
    __table_args__ = (
        CheckConstraint("side IN ('buy', 'sell')", name="trade_side_valid"),
        CheckConstraint("price >= 0", name="trade_price_nonnegative"),
        CheckConstraint("amount >= 0", name="trade_amount_nonnegative"),
        Index("ix_trades_pair_source_trade_id", "pair_id", "source", "trade_id"),
        Index("ix_trades_pair_source_timestamp", "pair_id", "source", "timestamp"),
        Index("ix_trades_pit_replay", "pair_id", "source", "available_at", "timestamp"),
        Index("ix_trades_available_at", "available_at"),
    )

    pair_id: Mapped[int] = mapped_column(ForeignKey("trading_pairs.id"), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    trade_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    quality_flags: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    inserted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    pair: Mapped[TradingPair] = relationship()


class OrderBookSnapshot(Base):
    __tablename__ = "order_book_snapshots"
    __table_args__ = (
        CheckConstraint("best_bid > 0", name="order_book_best_bid_positive"),
        CheckConstraint("best_ask > best_bid", name="order_book_spread_positive"),
        CheckConstraint("spread_bps >= 0", name="order_book_spread_bps_nonnegative"),
        CheckConstraint("aggregate_bid_depth >= 0", name="order_book_bid_depth_nonnegative"),
        CheckConstraint("aggregate_ask_depth >= 0", name="order_book_ask_depth_nonnegative"),
        Index("ix_order_book_pair_source_timestamp", "pair_id", "source", "timestamp"),
        Index(
            "ix_order_book_pit_replay",
            "pair_id",
            "source",
            "available_at",
            "timestamp",
        ),
        Index("ix_order_book_available_at", "available_at"),
    )

    pair_id: Mapped[int] = mapped_column(ForeignKey("trading_pairs.id"), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    best_bid: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    best_ask: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    spread_bps: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    bids: Mapped[list[dict[str, str]]] = mapped_column(JSONB, nullable=False)
    asks: Mapped[list[dict[str, str]]] = mapped_column(JSONB, nullable=False)
    aggregate_bid_depth: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    aggregate_ask_depth: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    imbalance: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    quality_flags: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    inserted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    pair: Mapped[TradingPair] = relationship()


class DerivativesMetric(Base):
    __tablename__ = "derivatives_metrics"
    __table_args__ = (
        CheckConstraint("open_interest IS NULL OR open_interest >= 0", name="open_interest_valid"),
        CheckConstraint(
            "long_short_ratio IS NULL OR long_short_ratio >= 0",
            name="long_short_ratio_valid",
        ),
        CheckConstraint(
            "liquidation_long_volume IS NULL OR liquidation_long_volume >= 0",
            name="liquidation_long_volume_valid",
        ),
        CheckConstraint(
            "liquidation_short_volume IS NULL OR liquidation_short_volume >= 0",
            name="liquidation_short_volume_valid",
        ),
        Index(
            "ix_derivatives_metrics_pair_source_timestamp",
            "pair_id",
            "source",
            "timestamp",
        ),
        Index(
            "ix_derivatives_metrics_pit_replay",
            "pair_id",
            "source",
            "available_at",
            "timestamp",
        ),
        Index("ix_derivatives_metrics_available_at", "available_at"),
    )

    pair_id: Mapped[int] = mapped_column(ForeignKey("trading_pairs.id"), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    funding_rate: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    open_interest: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    long_short_ratio: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    liquidation_long_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    liquidation_short_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    quality_flags: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    inserted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    pair: Mapped[TradingPair] = relationship()
