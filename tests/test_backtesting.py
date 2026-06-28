from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trading.backtesting import BacktestConfig, run_candle_backtest
from trading.data.market import NormalizedCandle
from trading.strategies import MovingAverageCrossoverStrategy, StrategyParameters, StrategySignal

BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


def make_candle(
    minute: int,
    *,
    open_: str,
    close: str,
    available_at: datetime | None = None,
    symbol: str = "BTC/USDT",
) -> NormalizedCandle:
    timestamp = BASE_TIME + timedelta(minutes=minute)
    open_decimal = Decimal(open_)
    close_decimal = Decimal(close)
    return NormalizedCandle(
        exchange="binance",
        symbol=symbol,
        timeframe="1m",
        timestamp=timestamp,
        open=open_decimal,
        high=max(open_decimal, close_decimal),
        low=min(open_decimal, close_decimal),
        close=close_decimal,
        volume=Decimal("1"),
        available_at=available_at or timestamp,
        raw_checksum=f"raw-{minute}",
    )


def make_config(
    *,
    strategy_name: str,
    strategy_parameters: StrategyParameters,
    fee_bps: str = "0",
    slippage_bps: str = "0",
    decision_time: datetime = BASE_TIME + timedelta(minutes=10),
) -> BacktestConfig:
    return BacktestConfig(
        symbol="BTC/USDT",
        timeframe="1m",
        initial_capital=Decimal("1000"),
        fee_bps=Decimal(fee_bps),
        slippage_bps=Decimal(slippage_bps),
        start=BASE_TIME,
        end=BASE_TIME + timedelta(minutes=10),
        decision_time=decision_time,
        strategy_name=strategy_name,
        strategy_parameters=strategy_parameters,
    )


def test_moving_average_crossover_generates_deterministic_signals() -> None:
    strategy = MovingAverageCrossoverStrategy(short_window=2, long_window=3)
    rising = (
        make_candle(0, open_="100", close="100"),
        make_candle(1, open_="101", close="102"),
        make_candle(2, open_="103", close="104"),
    )
    falling = (
        make_candle(0, open_="104", close="104"),
        make_candle(1, open_="102", close="102"),
        make_candle(2, open_="100", close="100"),
    )

    assert strategy.on_candle(candle=rising[-1], history=rising).target_position == Decimal("1")
    assert strategy.on_candle(candle=falling[-1], history=falling).target_position == Decimal("0")


class AlwaysLongStrategy:
    @property
    def name(self) -> str:
        return "always_long"

    @property
    def parameters(self) -> StrategyParameters:
        return {}

    def on_candle(
        self,
        *,
        candle: NormalizedCandle,
        history: Sequence[NormalizedCandle],
    ) -> StrategySignal:
        return StrategySignal(
            symbol=candle.symbol,
            timestamp=candle.timestamp,
            target_position=Decimal("1"),
        )


def test_backtest_accounts_for_fee_and_slippage_on_next_candle_open() -> None:
    candles = (
        make_candle(0, open_="100", close="100"),
        make_candle(1, open_="100", close="100"),
    )
    result = run_candle_backtest(
        candles=candles,
        dataset_hash="dataset-a",
        config=make_config(
            strategy_name="always_long",
            strategy_parameters={},
            fee_bps="100",
            slippage_bps="100",
        ),
        strategy=AlwaysLongStrategy(),
    )

    expected_fill_price = Decimal("101.00")
    expected_quantity = Decimal("1000") / (expected_fill_price * Decimal("1.01"))
    expected_fee = expected_quantity * expected_fill_price * Decimal("0.01")
    expected_final_equity = expected_quantity * Decimal("100")

    assert result.trades_count == 1
    assert result.trades[0].side == "buy"
    assert result.trades[0].fill_price == expected_fill_price
    assert result.trades[0].quantity == expected_quantity
    assert result.fees_paid == expected_fee
    assert result.final_equity == expected_final_equity
    assert result.max_drawdown == (Decimal("1000") - expected_final_equity) / Decimal("1000")


def test_same_dataset_and_config_produce_same_result_hash() -> None:
    strategy = MovingAverageCrossoverStrategy(short_window=1, long_window=2)
    config = make_config(
        strategy_name=strategy.name,
        strategy_parameters=strategy.parameters,
    )
    candles = (
        make_candle(0, open_="100", close="100"),
        make_candle(1, open_="101", close="102"),
        make_candle(2, open_="103", close="104"),
    )

    first = run_candle_backtest(
        candles=candles,
        dataset_hash="dataset-a",
        config=config,
        strategy=strategy,
    )
    second = run_candle_backtest(
        candles=tuple(reversed(candles)),
        dataset_hash="dataset-a",
        config=config,
        strategy=strategy,
    )

    assert first.config_hash == second.config_hash
    assert first.result_hash == second.result_hash
    assert len(first.result_hash) == 64


class RecordingStrategy:
    def __init__(self) -> None:
        self.histories: list[tuple[datetime, tuple[datetime, ...]]] = []

    @property
    def name(self) -> str:
        return "recording"

    @property
    def parameters(self) -> StrategyParameters:
        return {}

    def on_candle(
        self,
        *,
        candle: NormalizedCandle,
        history: Sequence[NormalizedCandle],
    ) -> StrategySignal:
        self.histories.append((candle.timestamp, tuple(item.timestamp for item in history)))
        return StrategySignal(
            symbol=candle.symbol,
            timestamp=candle.timestamp,
            target_position=Decimal("0"),
        )


def test_runner_filters_by_decision_time_and_never_passes_future_history() -> None:
    strategy = RecordingStrategy()
    candles = (
        make_candle(0, open_="100", close="100", available_at=BASE_TIME),
        make_candle(1, open_="101", close="101", available_at=BASE_TIME + timedelta(minutes=1)),
        make_candle(
            2,
            open_="102",
            close="102",
            available_at=BASE_TIME + timedelta(minutes=30),
        ),
    )

    result = run_candle_backtest(
        candles=candles,
        dataset_hash="dataset-a",
        config=make_config(
            strategy_name=strategy.name,
            strategy_parameters=strategy.parameters,
            decision_time=BASE_TIME + timedelta(minutes=1, seconds=30),
        ),
        strategy=strategy,
    )

    assert [point.timestamp for point in result.equity_curve] == [
        BASE_TIME,
        BASE_TIME + timedelta(minutes=1),
    ]
    for candle_timestamp, history_timestamps in strategy.histories:
        assert all(
            history_timestamp <= candle_timestamp for history_timestamp in history_timestamps
        )
    assert BASE_TIME + timedelta(minutes=2) not in {
        history_timestamp
        for _, history_timestamps in strategy.histories
        for history_timestamp in history_timestamps
    }


def test_strategy_and_config_must_match() -> None:
    strategy = AlwaysLongStrategy()
    with pytest.raises(ValueError, match="strategy name does not match"):
        run_candle_backtest(
            candles=(make_candle(0, open_="100", close="100"),),
            dataset_hash="dataset-a",
            config=make_config(strategy_name="other", strategy_parameters={}),
            strategy=strategy,
        )
