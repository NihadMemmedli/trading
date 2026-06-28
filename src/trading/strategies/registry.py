"""Deterministic strategy registry."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from trading.data.market import MarketDataError
from trading.strategies.base import CandleStrategy, StrategyMetadata
from trading.strategies.moving_average import MovingAverageCrossoverStrategy

MOVING_AVERAGE_CROSSOVER_METADATA = StrategyMetadata(
    name="moving_average_crossover",
    version="1",
    description="Long-only close-price simple moving-average crossover benchmark.",
    parameter_schema={
        "type": "object",
        "required": ["short_window", "long_window"],
        "additionalProperties": False,
        "properties": {
            "short_window": {"type": "integer", "minimum": 1},
            "long_window": {"type": "integer", "minimum": 1},
        },
    },
)

STRATEGY_REGISTRY: Mapping[str, StrategyMetadata] = {
    MOVING_AVERAGE_CROSSOVER_METADATA.name: MOVING_AVERAGE_CROSSOVER_METADATA,
}


def get_strategy_metadata(strategy_name: str) -> StrategyMetadata:
    """Return metadata for a registered deterministic strategy."""

    normalized_name = strategy_name.strip()
    metadata = STRATEGY_REGISTRY.get(normalized_name)
    if metadata is None:
        raise MarketDataError("unsupported strategy_name")
    return metadata


def build_strategy(
    strategy_name: str,
    strategy_parameters: Mapping[str, Any],
) -> CandleStrategy:
    """Build a registered deterministic candle strategy."""

    metadata = get_strategy_metadata(strategy_name)
    if metadata.name != MOVING_AVERAGE_CROSSOVER_METADATA.name:
        raise MarketDataError("unsupported strategy_name")

    expected_keys = {"short_window", "long_window"}
    provided_keys = set(strategy_parameters)
    if provided_keys != expected_keys:
        raise MarketDataError("strategy_parameters must include short_window and long_window only")

    return MovingAverageCrossoverStrategy(
        short_window=_strict_positive_int(strategy_parameters["short_window"], "short_window"),
        long_window=_strict_positive_int(strategy_parameters["long_window"], "long_window"),
    )


def _strict_positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MarketDataError(f"{field_name} must be an integer")
    if value <= 0:
        raise MarketDataError(f"{field_name} must be positive")
    return int(value)
