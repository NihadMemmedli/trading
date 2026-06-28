from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from trading.data.market import NormalizedCandle
from trading.features import (
    FeatureMaterializationError,
    FeatureSetLeakageError,
    InsufficientLookbackError,
    deterministic_feature_set_hash,
    deterministic_parameter_hash,
    materialize_candle_features,
    normalize_feature_parameters,
)
from trading.services.feature_sets import (
    FeatureSetDatasetNotMaterializableError,
    _parse_feature_dataset_name,
)


def candle(minute: int, close: str, *, available_hour: int = 1) -> NormalizedCandle:
    timestamp = datetime(2026, 1, 1, 0, minute, tzinfo=UTC)
    return NormalizedCandle(
        exchange="binance",
        symbol="BTC/USDT",
        timeframe="1m",
        timestamp=timestamp,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=Decimal(str(10 + minute)),
        available_at=datetime(2026, 1, 1, available_hour, tzinfo=UTC),
        raw_checksum=f"checksum-{minute}",
        quality_flags={},
    )


def test_parameter_hash_is_deterministic_and_validates_shape() -> None:
    first = deterministic_parameter_hash({"lookback": 3})
    second = deterministic_parameter_hash({"lookback": 3})

    assert first == second
    assert len(first) == 64
    assert normalize_feature_parameters({}) == {"lookback": 3}

    with pytest.raises(FeatureMaterializationError, match="unsupported"):
        normalize_feature_parameters({"lookback": 3, "future_window": 1})
    with pytest.raises(FeatureMaterializationError, match="at least 2"):
        normalize_feature_parameters({"lookback": 1})
    with pytest.raises(FeatureMaterializationError, match="integer"):
        normalize_feature_parameters({"lookback": True})


def test_materialize_candle_features_is_deterministic_and_point_in_time() -> None:
    candles = [candle(0, "100"), candle(1, "110"), candle(2, "121")]

    rows = materialize_candle_features(
        candles=tuple(reversed(candles)),
        decision_time=datetime(2026, 1, 1, 1, tzinfo=UTC),
        dataset_id=42,
        dataset_hash="d" * 64,
        code_version="candle_features_v1",
        parameters={"lookback": 2},
    )
    repeated = materialize_candle_features(
        candles=candles,
        decision_time=datetime(2026, 1, 1, 1, tzinfo=UTC),
        dataset_id=42,
        dataset_hash="d" * 64,
        code_version="candle_features_v1",
        parameters={"lookback": 2},
    )

    assert rows == repeated
    assert len(rows) == 2
    assert rows[0].features == {
        "close_return_1": "0.1",
        "close_sma_2": "105",
        "volume_sma_2": "10.5",
    }
    assert all(row.available_at <= row.decision_time for row in rows)
    assert deterministic_feature_set_hash(
        dataset_id=42,
        dataset_hash="d" * 64,
        name="mvp-candles",
        code_version="candle_features_v1",
        parameters={"lookback": 2},
        rows=rows,
    ) == deterministic_feature_set_hash(
        dataset_id=42,
        dataset_hash="d" * 64,
        name="mvp-candles",
        code_version="candle_features_v1",
        parameters={"lookback": 2},
        rows=repeated,
    )


def test_materialize_candle_features_rejects_insufficient_lookback() -> None:
    with pytest.raises(InsufficientLookbackError, match="not enough candles"):
        materialize_candle_features(
            candles=[candle(0, "100")],
            decision_time=datetime(2026, 1, 1, 1, tzinfo=UTC),
            dataset_id=42,
            dataset_hash="d" * 64,
            code_version="candle_features_v1",
            parameters={"lookback": 2},
        )


def test_materialize_candle_features_rejects_leaking_availability() -> None:
    with pytest.raises(FeatureSetLeakageError, match="after decision_time"):
        materialize_candle_features(
            candles=[candle(0, "100"), candle(1, "110", available_hour=2)],
            decision_time=datetime(2026, 1, 1, 1, tzinfo=UTC),
            dataset_id=42,
            dataset_hash="d" * 64,
            code_version="candle_features_v1",
            parameters={"lookback": 2},
        )


def test_feature_dataset_selector_parses_backtest_dataset_names() -> None:
    selector = _parse_feature_dataset_name(
        "backtest:binance:BTC/USDT:1m:"
        "2026-01-01T00:00:00Z:2026-01-01T00:05:00Z:2026-01-01T01:00:00Z"
    )

    assert selector.exchange == "binance"
    assert selector.symbol == "BTC/USDT"
    assert selector.timeframe == "1m"
    assert selector.start == datetime(2026, 1, 1, tzinfo=UTC)
    assert selector.end == datetime(2026, 1, 1, 0, 5, tzinfo=UTC)
    assert selector.decision_time == datetime(2026, 1, 1, 1, tzinfo=UTC)

    with pytest.raises(FeatureSetDatasetNotMaterializableError, match="backtest-created"):
        _parse_feature_dataset_name("manual:binance:BTC/USDT")
    with pytest.raises(FeatureSetDatasetNotMaterializableError, match="malformed"):
        _parse_feature_dataset_name("backtest:binance:BTC/USDT:1m:not-a-range")
