"""Deterministic moving-average crossover baseline."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from trading.data.market import MarketDataError, NormalizedCandle
from trading.strategies.base import StrategyParameters, StrategySignal


@dataclass(frozen=True)
class MovingAverageCrossoverStrategy:
    """Long-only benchmark using close-price simple moving averages."""

    short_window: int
    long_window: int

    def __post_init__(self) -> None:
        if self.short_window <= 0:
            raise MarketDataError("short_window must be positive")
        if self.long_window <= 0:
            raise MarketDataError("long_window must be positive")
        if self.short_window >= self.long_window:
            raise MarketDataError("short_window must be smaller than long_window")

    @property
    def name(self) -> str:
        return "moving_average_crossover"

    @property
    def parameters(self) -> StrategyParameters:
        return {"short_window": self.short_window, "long_window": self.long_window}

    def on_candle(
        self,
        *,
        candle: NormalizedCandle,
        history: Sequence[NormalizedCandle],
    ) -> StrategySignal:
        closes = [item.close for item in history if item.symbol == candle.symbol]
        if len(closes) < self.long_window:
            return StrategySignal(
                symbol=candle.symbol,
                timestamp=candle.timestamp,
                target_position=Decimal("0"),
            )

        short_average = _mean(closes[-self.short_window :])
        long_average = _mean(closes[-self.long_window :])
        return StrategySignal(
            symbol=candle.symbol,
            timestamp=candle.timestamp,
            target_position=Decimal("1") if short_average > long_average else Decimal("0"),
        )


def _mean(values: Sequence[Decimal]) -> Decimal:
    return sum(values, Decimal("0")) / Decimal(len(values))
