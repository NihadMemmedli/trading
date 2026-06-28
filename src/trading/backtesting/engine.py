"""Candle-only deterministic backtest runner."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from trading.data.market import MarketDataError, NormalizedCandle, require_utc, validate_timeframe
from trading.strategies import CandleStrategy, StrategyParameters

BPS_DENOMINATOR = Decimal("10000")


@dataclass(frozen=True)
class BacktestConfig:
    """Explicit replay configuration for one symbol and timeframe."""

    symbol: str
    timeframe: str
    initial_capital: Decimal
    fee_bps: Decimal
    slippage_bps: Decimal
    start: datetime
    end: datetime
    decision_time: datetime
    strategy_name: str
    strategy_parameters: StrategyParameters

    def __post_init__(self) -> None:
        if not self.strategy_name.strip():
            raise MarketDataError("strategy_name cannot be blank")
        if self.initial_capital <= Decimal("0"):
            raise MarketDataError("initial_capital must be positive")
        if self.fee_bps < Decimal("0"):
            raise MarketDataError("fee_bps must be nonnegative")
        if self.slippage_bps < Decimal("0"):
            raise MarketDataError("slippage_bps must be nonnegative")

        normalized_start = require_utc(self.start, field_name="start")
        normalized_end = require_utc(self.end, field_name="end")
        normalized_decision_time = require_utc(self.decision_time, field_name="decision_time")
        if normalized_start >= normalized_end:
            raise MarketDataError("start must be earlier than end")

        object.__setattr__(self, "timeframe", validate_timeframe(self.timeframe))
        object.__setattr__(self, "start", normalized_start)
        object.__setattr__(self, "end", normalized_end)
        object.__setattr__(self, "decision_time", normalized_decision_time)


@dataclass(frozen=True)
class BacktestTrade:
    symbol: str
    timestamp: datetime
    side: str
    quantity: Decimal
    fill_price: Decimal
    fee: Decimal
    slippage: Decimal


@dataclass(frozen=True)
class EquityPoint:
    timestamp: datetime
    equity: Decimal


@dataclass(frozen=True)
class BacktestResult:
    config_hash: str
    dataset_hash: str
    result_hash: str
    trades_count: int
    final_equity: Decimal
    total_return: Decimal
    max_drawdown: Decimal
    fees_paid: Decimal
    trades: tuple[BacktestTrade, ...]
    equity_curve: tuple[EquityPoint, ...]


def run_candle_backtest(
    *,
    candles: tuple[NormalizedCandle, ...],
    dataset_hash: str,
    config: BacktestConfig,
    strategy: CandleStrategy,
) -> BacktestResult:
    """Run a deterministic long-only backtest on point-in-time candle data."""

    filtered_candles = _select_replay_candles(candles, config)
    if not filtered_candles:
        raise MarketDataError("backtest requires at least one eligible candle")
    if strategy.name != config.strategy_name:
        raise MarketDataError("strategy name does not match backtest config")
    if dict(strategy.parameters) != dict(config.strategy_parameters):
        raise MarketDataError("strategy parameters do not match backtest config")

    cash = config.initial_capital
    position = Decimal("0")
    pending_target = Decimal("0")
    fee_rate = config.fee_bps / BPS_DENOMINATOR
    slippage_rate = config.slippage_bps / BPS_DENOMINATOR
    trades: list[BacktestTrade] = []
    equity_curve: list[EquityPoint] = []

    for index, candle in enumerate(filtered_candles):
        cash, position, trade = _rebalance_to_target(
            cash=cash,
            position=position,
            target_position=pending_target,
            candle=candle,
            fee_rate=fee_rate,
            slippage_rate=slippage_rate,
        )
        if trade is not None:
            trades.append(trade)

        equity = cash + position * candle.close
        equity_curve.append(EquityPoint(timestamp=candle.timestamp, equity=equity))

        history = filtered_candles[: index + 1]
        signal = strategy.on_candle(candle=candle, history=history)
        if signal.symbol != config.symbol:
            raise MarketDataError("strategy emitted a signal for the wrong symbol")
        if signal.timestamp != candle.timestamp:
            raise MarketDataError("strategy emitted a signal for the wrong timestamp")
        if signal.target_position < Decimal("0") or signal.target_position > Decimal("1"):
            raise MarketDataError("strategy target_position must be between 0 and 1")
        pending_target = signal.target_position

    final_equity = equity_curve[-1].equity
    config_hash = deterministic_config_hash(config)
    result = BacktestResult(
        config_hash=config_hash,
        dataset_hash=dataset_hash,
        result_hash="",
        trades_count=len(trades),
        final_equity=final_equity,
        total_return=(final_equity - config.initial_capital) / config.initial_capital,
        max_drawdown=_max_drawdown(equity_curve),
        fees_paid=sum((trade.fee for trade in trades), Decimal("0")),
        trades=tuple(trades),
        equity_curve=tuple(equity_curve),
    )
    return BacktestResult(
        config_hash=result.config_hash,
        dataset_hash=result.dataset_hash,
        result_hash=deterministic_result_hash(result),
        trades_count=result.trades_count,
        final_equity=result.final_equity,
        total_return=result.total_return,
        max_drawdown=result.max_drawdown,
        fees_paid=result.fees_paid,
        trades=result.trades,
        equity_curve=result.equity_curve,
    )


def deterministic_config_hash(config: BacktestConfig) -> str:
    payload = {
        "symbol": config.symbol,
        "timeframe": config.timeframe,
        "initial_capital": config.initial_capital,
        "fee_bps": config.fee_bps,
        "slippage_bps": config.slippage_bps,
        "start": config.start,
        "end": config.end,
        "decision_time": config.decision_time,
        "strategy_name": config.strategy_name,
        "strategy_parameters": dict(config.strategy_parameters),
    }
    return _sha256_json(payload)


def deterministic_result_hash(result: BacktestResult) -> str:
    payload = {
        "config_hash": result.config_hash,
        "dataset_hash": result.dataset_hash,
        "trades_count": result.trades_count,
        "final_equity": result.final_equity,
        "total_return": result.total_return,
        "max_drawdown": result.max_drawdown,
        "fees_paid": result.fees_paid,
        "trades": [
            {
                "symbol": trade.symbol,
                "timestamp": trade.timestamp,
                "side": trade.side,
                "quantity": trade.quantity,
                "fill_price": trade.fill_price,
                "fee": trade.fee,
                "slippage": trade.slippage,
            }
            for trade in result.trades
        ],
        "equity_curve": [
            {"timestamp": point.timestamp, "equity": point.equity} for point in result.equity_curve
        ],
    }
    return _sha256_json(payload)


def _select_replay_candles(
    candles: tuple[NormalizedCandle, ...],
    config: BacktestConfig,
) -> tuple[NormalizedCandle, ...]:
    selected = [
        candle
        for candle in candles
        if candle.symbol == config.symbol
        and candle.timeframe == config.timeframe
        and config.start <= candle.timestamp <= config.end
        and candle.available_at <= config.decision_time
    ]
    return tuple(sorted(selected, key=lambda candle: candle.timestamp))


def _rebalance_to_target(
    *,
    cash: Decimal,
    position: Decimal,
    target_position: Decimal,
    candle: NormalizedCandle,
    fee_rate: Decimal,
    slippage_rate: Decimal,
) -> tuple[Decimal, Decimal, BacktestTrade | None]:
    reference_price = candle.open
    equity = cash + position * reference_price
    target_quantity = equity * target_position / reference_price
    quantity_delta = target_quantity - position
    if quantity_delta == Decimal("0"):
        return cash, position, None

    if quantity_delta > Decimal("0"):
        fill_price = reference_price * (Decimal("1") + slippage_rate)
        max_quantity = cash / (fill_price * (Decimal("1") + fee_rate))
        quantity = min(quantity_delta, max_quantity)
        if quantity <= Decimal("0"):
            return cash, position, None
        notional = quantity * fill_price
        fee = notional * fee_rate
        slippage = (fill_price - reference_price) * quantity
        return (
            cash - notional - fee,
            position + quantity,
            BacktestTrade(
                symbol=candle.symbol,
                timestamp=candle.timestamp,
                side="buy",
                quantity=quantity,
                fill_price=fill_price,
                fee=fee,
                slippage=slippage,
            ),
        )

    fill_price = reference_price * (Decimal("1") - slippage_rate)
    quantity = min(-quantity_delta, position)
    if quantity <= Decimal("0"):
        return cash, position, None
    notional = quantity * fill_price
    fee = notional * fee_rate
    slippage = (reference_price - fill_price) * quantity
    return (
        cash + notional - fee,
        position - quantity,
        BacktestTrade(
            symbol=candle.symbol,
            timestamp=candle.timestamp,
            side="sell",
            quantity=quantity,
            fill_price=fill_price,
            fee=fee,
            slippage=slippage,
        ),
    )


def _max_drawdown(equity_curve: list[EquityPoint]) -> Decimal:
    peak = equity_curve[0].equity
    max_drawdown = Decimal("0")
    for point in equity_curve:
        if point.equity > peak:
            peak = point.equity
        if peak > Decimal("0"):
            drawdown = (peak - point.equity) / peak
            if drawdown > max_drawdown:
                max_drawdown = drawdown
    return max_drawdown


def _sha256_json(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_default(value: object) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")
