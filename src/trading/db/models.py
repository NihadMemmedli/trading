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
    agent_reports: Mapped[list[AgentReport]] = relationship(back_populates="pair")
    trade_proposals: Mapped[list[TradeProposal]] = relationship(back_populates="pair")
    feature_rows: Mapped[list[FeatureRow]] = relationship(back_populates="pair")


class AgentReport(Base):
    __tablename__ = "agent_reports"
    __table_args__ = (
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="agent_report_confidence_valid",
        ),
        Index("ix_agent_reports_pair_timestamp", "pair_id", "timestamp"),
        Index("ix_agent_reports_agent_name", "agent_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pair_id: Mapped[int] = mapped_column(ForeignKey("trading_pairs.id"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    report_type: Mapped[str] = mapped_column(String(64), nullable=False, default="analyst_report")
    output_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    pair: Mapped[TradingPair] = relationship(back_populates="agent_reports")


class TradeProposal(Base):
    __tablename__ = "trade_proposals"
    __table_args__ = (
        CheckConstraint("side IN ('long', 'flat')", name="trade_proposal_side_valid"),
        CheckConstraint(
            "status IN ('pending_risk', 'flat', 'approved', 'rejected', 'reduced')",
            name="trade_proposal_status_valid",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="trade_proposal_confidence_valid",
        ),
        CheckConstraint("entry_price IS NULL OR entry_price > 0", name="entry_price_positive"),
        CheckConstraint("stop_loss IS NULL OR stop_loss > 0", name="stop_loss_positive"),
        Index("ix_trade_proposals_pair_timestamp_status", "pair_id", "timestamp", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pair_id: Mapped[int] = mapped_column(ForeignKey("trading_pairs.id"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    entry_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    take_profit_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    thesis: Mapped[str] = mapped_column(Text, nullable=False)
    invalidation: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    pair: Mapped[TradingPair] = relationship(back_populates="trade_proposals")
    risk_decision: Mapped[RiskDecision | None] = relationship(
        back_populates="proposal",
        cascade="all, delete-orphan",
    )


class RiskDecision(Base):
    __tablename__ = "risk_decisions"
    __table_args__ = (
        CheckConstraint("decision IN ('approve', 'reject', 'reduce')", name="risk_decision_valid"),
        CheckConstraint(
            "max_position_size IS NULL OR max_position_size >= 0",
            name="max_position_size_nonnegative",
        ),
        CheckConstraint(
            "max_loss_usd IS NULL OR max_loss_usd >= 0",
            name="max_loss_usd_nonnegative",
        ),
        Index("ix_risk_decisions_created_at", "created_at"),
        Index("ix_risk_decisions_decision_created_at", "decision", "created_at"),
    )

    proposal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("trade_proposals.id", ondelete="CASCADE"),
        primary_key=True,
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    max_position_size: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    max_loss_usd: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    violated_rules_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    warnings_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    inserted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    proposal: Mapped[TradeProposal] = relationship(back_populates="risk_decision")


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


class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    __table_args__ = (
        CheckConstraint("status IN ('succeeded', 'failed')", name="backtest_run_status_valid"),
        Index("ix_backtest_runs_status_created_at", "status", "created_at"),
        Index("ix_backtest_runs_exchange_symbol_timeframe", "exchange", "symbol", "timeframe"),
        Index("ix_backtest_runs_dataset_id", "dataset_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decision_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    initial_capital: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    fee_bps: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    slippage_bps: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(128), nullable=False)
    strategy_parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    dataset_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("datasets.id"),
        nullable=True,
    )
    dataset_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    config_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    report_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metrics_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    report_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    artifact_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    dataset: Mapped[Dataset | None] = relationship(back_populates="backtest_runs")
    trades: Mapped[list[BacktestTrade]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="BacktestTrade.timestamp, BacktestTrade.id",
    )
    equity_points: Mapped[list[BacktestEquityPoint]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="BacktestEquityPoint.timestamp",
    )
    events: Mapped[list[BacktestRunEvent]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="BacktestRunEvent.timestamp, BacktestRunEvent.id",
    )


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"
    __table_args__ = (
        CheckConstraint("side IN ('buy', 'sell')", name="backtest_trade_side_valid"),
        CheckConstraint("quantity >= 0", name="backtest_trade_quantity_nonnegative"),
        CheckConstraint("fill_price >= 0", name="backtest_trade_fill_price_nonnegative"),
        CheckConstraint("fee >= 0", name="backtest_trade_fee_nonnegative"),
        CheckConstraint("slippage >= 0", name="backtest_trade_slippage_nonnegative"),
        Index("ix_backtest_trades_run_id_timestamp", "run_id", "timestamp"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("backtest_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    fill_price: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    slippage: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    run: Mapped[BacktestRun] = relationship(back_populates="trades")


class BacktestEquityPoint(Base):
    __tablename__ = "backtest_equity_points"
    __table_args__ = (
        CheckConstraint("equity >= 0", name="backtest_equity_point_equity_nonnegative"),
        Index(
            "ix_backtest_equity_points_run_id_timestamp",
            "run_id",
            "timestamp",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("backtest_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    equity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    run: Mapped[BacktestRun] = relationship(back_populates="equity_points")


class BacktestRunEvent(Base):
    __tablename__ = "backtest_run_events"
    __table_args__ = (
        CheckConstraint(
            "level IN ('debug', 'info', 'warning', 'error')", name="backtest_event_level_valid"
        ),
        Index("ix_backtest_run_events_run_id_timestamp", "run_id", "timestamp"),
        Index("ix_backtest_run_events_event_type_created_at", "event_type", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("backtest_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    run: Mapped[BacktestRun] = relationship(back_populates="events")


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

    backtest_runs: Mapped[list[BacktestRun]] = relationship(back_populates="dataset")
    feature_sets: Mapped[list[FeatureSet]] = relationship(back_populates="dataset")
    split_definitions: Mapped[list[SplitDefinition]] = relationship(back_populates="dataset")
    model_experiments: Mapped[list[ModelExperiment]] = relationship(back_populates="dataset")


class FeatureSet(Base):
    __tablename__ = "feature_sets"
    __table_args__ = (
        UniqueConstraint("dataset_id", "name", "parameter_hash", "code_version"),
        Index("ix_feature_sets_dataset_id", "dataset_id"),
        Index("ix_feature_sets_hash", "feature_set_hash"),
        Index("ix_feature_sets_parameter_hash", "parameter_hash"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    dataset_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("datasets.id"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    dataset_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parameter_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    code_version: Mapped[str] = mapped_column(String(64), nullable=False)
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    feature_names_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    selector_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    output_location: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    dataset: Mapped[Dataset] = relationship(back_populates="feature_sets")
    rows: Mapped[list[FeatureRow]] = relationship(
        back_populates="feature_set",
        cascade="all, delete-orphan",
        order_by="FeatureRow.timestamp, FeatureRow.id",
    )
    split_definitions: Mapped[list[SplitDefinition]] = relationship(back_populates="feature_set")
    model_experiments: Mapped[list[ModelExperiment]] = relationship(back_populates="feature_set")


class SplitDefinition(Base):
    __tablename__ = "split_definitions"
    __table_args__ = (
        CheckConstraint(
            "split_type IN ('holdout', 'walk_forward')",
            name="split_definition_type_valid",
        ),
        UniqueConstraint("dataset_id", "feature_set_id", "name", "split_hash"),
        Index("ix_split_definitions_dataset_feature_set", "dataset_id", "feature_set_id"),
        Index("ix_split_definitions_hash", "split_hash"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    dataset_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("datasets.id"),
        nullable=False,
    )
    feature_set_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("feature_sets.id"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    split_type: Mapped[str] = mapped_column(String(32), nullable=False)
    split_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    dataset: Mapped[Dataset] = relationship(back_populates="split_definitions")
    feature_set: Mapped[FeatureSet] = relationship(back_populates="split_definitions")
    windows: Mapped[list[SplitWindow]] = relationship(
        back_populates="split_definition",
        cascade="all, delete-orphan",
        order_by="SplitWindow.window_index, SplitWindow.split_name, SplitWindow.id",
    )
    model_experiments: Mapped[list[ModelExperiment]] = relationship(
        back_populates="split_definition"
    )


class SplitWindow(Base):
    __tablename__ = "split_windows"
    __table_args__ = (
        CheckConstraint(
            "split_name IN ('train', 'validation', 'test')",
            name="split_window_name_valid",
        ),
        CheckConstraint("window_index >= 0", name="split_window_index_nonnegative"),
        CheckConstraint("start_at < end_at", name="split_window_range_valid"),
        CheckConstraint("end_at <= decision_time", name="split_window_decision_time_valid"),
        UniqueConstraint("split_definition_id", "window_index", "split_name"),
        Index(
            "ix_split_windows_definition_index_name",
            "split_definition_id",
            "window_index",
            "split_name",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    split_definition_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("split_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    window_index: Mapped[int] = mapped_column(Integer, nullable=False)
    split_name: Mapped[str] = mapped_column(String(32), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decision_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    split_definition: Mapped[SplitDefinition] = relationship(back_populates="windows")


class ModelExperiment(Base):
    __tablename__ = "model_experiments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('created', 'running', 'succeeded', 'failed')",
            name="model_experiment_status_valid",
        ),
        Index("ix_model_experiments_dataset_feature_set", "dataset_id", "feature_set_id"),
        Index("ix_model_experiments_split_definition_id", "split_definition_id"),
        Index("ix_model_experiments_status_created_at", "status", "created_at"),
        Index("ix_model_experiments_hash", "experiment_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("datasets.id"),
        nullable=False,
    )
    feature_set_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("feature_sets.id"),
        nullable=False,
    )
    split_definition_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("split_definitions.id"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    parameter_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    experiment_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    code_version: Mapped[str] = mapped_column(String(64), nullable=False)
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    dataset: Mapped[Dataset] = relationship(back_populates="model_experiments")
    feature_set: Mapped[FeatureSet] = relationship(back_populates="model_experiments")
    split_definition: Mapped[SplitDefinition] = relationship(back_populates="model_experiments")


class FeatureRow(Base):
    __tablename__ = "feature_rows"
    __table_args__ = (
        CheckConstraint(
            "available_at <= decision_time",
            name="feature_row_available_before_decision",
        ),
        UniqueConstraint(
            "feature_set_id",
            "pair_id",
            "timeframe",
            "timestamp",
            "decision_time",
        ),
        Index("ix_feature_rows_feature_set_timestamp", "feature_set_id", "timestamp"),
        Index(
            "ix_feature_rows_pair_timeframe_available_at",
            "pair_id",
            "timeframe",
            "available_at",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    feature_set_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("feature_sets.id", ondelete="CASCADE"),
        nullable=False,
    )
    pair_id: Mapped[int] = mapped_column(ForeignKey("trading_pairs.id"), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decision_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    features_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    feature_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    feature_set: Mapped[FeatureSet] = relationship(back_populates="rows")
    pair: Mapped[TradingPair] = relationship(back_populates="feature_rows")


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
