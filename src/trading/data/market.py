"""Public market-data request and normalized DTOs."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ALLOWED_SYMBOLS = frozenset({"BTC/USDT", "ETH/USDT", "SOL/USDT"})
ALLOWED_TIMEFRAMES = frozenset({"1m", "5m", "15m", "1h", "4h", "1d"})
TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 5 * 60,
    "15m": 15 * 60,
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
    "1d": 24 * 60 * 60,
}


class IngestionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class MarketDataError(ValueError):
    """Raised when public market data cannot be validated or normalized."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def require_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise MarketDataError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def parse_timestamp(value: datetime | str | int | float, *, field_name: str) -> datetime:
    if isinstance(value, datetime):
        return require_utc(value, field_name=field_name)
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        return require_utc(datetime.fromisoformat(normalized), field_name=field_name)
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value / 1000, UTC)
    raise MarketDataError(f"{field_name} must be a datetime, ISO timestamp, or epoch ms")


def normalize_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper().replace("-", "/").replace("_", "/")
    if "/" not in normalized:
        raise MarketDataError("symbol must be BASE/QUOTE")
    base, quote = [part.strip() for part in normalized.split("/", maxsplit=1)]
    if not base or not quote:
        raise MarketDataError("symbol must include base and quote assets")
    return f"{base}/{quote}"


def validate_symbol(symbol: str) -> str:
    normalized = normalize_symbol(symbol)
    if normalized not in ALLOWED_SYMBOLS:
        raise MarketDataError(f"unsupported symbol: {normalized}")
    return normalized


def validate_timeframe(timeframe: str) -> str:
    normalized = timeframe.strip()
    if normalized not in ALLOWED_TIMEFRAMES:
        raise MarketDataError(f"unsupported timeframe: {timeframe}")
    return normalized


