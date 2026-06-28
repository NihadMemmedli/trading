"""Pydantic schemas for persisted backtest run endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading.backtesting import BacktestRunStatus
from trading.data.market import require_exact_utc, require_utc, validate_symbol, validate_timeframe
from trading.db.models import BacktestRun
from trading.services.backtests import BacktestRunRequest


class BacktestRunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exchange: str = Field(default="binance", min_length=1, max_length=64)
    symbol: str
    timeframe: str
    start: datetime
    end: datetime
    decision_time: datetime
    generated_at: datetime
    initial_capital: Decimal = Field(gt=Decimal("0"))
    fee_bps: Decimal = Field(ge=Decimal("0"))
    slippage_bps: Decimal = Field(ge=Decimal("0"))
    strategy_name: str = Field(default="moving_average_crossover", min_length=1, max_length=128)
    strategy_parameters: dict[str, Any]

    @field_validator("exchange")
    @classmethod
    def normalize_exchange(cls, value: str) -> str:
        exchange = value.strip().lower()
        if exchange != "binance":
            raise ValueError("only binance public spot candles are supported for backtests")
        return exchange

    @field_validator("symbol")
    @classmethod
    def validate_request_symbol(cls, value: str) -> str:
        return validate_symbol(value)

    @field_validator("timeframe")
    @classmethod
    def validate_request_timeframe(cls, value: str) -> str:
        return validate_timeframe(value)

    @field_validator("start", "end", "decision_time")
    @classmethod
    def validate_datetime(cls, value: datetime) -> datetime:
        return require_utc(value, field_name="datetime")

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: datetime) -> datetime:
        return require_exact_utc(value, field_name="generated_at")

    @model_validator(mode="after")
    def validate_range(self) -> BacktestRunCreateRequest:
        if self.start >= self.end:
            raise ValueError("start must be earlier than end")
        return self

    def to_service_request(self) -> BacktestRunRequest:
        return BacktestRunRequest(
            exchange=self.exchange,
            symbol=self.symbol,
            timeframe=self.timeframe,
            start=self.start,
            end=self.end,
            decision_time=self.decision_time,
            generated_at=self.generated_at,
            initial_capital=self.initial_capital,
            fee_bps=self.fee_bps,
            slippage_bps=self.slippage_bps,
            strategy_name=self.strategy_name,
            strategy_parameters=self.strategy_parameters,
        )


class BacktestRunResponse(BaseModel):
    id: uuid.UUID
    status: BacktestRunStatus
    exchange: str
    symbol: str
    timeframe: str
    start: datetime
    end: datetime
    decision_time: datetime
    generated_at: datetime
    initial_capital: Decimal
    fee_bps: Decimal
    slippage_bps: Decimal
    strategy_name: str
    strategy_parameters: dict[str, Any]
    dataset_hash: str | None
    config_hash: str | None
    result_hash: str | None
    report_hash: str | None
    metrics: dict[str, Any] | None
    artifact_path: str | None
    started_at: datetime
    completed_at: datetime
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_run(cls, run: BacktestRun) -> BacktestRunResponse:
        return cls(
            id=run.id,
            status=BacktestRunStatus(run.status),
            exchange=run.exchange,
            symbol=run.symbol,
            timeframe=run.timeframe,
            start=run.start,
            end=run.end,
            decision_time=run.decision_time,
            generated_at=run.generated_at,
            initial_capital=run.initial_capital,
            fee_bps=run.fee_bps,
            slippage_bps=run.slippage_bps,
            strategy_name=run.strategy_name,
            strategy_parameters=run.strategy_parameters,
            dataset_hash=run.dataset_hash,
            config_hash=run.config_hash,
            result_hash=run.result_hash,
            report_hash=run.report_hash,
            metrics=run.metrics_json,
            artifact_path=run.artifact_path,
            started_at=run.started_at,
            completed_at=run.completed_at,
            error_message=run.error_message,
            created_at=run.created_at,
            updated_at=run.updated_at,
        )


class BacktestRunListResponse(BaseModel):
    runs: list[BacktestRunResponse] = Field(default_factory=list)
