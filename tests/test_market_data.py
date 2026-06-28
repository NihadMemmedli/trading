from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from trading.data.market import (
    MarketDataError,
    OhlcvRequest,
    RawOhlcvBatch,
    RawTradeBatch,
    TradeRequest,
    normalize_symbol,
)
from trading.data.quality import (
    detect_duplicate_timestamps,
    detect_gaps,
    deterministic_dataset_hash,
    normalize_ohlcv_batch,
    normalize_trade_batch,
)


def test_ohlcv_request_normalizes_symbol_and_requires_supported_timeframe() -> None:
    request = OhlcvRequest(symbol="btc_usdt", timeframe="1m")

    assert request.exchange == "binance"
    assert request.symbol == "BTC/USDT"
    assert request.timeframe == "1m"

    with pytest.raises(ValidationError):
        OhlcvRequest(symbol="DOGE/USDT", timeframe="1m")
    with pytest.raises(ValidationError):
        OhlcvRequest(symbol="BTC/USDT", timeframe="30m")


def test_ohlcv_request_rejects_naive_and_future_timestamps() -> None:
    with pytest.raises(ValidationError):
        OhlcvRequest(symbol="BTC/USDT", timeframe="1m", since=datetime(2026, 1, 1))

    with pytest.raises(ValidationError):
        OhlcvRequest(
            symbol="BTC/USDT",
            timeframe="1m",
            since=datetime(2999, 1, 1, tzinfo=UTC),
        )


def test_trade_request_normalizes_symbol_and_rejects_unsupported_inputs() -> None:
    request = TradeRequest(symbol="btc_usdt")

    assert request.exchange == "binance"
    assert request.symbol == "BTC/USDT"

    with pytest.raises(ValidationError):
        TradeRequest(symbol="DOGE/USDT")
    with pytest.raises(ValidationError):
        TradeRequest(exchange="kraken", symbol="BTC/USDT")
    with pytest.raises(ValidationError):
        TradeRequest(symbol="BTC/USDT", timeframe="1m")  # type: ignore[call-arg]


def test_trade_request_rejects_naive_and_future_timestamps() -> None:
    with pytest.raises(ValidationError):
        TradeRequest(symbol="BTC/USDT", since=datetime(2026, 1, 1))

    with pytest.raises(ValidationError):
        TradeRequest(symbol="BTC/USDT", since=datetime(2999, 1, 1, tzinfo=UTC))


def test_symbol_normalization_is_deterministic() -> None:
    assert normalize_symbol(" eth-usdt ") == "ETH/USDT"
    assert normalize_symbol("sol_usdt") == "SOL/USDT"


def test_normalization_rejects_duplicate_and_future_candles() -> None:
    batch = RawOhlcvBatch(
        exchange="binance",
        symbol="BTC/USDT",
        timeframe="1m",
        rows=[
            ["2026-01-01T00:00:00Z", "1", "2", "1", "2", "10"],
            ["2026-01-01T00:00:00Z", "2", "3", "2", "3", "10"],
        ],
    )

    with pytest.raises(MarketDataError, match="duplicate"):
        normalize_ohlcv_batch(
            batch,
            raw_checksum="abc",
            now=datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
        )

    future_batch = RawOhlcvBatch(
        exchange="binance",
        symbol="BTC/USDT",
        timeframe="1m",
        rows=[["2999-01-01T00:00:00Z", "1", "2", "1", "2", "10"]],
    )
    with pytest.raises(MarketDataError, match="future"):
        normalize_ohlcv_batch(future_batch, raw_checksum="abc")


def test_normalization_rejects_invalid_ohlcv_ranges() -> None:
    batch = RawOhlcvBatch(
        exchange="binance",
        symbol="BTC/USDT",
        timeframe="1m",
        rows=[
            ["2026-01-01T00:00:00Z", "10", "9", "8", "9", "1"],
        ],
    )

    with pytest.raises(MarketDataError, match="high"):
        normalize_ohlcv_batch(
            batch,
            raw_checksum="abc",
            now=datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
        )

    negative_volume = RawOhlcvBatch(
        exchange="binance",
        symbol="BTC/USDT",
        timeframe="1m",
        rows=[
            ["2026-01-01T00:00:00Z", "8", "10", "7", "9", "-1"],
        ],
    )

    with pytest.raises(MarketDataError, match="nonnegative"):
        normalize_ohlcv_batch(
            negative_volume,
            raw_checksum="abc",
            now=datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
        )