class OhlcvRequest(BaseModel):
    """Request for public spot OHLCV data."""

    model_config = ConfigDict(extra="forbid")

    exchange: str = Field(default="binance", min_length=1, max_length=64)
    symbol: str
    timeframe: str
    since: datetime | None = None
    until: datetime | None = None
    limit: int = Field(default=500, ge=1, le=1000)

    @field_validator("exchange")
    @classmethod
    def normalize_exchange(cls, value: str) -> str:
        exchange = value.strip().lower()
        if exchange != "binance":
            raise ValueError("only binance public spot OHLCV is supported in this phase")
        return exchange

    @field_validator("symbol")
    @classmethod
    def validate_request_symbol(cls, value: str) -> str:
        return validate_symbol(value)

    @field_validator("timeframe")
    @classmethod
    def validate_request_timeframe(cls, value: str) -> str:
        return validate_timeframe(value)

    @field_validator("since", "until")
    @classmethod
    def validate_datetime(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        parsed = require_utc(value, field_name="datetime")
        if parsed > utc_now():
            raise ValueError("timestamp cannot be in the future")
        return parsed

    @model_validator(mode="after")
    def validate_range(self) -> OhlcvRequest:
        if self.since is not None and self.until is not None and self.since >= self.until:
            raise ValueError("since must be earlier than until")
        return self


class TradeRequest(BaseModel):
    """Request for public spot trade data."""

    model_config = ConfigDict(extra="forbid")

    exchange: str = Field(default="binance", min_length=1, max_length=64)
    symbol: str
    since: datetime | None = None
    until: datetime | None = None
    limit: int = Field(default=500, ge=1, le=1000)

    @field_validator("exchange")
    @classmethod
    def normalize_exchange(cls, value: str) -> str:
        exchange = value.strip().lower()
        if exchange != "binance":
            raise ValueError("only binance public spot trades are supported in this phase")
        return exchange

    @field_validator("symbol")
    @classmethod
    def validate_request_symbol(cls, value: str) -> str:
        return validate_symbol(value)

    @field_validator("since", "until")
    @classmethod
    def validate_datetime(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        parsed = require_utc(value, field_name="datetime")
        if parsed > utc_now():
            raise ValueError("timestamp cannot be in the future")
        return parsed

    @model_validator(mode="after")
    def validate_range(self) -> TradeRequest:
        if self.since is not None and self.until is not None and self.since >= self.until:
            raise ValueError("since must be earlier than until")
        return self


class RawOhlcvBatch(BaseModel):
    """Raw public OHLCV rows as returned by an exchange adapter."""

    model_config = ConfigDict(extra="forbid")

    exchange: str
    symbol: str
    timeframe: str
    rows: list[list[Any]]
    fetched_at: datetime = Field(default_factory=utc_now)

    @field_validator("symbol")
    @classmethod
    def validate_batch_symbol(cls, value: str) -> str:
        return validate_symbol(value)

    @field_validator("timeframe")
    @classmethod
    def validate_batch_timeframe(cls, value: str) -> str:
        return validate_timeframe(value)

    @field_validator("fetched_at")
    @classmethod
    def validate_fetched_at(cls, value: datetime) -> datetime:
        return require_utc(value, field_name="fetched_at")


class RawTradeBatch(BaseModel):
    """Raw public trade rows as returned by an exchange adapter."""

    model_config = ConfigDict(extra="forbid")

    exchange: str
    symbol: str
    rows: list[dict[str, Any]]
    fetched_at: datetime = Field(default_factory=utc_now)

    @field_validator("symbol")
    @classmethod
    def validate_batch_symbol(cls, value: str) -> str:
        return validate_symbol(value)

    @field_validator("fetched_at")
    @classmethod
    def validate_fetched_at(cls, value: datetime) -> datetime:
        return require_utc(value, field_name="fetched_at")


class NormalizedCandle(BaseModel):
    """Normalized public OHLCV candle ready for persistence."""

    model_config = ConfigDict(extra="forbid")

    exchange: str
    symbol: str
    timeframe: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    available_at: datetime
    raw_checksum: str
    quality_flags: dict[str, Any] = Field(default_factory=dict)

    @field_validator("symbol")
    @classmethod
    def validate_candle_symbol(cls, value: str) -> str:
        return validate_symbol(value)

    @field_validator("timeframe")
    @classmethod
    def validate_candle_timeframe(cls, value: str) -> str:
        return validate_timeframe(value)

    @field_validator("timestamp", "available_at")
    @classmethod
    def validate_candle_datetime(cls, value: datetime) -> datetime:
        parsed = require_utc(value, field_name="candle timestamp")
        if parsed > utc_now():
            raise ValueError("candle timestamp cannot be in the future")
        return parsed

    @model_validator(mode="after")
    def validate_ohlcv(self) -> NormalizedCandle:
        if min(self.open, self.high, self.low, self.close, self.volume) < Decimal("0"):
            raise ValueError("OHLCV values must be nonnegative")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high must be at least open, close, and low")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low must be at most open, close, and high")
        if self.available_at < self.timestamp:
            raise ValueError("available_at cannot be earlier than timestamp")
        return self


class NormalizedTrade(BaseModel):
    """Normalized public trade ready for persistence."""

    model_config = ConfigDict(extra="forbid")

    exchange: str
    symbol: str
    trade_id: str = Field(min_length=1, max_length=128)
    timestamp: datetime
    side: str
    price: Decimal
    amount: Decimal
    available_at: datetime
    raw_checksum: str
    quality_flags: dict[str, Any] = Field(default_factory=dict)

    @field_validator("symbol")
    @classmethod
    def validate_trade_symbol(cls, value: str) -> str:
        return validate_symbol(value)

    @field_validator("side")
    @classmethod
    def validate_side(cls, value: str) -> str:
        side = value.strip().lower()
        if side not in {"buy", "sell"}:
            raise ValueError("trade side must be buy or sell")
        return side

    @field_validator("timestamp", "available_at")
    @classmethod
    def validate_trade_datetime(cls, value: datetime) -> datetime:
        parsed = require_utc(value, field_name="trade timestamp")
        if parsed > utc_now():
            raise ValueError("trade timestamp cannot be in the future")
        return parsed

    @model_validator(mode="after")
    def validate_trade_values(self) -> NormalizedTrade:
        if min(self.price, self.amount) < Decimal("0"):
            raise ValueError("trade price and amount must be nonnegative")
        if self.available_at < self.timestamp:
            raise ValueError("available_at cannot be earlier than timestamp")
        return self
