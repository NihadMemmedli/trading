"""Deterministic market-data normalization and quality checks."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from trading.data.market import (
    TIMEFRAME_SECONDS,
    MarketDataError,
    NormalizedCandle,
    NormalizedTrade,
    RawOhlcvBatch,
    RawTradeBatch,
    parse_timestamp,
    utc_now,
)


def decimal_from_raw(value: Any, *, field_name: str) -> Decimal:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise MarketDataError(f"{field_name} must be decimal-compatible") from exc
    if not decimal.is_finite():
        raise MarketDataError(f"{field_name} must be finite")
    return decimal


def validate_ohlcv_range(
    *,
    open_: Decimal,
    high: Decimal,
    low: Decimal,
    close: Decimal,
    volume: Decimal,
) -> None:
    if min(open_, high, low, close, volume) < Decimal("0"):
        raise MarketDataError("OHLCV values must be nonnegative")
    if high < max(open_, close, low):
        raise MarketDataError("high must be at least open, close, and low")
    if low > min(open_, close, high):
        raise MarketDataError("low must be at most open, close, and high")


def validate_trade_values(*, price: Decimal, amount: Decimal) -> None:
    if min(price, amount) < Decimal("0"):
        raise MarketDataError("trade price and amount must be nonnegative")


def normalize_trade_side(value: Any) -> str:
    if not isinstance(value, str):
        raise MarketDataError("trade side must be buy or sell")
    side = value.strip().lower()
    if side not in {"buy", "sell"}:
        raise MarketDataError("trade side must be buy or sell")
    return side


def detect_duplicate_timestamps(timestamps: list[datetime]) -> list[datetime]:
    seen: set[datetime] = set()
    duplicates: list[datetime] = []
    for timestamp in timestamps:
        if timestamp in seen and timestamp not in duplicates:
            duplicates.append(timestamp)
        seen.add(timestamp)
    return duplicates


def detect_duplicate_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return duplicates


def detect_gaps(timestamps: list[datetime], timeframe: str) -> list[tuple[datetime, datetime]]:
    if len(timestamps) < 2:
        return []
    step = timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
    sorted_timestamps = sorted(timestamps)
    gaps: list[tuple[datetime, datetime]] = []
    for previous, current in zip(sorted_timestamps, sorted_timestamps[1:], strict=False):
        if current - previous > step:
            gaps.append((previous + step, current - step))
    return gaps


def normalize_ohlcv_batch(
    batch: RawOhlcvBatch,
    *,
    raw_checksum: str,
    now: datetime | None = None,
) -> list[NormalizedCandle]:
    available_at = (now or utc_now()).astimezone(UTC)
    rows = sorted(batch.rows, key=lambda row: row[0])
    timestamps: list[datetime] = []
    parsed_rows: list[tuple[datetime, list[Any]]] = []

    for index, row in enumerate(rows):
        if len(row) < 6:
            message = f"row {index} must contain timestamp, open, high, low, close, volume"
            raise MarketDataError(message)
        timestamp = parse_timestamp(row[0], field_name="timestamp")
        if timestamp > available_at:
            raise MarketDataError("future candles are not accepted")
        timestamps.append(timestamp)
        parsed_rows.append((timestamp, row))

    duplicates = detect_duplicate_timestamps(timestamps)
    if duplicates:
        joined = ", ".join(timestamp.isoformat() for timestamp in duplicates)
        raise MarketDataError(f"duplicate candle timestamps: {joined}")

    gaps = detect_gaps(timestamps, batch.timeframe)
    quality_flags: dict[str, Any] = {}
    if gaps:
        quality_flags["gaps"] = [
            {"from": start.isoformat(), "to": end.isoformat()} for start, end in gaps
        ]

    candles: list[NormalizedCandle] = []
    for timestamp, row in parsed_rows:
        open_ = decimal_from_raw(row[1], field_name="open")
        high = decimal_from_raw(row[2], field_name="high")
        low = decimal_from_raw(row[3], field_name="low")
        close = decimal_from_raw(row[4], field_name="close")
        volume = decimal_from_raw(row[5], field_name="volume")
        validate_ohlcv_range(open_=open_, high=high, low=low, close=close, volume=volume)
        candles.append(
            NormalizedCandle(
                exchange=batch.exchange,
                symbol=batch.symbol,
                timeframe=batch.timeframe,
                timestamp=timestamp,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
                available_at=available_at,
                raw_checksum=raw_checksum,
                quality_flags=quality_flags.copy(),
            )
        )
    return candles


def deterministic_dataset_hash(candles: list[NormalizedCandle]) -> str:
    digest = hashlib.sha256()
    for candle in sorted(candles, key=lambda item: (item.symbol, item.timeframe, item.timestamp)):
        line = "|".join(
            [
                candle.exchange,
                candle.symbol,
                candle.timeframe,
                candle.timestamp.isoformat(),
                str(candle.open),
                str(candle.high),
                str(candle.low),
                str(candle.close),
                str(candle.volume),
                candle.available_at.isoformat(),
                candle.raw_checksum,
            ]
        )
        digest.update(line.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def parse_trade_timestamp(row: dict[str, Any]) -> datetime:
    timestamp = row.get("timestamp")
    if timestamp is not None:
        return parse_timestamp(timestamp, field_name="timestamp")
    datetime_value = row.get("datetime")
    if datetime_value is not None:
        return parse_timestamp(datetime_value, field_name="datetime")
    raise MarketDataError("trade row must contain timestamp or datetime")


def deterministic_trade_id(
    *,
    exchange: str,
    symbol: str,
    timestamp: datetime,
    side: str,
    price: Decimal,
    amount: Decimal,
    raw_id: Any,
) -> str:
    if raw_id is not None and str(raw_id).strip():
        return str(raw_id).strip()

    payload = {
        "exchange": exchange,
        "symbol": symbol,
        "timestamp": timestamp.isoformat(),
        "side": side,
        "price": str(price),
        "amount": str(amount),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_trade_batch(
    batch: RawTradeBatch,
    *,
    raw_checksum: str,
    now: datetime | None = None,
) -> list[NormalizedTrade]:
    available_at = (now or utc_now()).astimezone(UTC)
    parsed_rows: list[tuple[datetime, str, NormalizedTrade]] = []
    trade_ids: list[str] = []

    for index, row in enumerate(batch.rows):
        timestamp = parse_trade_timestamp(row)
        if timestamp > available_at:
            raise MarketDataError("future trades are not accepted")

        price = decimal_from_raw(row.get("price"), field_name="price")
        amount = decimal_from_raw(row.get("amount"), field_name="amount")
        validate_trade_values(price=price, amount=amount)
        side = normalize_trade_side(row.get("side"))
        trade_id = deterministic_trade_id(
            exchange=batch.exchange,
            symbol=batch.symbol,
            timestamp=timestamp,
            side=side,
            price=price,
            amount=amount,
            raw_id=row.get("id"),
        )
        trade_ids.append(trade_id)
        try:
            trade = NormalizedTrade(
                exchange=batch.exchange,
                symbol=batch.symbol,
                trade_id=trade_id,
                timestamp=timestamp,
                side=side,
                price=price,
                amount=amount,
                available_at=available_at,
                raw_checksum=raw_checksum,
            )
        except ValueError as exc:
            raise MarketDataError(f"invalid trade row {index}: {exc}") from exc
        parsed_rows.append((timestamp, trade_id, trade))

    duplicates = detect_duplicate_values(trade_ids)
    if duplicates:
        joined = ", ".join(duplicates)
        raise MarketDataError(f"duplicate trade ids: {joined}")

    return [
        trade
        for _, _, trade in sorted(parsed_rows, key=lambda item: (item[0], item[1], item[2].side))
    ]


def deterministic_trade_dataset_hash(trades: list[NormalizedTrade]) -> str:
    digest = hashlib.sha256()
    for trade in sorted(trades, key=lambda item: (item.symbol, item.timestamp, item.trade_id)):
        line = "|".join(
            [
                trade.exchange,
                trade.symbol,
                trade.trade_id,
                trade.timestamp.isoformat(),
                trade.side,
                str(trade.price),
                str(trade.amount),
                trade.available_at.isoformat(),
                trade.raw_checksum,
            ]
        )
        digest.update(line.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()