def test_trade_normalization_rejects_duplicates_future_bad_side_and_negative_values() -> None:
    duplicate_batch = RawTradeBatch(
        exchange="binance",
        symbol="BTC/USDT",
        rows=[
            {
                "id": "trade-1",
                "timestamp": "2026-01-01T00:00:00Z",
                "side": "buy",
                "price": "1",
                "amount": "2",
            },
            {
                "id": "trade-1",
                "timestamp": "2026-01-01T00:00:01Z",
                "side": "sell",
                "price": "2",
                "amount": "1",
            },
        ],
    )
    with pytest.raises(MarketDataError, match="duplicate trade ids"):
        normalize_trade_batch(
            duplicate_batch,
            raw_checksum="abc",
            now=datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
        )

    future_batch = RawTradeBatch(
        exchange="binance",
        symbol="BTC/USDT",
        rows=[
            {
                "id": "trade-2",
                "timestamp": "2999-01-01T00:00:00Z",
                "side": "buy",
                "price": "1",
                "amount": "1",
            }
        ],
    )
    with pytest.raises(MarketDataError, match="future"):
        normalize_trade_batch(future_batch, raw_checksum="abc")

    bad_side = RawTradeBatch(
        exchange="binance",
        symbol="BTC/USDT",
        rows=[
            {
                "id": "trade-3",
                "timestamp": "2026-01-01T00:00:00Z",
                "side": "hold",
                "price": "1",
                "amount": "1",
            }
        ],
    )
    with pytest.raises(MarketDataError, match="side"):
        normalize_trade_batch(
            bad_side,
            raw_checksum="abc",
            now=datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
        )

    negative_price = RawTradeBatch(
        exchange="binance",
        symbol="BTC/USDT",
        rows=[
            {
                "id": "trade-4",
                "timestamp": "2026-01-01T00:00:00Z",
                "side": "buy",
                "price": "-1",
                "amount": "1",
            }
        ],
    )
    with pytest.raises(MarketDataError, match="nonnegative"):
        normalize_trade_batch(
            negative_price,
            raw_checksum="abc",
            now=datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
        )


def test_trade_normalization_generates_deterministic_missing_ids() -> None:
    batch = RawTradeBatch(
        exchange="binance",
        symbol="BTC/USDT",
        rows=[
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "side": "buy",
                "price": "1",
                "amount": "2",
            }
        ],
    )

    first = normalize_trade_batch(
        batch,
        raw_checksum="abc",
        now=datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
    )
    second = normalize_trade_batch(
        batch,
        raw_checksum="abc",
        now=datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
    )

    assert len(first[0].trade_id) == 64
    assert first[0].trade_id == second[0].trade_id


def test_gap_detection_and_dataset_hash_are_deterministic() -> None:
    timestamps = [
        datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 1, 0, 2, tzinfo=UTC),
    ]
    assert detect_duplicate_timestamps(timestamps + [timestamps[0]]) == [timestamps[0]]
    assert detect_gaps(timestamps, "1m") == [
        (
            datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
            datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
        )
    ]

    batch = RawOhlcvBatch(
        exchange="binance",
        symbol="BTC/USDT",
        timeframe="1m",
        rows=[
            ["2026-01-01T00:00:00Z", "1", "2", "1", "2", "10"],
            ["2026-01-01T00:02:00Z", "2", "3", "2", "3", "10"],
        ],
    )
    candles = normalize_ohlcv_batch(
        batch,
        raw_checksum="abc",
        now=datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
    )

    assert candles[0].quality_flags["gaps"][0]["from"] == "2026-01-01T00:01:00+00:00"
    assert deterministic_dataset_hash(candles) == deterministic_dataset_hash(
        list(reversed(candles))
    )
