from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from trading.data.market import (
    DerivativesMetricRequest,
    MarketDataError,
    OhlcvRequest,
    OrderBookRequest,
    RawDerivativesMetricBatch,
    RawOhlcvBatch,
    RawOrderBookBatch,
    RawTradeBatch,
    TradeRequest,
    normalize_symbol,
)
from trading.data.quality import (
    detect_duplicate_timestamps,
    detect_gaps,
    deterministic_dataset_hash,
    deterministic_derivatives_metric_dataset_hash,
    deterministic_order_book_dataset_hash,
    normalize_derivatives_metric_batch,
    normalize_ohlcv_batch,
    normalize_order_book_batch,
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


def test_order_book_request_normalizes_symbol_and_enforces_top_20() -> None:
    request = OrderBookRequest(symbol="btc_usdt")

    assert request.exchange == "binance"
    assert request.symbol == "BTC/USDT"
    assert request.limit == 20

    with pytest.raises(ValidationError):
        OrderBookRequest(symbol="DOGE/USDT")
    with pytest.raises(ValidationError):
        OrderBookRequest(exchange="kraken", symbol="BTC/USDT")
    with pytest.raises(ValidationError):
        OrderBookRequest(symbol="BTC/USDT", limit=10)


def test_derivatives_metric_request_normalizes_symbol_and_rejects_unsupported_inputs() -> None:
    request = DerivativesMetricRequest(symbol="btc_usdt")

    assert request.exchange == "binance"
    assert request.symbol == "BTC/USDT"
    assert request.limit == 500

    with pytest.raises(ValidationError):
        DerivativesMetricRequest(symbol="DOGE/USDT")
    with pytest.raises(ValidationError):
        DerivativesMetricRequest(exchange="kraken", symbol="BTC/USDT")
    with pytest.raises(ValidationError):
        DerivativesMetricRequest(symbol="BTC/USDT", timeframe="1m")  # type: ignore[call-arg]


def test_derivatives_metric_request_rejects_naive_future_and_invalid_ranges() -> None:
    with pytest.raises(ValidationError):
        DerivativesMetricRequest(symbol="BTC/USDT", since=datetime(2026, 1, 1))

    with pytest.raises(ValidationError):
        DerivativesMetricRequest(symbol="BTC/USDT", since=datetime(2999, 1, 1, tzinfo=UTC))

    with pytest.raises(ValidationError):
        DerivativesMetricRequest(
            symbol="BTC/USDT",
            since=datetime(2026, 1, 1, 1, 0, tzinfo=UTC),
            until=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
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


def order_book_row(
    *,
    timestamp: str = "2026-01-01T00:00:10Z",
    best_bid: str = "100.00",
    best_ask: str = "100.10",
) -> dict[str, object]:
    bid_start = Decimal(best_bid)
    ask_start = Decimal(best_ask)
    return {
        "timestamp": timestamp,
        "datetime": timestamp,
        "nonce": 1,
        "bids": [
            [str(bid_start - Decimal(index) / Decimal("100")), str(Decimal(index + 1))]
            for index in range(20)
        ],
        "asks": [
            [str(ask_start + Decimal(index) / Decimal("100")), str(Decimal(index + 2))]
            for index in range(20)
        ],
    }


def test_order_book_normalization_rejects_empty_crossed_negative_future_and_non_utc() -> None:
    now = datetime(2026, 1, 1, 0, 5, tzinfo=UTC)

    empty = RawOrderBookBatch(
        exchange="binance",
        symbol="BTC/USDT",
        rows=[{"timestamp": "2026-01-01T00:00:10Z", "bids": [], "asks": []}],
    )
    with pytest.raises(MarketDataError, match="nonempty"):
        normalize_order_book_batch(empty, raw_checksum="abc", now=now)

    crossed = RawOrderBookBatch(
        exchange="binance",
        symbol="BTC/USDT",
        rows=[order_book_row(best_bid="101", best_ask="100")],
    )
    with pytest.raises(MarketDataError, match="crossed"):
        normalize_order_book_batch(crossed, raw_checksum="abc", now=now)

    negative = order_book_row()
    negative["bids"][0][1] = "-1"  # type: ignore[index]
    with pytest.raises(MarketDataError, match="nonnegative"):
        normalize_order_book_batch(
            RawOrderBookBatch(exchange="binance", symbol="BTC/USDT", rows=[negative]),
            raw_checksum="abc",
            now=now,
        )

    future = RawOrderBookBatch(
        exchange="binance",
        symbol="BTC/USDT",
        rows=[order_book_row(timestamp="2999-01-01T00:00:00Z")],
    )
    with pytest.raises(MarketDataError, match="future"):
        normalize_order_book_batch(future, raw_checksum="abc")

    non_utc = RawOrderBookBatch(
        exchange="binance",
        symbol="BTC/USDT",
        rows=[order_book_row(timestamp="2026-01-01T04:00:10+04:00")],
    )
    with pytest.raises(MarketDataError, match="UTC"):
        normalize_order_book_batch(non_utc, raw_checksum="abc", now=now)


def test_order_book_normalization_metrics_and_hash_are_deterministic() -> None:
    batch = RawOrderBookBatch(
        exchange="binance",
        symbol="BTC/USDT",
        rows=[order_book_row(best_bid="100", best_ask="101")],
    )

    snapshots = normalize_order_book_batch(
        batch,
        raw_checksum="abc",
        now=datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
    )
    snapshot = snapshots[0]

    assert len(snapshot.bids) == 20
    assert len(snapshot.asks) == 20
    assert snapshot.best_bid == Decimal("100")
    assert snapshot.best_ask == Decimal("101")
    assert snapshot.spread_bps == Decimal("99.50248756218905472636815920")
    assert snapshot.aggregate_bid_depth == Decimal("210")
    assert snapshot.aggregate_ask_depth == Decimal("230")
    assert snapshot.imbalance == Decimal("-0.04545454545454545454545454545")
    assert deterministic_order_book_dataset_hash(
        snapshots
    ) == deterministic_order_book_dataset_hash(list(reversed(snapshots)))


def test_derivatives_metric_normalization_allows_optional_fields_and_hashes() -> None:
    batch = RawDerivativesMetricBatch(
        exchange="binance",
        symbol="BTC/USDT",
        rows=[
            {
                "fundingTime": 1767225600000,
                "fundingRate": "-0.0001",
                "openInterest": "1250.5",
                "longShortRatio": "1.25",
                "longLiquidationVolume": "42",
                "shortLiquidationVolume": "12",
            },
            {
                "timestamp": "2026-01-01T08:00:00Z",
                "funding_rate": "0.0002",
            },
        ],
    )

    metrics = normalize_derivatives_metric_batch(
        batch,
        raw_checksum="abc",
        now=datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
    )

    assert [metric.timestamp for metric in metrics] == [
        datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 1, 8, 0, tzinfo=UTC),
    ]
    assert metrics[0].funding_rate == Decimal("-0.0001")
    assert metrics[0].open_interest == Decimal("1250.5")
    assert metrics[0].long_short_ratio == Decimal("1.25")
    assert metrics[0].liquidation_long_volume == Decimal("42")
    assert metrics[0].liquidation_short_volume == Decimal("12")
    assert metrics[1].open_interest is None
    assert deterministic_derivatives_metric_dataset_hash(
        metrics
    ) == deterministic_derivatives_metric_dataset_hash(list(reversed(metrics)))


def test_derivatives_metric_normalization_rejects_duplicate_future_and_bad_values() -> None:
    now = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    duplicate = RawDerivativesMetricBatch(
        exchange="binance",
        symbol="BTC/USDT",
        rows=[
            {"timestamp": "2026-01-01T00:00:00Z", "funding_rate": "0.0001"},
            {"timestamp": "2026-01-01T00:00:00Z", "funding_rate": "0.0002"},
        ],
    )
    with pytest.raises(MarketDataError, match="duplicate derivatives metric timestamps"):
        normalize_derivatives_metric_batch(duplicate, raw_checksum="abc", now=now)

    future = RawDerivativesMetricBatch(
        exchange="binance",
        symbol="BTC/USDT",
        rows=[{"timestamp": "2999-01-01T00:00:00Z", "funding_rate": "0.0001"}],
    )
    with pytest.raises(MarketDataError, match="future"):
        normalize_derivatives_metric_batch(future, raw_checksum="abc")

    invalid_decimal = RawDerivativesMetricBatch(
        exchange="binance",
        symbol="BTC/USDT",
        rows=[{"timestamp": "2026-01-01T00:00:00Z", "funding_rate": "nan"}],
    )
    with pytest.raises(MarketDataError, match="finite"):
        normalize_derivatives_metric_batch(invalid_decimal, raw_checksum="abc", now=now)

    negative_optional_value = RawDerivativesMetricBatch(
        exchange="binance",
        symbol="BTC/USDT",
        rows=[
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "funding_rate": "0.0001",
                "open_interest": "-1",
            }
        ],
    )
    with pytest.raises(MarketDataError, match="open_interest must be nonnegative"):
        normalize_derivatives_metric_batch(negative_optional_value, raw_checksum="abc", now=now)


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
