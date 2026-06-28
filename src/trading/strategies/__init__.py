"""Deterministic strategy interfaces and baseline strategies."""

from trading.strategies.base import (
    CandleStrategy,
    StrategyMetadata,
    StrategyParameters,
    StrategySignal,
)
from trading.strategies.moving_average import MovingAverageCrossoverStrategy
from trading.strategies.registry import build_strategy, get_strategy_metadata

__all__ = [
    "CandleStrategy",
    "MovingAverageCrossoverStrategy",
    "StrategyMetadata",
    "StrategyParameters",
    "StrategySignal",
    "build_strategy",
    "get_strategy_metadata",
]
