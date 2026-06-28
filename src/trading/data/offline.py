"""Offline market-data dataset loading for deterministic research and backtests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from trading.data.market import (
    NormalizedCandle,
    NormalizedOrderBookSnapshot,
    NormalizedTrade,
    RawOhlcvBatch,
    RawOrderBookBatch,
    RawTradeBatch,
    parse_timestamp,
    require_utc,
)
from trading.data.quality import (
    deterministic_dataset_hash,
    deterministic_order_book_dataset_hash,
    deterministic_trade_dataset_hash,
    normalize_ohlcv_batch,
    normalize_order_book_batch,
    normalize_trade_batch,
)


@dataclass(frozen=True)
class OhlcvFixtureSpec:
    path: Path
    symbol: str
    timeframe: str
    exchange: str = "binance"


@dataclass(frozen=True)
class TradeFixtureSpec:
    path: Path
    symbol: str
    exchange: str = "binance"


@dataclass(frozen=True)
class OrderBookFixtureSpec:
    path: Path
    symbol: str
    exchange: str = "binance"


@dataclass(frozen=True)
class OfflineOhlcvDataset:
    name: str
    decision_time: datetime
    candles: tuple[NormalizedCandle, ...]
    dataset_hash: str

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(sorted({candle.symbol for candle in self.candles}))


@dataclass(frozen=True)
class OfflineTradeDataset:
    name: str
    decision_time: datetime
    trades: tuple[NormalizedTrade, ...]
    dataset_hash: str

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(sorted({trade.symbol for trade in self.trades}))


@dataclass(frozen=True)
class OfflineOrderBookDataset:
    name: str
    decision_time: datetime
    snapshots: tuple[NormalizedOrderBookSnapshot, ...]
    dataset_hash: str

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(sorted({snapshot.symbol for snapshot in self.snapshots}))


def load_raw_ohlcv_jsonl(spec: OhlcvFixtureSpec, *, fetched_at: str) -> RawOhlcvBatch:
    rows: list[list[Any]] = []
    with spec.path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            item = json.loads(line)
            try:
                rows.append(
                    [
                        item["timestamp"],
                        item["open"],
                        item["high"],
                        item["low"],
                        item["close"],
                        item["volume"],
                    ]
                )
            except KeyError as exc:
                raise ValueError(f"{spec.path}:{line_number} is missing {exc.args[0]}") from exc

    return RawOhlcvBatch(
        exchange=spec.exchange,
        symbol=spec.symbol,
        timeframe=spec.timeframe,
        rows=rows,
        fetched_at=parse_timestamp(fetched_at, field_name="fetched_at"),
    )


def load_raw_trade_jsonl(spec: TradeFixtureSpec, *, fetched_at: str) -> RawTradeBatch:
    rows: list[dict[str, Any]] = []
    with spec.path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            item = json.loads(line)
            try:
                for required_field in ("id", "timestamp", "side", "price", "amount"):
                    item[required_field]
            except KeyError as exc:
                raise ValueError(f"{spec.path}:{line_number} is missing {exc.args[0]}") from exc
            rows.append(item)

    return RawTradeBatch(
        exchange=spec.exchange,
        symbol=spec.symbol,
        rows=rows,
        fetched_at=parse_timestamp(fetched_at, field_name="fetched_at"),
    )


def load_raw_order_book_jsonl(
    spec: OrderBookFixtureSpec,
    *,
    fetched_at: str,
) -> RawOrderBookBatch:
    rows: list[dict[str, Any]] = []
    with spec.path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            item = json.loads(line)
            try:
                item["bids"]
                item["asks"]
            except KeyError as exc:
                raise ValueError(f"{spec.path}:{line_number} is missing {exc.args[0]}") from exc
            rows.append(item)

    return RawOrderBookBatch(
        exchange=spec.exchange,
        symbol=spec.symbol,
        rows=rows,
        fetched_at=parse_timestamp(fetched_at, field_name="fetched_at"),
    )


def build_offline_ohlcv_dataset(
    *,
    name: str,
    fixtures: list[OhlcvFixtureSpec],
    decision_time: str,
) -> OfflineOhlcvDataset:
    parsed_decision_time = parse_timestamp(decision_time, field_name="decision_time")
    require_utc(parsed_decision_time, field_name="decision_time")

    candles: list[NormalizedCandle] = []
    for fixture in fixtures:
        raw_checksum = hashlib.sha256(fixture.path.read_bytes()).hexdigest()
        batch = load_raw_ohlcv_jsonl(fixture, fetched_at=decision_time)
        candles.extend(
            normalize_ohlcv_batch(
                batch,
                raw_checksum=raw_checksum,
                now=parsed_decision_time,
            )
        )

    sorted_candles = tuple(
        sorted(candles, key=lambda candle: (candle.symbol, candle.timeframe, candle.timestamp))
    )
    return OfflineOhlcvDataset(
        name=name,
        decision_time=parsed_decision_time,
        candles=sorted_candles,
        dataset_hash=deterministic_dataset_hash(list(sorted_candles)),
    )


def build_offline_trade_dataset(
    *,
    name: str,
    fixtures: list[TradeFixtureSpec],
    decision_time: str,
) -> OfflineTradeDataset:
    parsed_decision_time = parse_timestamp(decision_time, field_name="decision_time")
    require_utc(parsed_decision_time, field_name="decision_time")

    trades: list[NormalizedTrade] = []
    for fixture in fixtures:
        raw_checksum = hashlib.sha256(fixture.path.read_bytes()).hexdigest()
        batch = load_raw_trade_jsonl(fixture, fetched_at=decision_time)
        trades.extend(
            normalize_trade_batch(
                batch,
                raw_checksum=raw_checksum,
                now=parsed_decision_time,
            )
        )

    sorted_trades = tuple(
        sorted(trades, key=lambda trade: (trade.symbol, trade.timestamp, trade.trade_id))
    )
    return OfflineTradeDataset(
        name=name,
        decision_time=parsed_decision_time,
        trades=sorted_trades,
        dataset_hash=deterministic_trade_dataset_hash(list(sorted_trades)),
    )


def build_offline_order_book_dataset(
    *,
    name: str,
    fixtures: list[OrderBookFixtureSpec],
    decision_time: str,
) -> OfflineOrderBookDataset:
    parsed_decision_time = parse_timestamp(decision_time, field_name="decision_time")
    require_utc(parsed_decision_time, field_name="decision_time")

    snapshots: list[NormalizedOrderBookSnapshot] = []
    for fixture in fixtures:
        raw_checksum = hashlib.sha256(fixture.path.read_bytes()).hexdigest()
        batch = load_raw_order_book_jsonl(fixture, fetched_at=decision_time)
        snapshots.extend(
            normalize_order_book_batch(
                batch,
                raw_checksum=raw_checksum,
                now=parsed_decision_time,
            )
        )

    sorted_snapshots = tuple(
        sorted(snapshots, key=lambda snapshot: (snapshot.symbol, snapshot.timestamp))
    )
    return OfflineOrderBookDataset(
        name=name,
        decision_time=parsed_decision_time,
        snapshots=sorted_snapshots,
        dataset_hash=deterministic_order_book_dataset_hash(list(sorted_snapshots)),
    )
