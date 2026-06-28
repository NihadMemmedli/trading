"""Strategy contracts used by deterministic backtests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from trading.data.market import NormalizedCandle

StrategyParameterValue = str | int | Decimal
StrategyParameters = Mapping[str, StrategyParameterValue]


@dataclass(frozen=True)
class StrategyMetadata:
    """Stable strategy registry metadata included in reproducibility hashes."""

    name: str
    version: str
    description: str
    parameter_schema: Mapping[str, Any]


@dataclass(frozen=True)
class StrategySignal:
    """Long-only target exposure for the next candle."""

    symbol: str
    timestamp: datetime
    target_position: Decimal


class CandleStrategy(Protocol):
    """Deterministic candle strategy evaluated with history available so far."""

    @property
    def name(self) -> str:
        """Stable strategy identifier."""

    @property
    def parameters(self) -> StrategyParameters:
        """Stable strategy parameters included in the backtest config hash."""

    def on_candle(
        self,
        *,
        candle: NormalizedCandle,
        history: Sequence[NormalizedCandle],
    ) -> StrategySignal:
        """Return the target exposure to apply on the next candle."""
