"""Deterministic strategy interfaces and baseline strategies."""

from trading.strategies.base import CandleStrategy, StrategyParameters, StrategySignal
from trading.strategies.moving_average import MovingAverageCrossoverStrategy

__all__ = [
    "CandleStrategy",
    "MovingAverageCrossoverStrategy",
    "StrategyParameters",
    "StrategySignal",
]
