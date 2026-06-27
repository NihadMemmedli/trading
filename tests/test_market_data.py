from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from trading.data.market import MarketDataError, OhlcvRequest, RawOhlcvBatch, normalize_symbol
from trading.data.quality import (
    detect_duplicate_timestamps,
    detect_gaps,
    deterministic_dataset_hash,
    normalize_ohlcv_batch,
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
