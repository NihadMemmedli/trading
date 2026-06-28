from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trading.backtesting import (
    BacktestConfig,
    BacktestSizingConfig,
    build_backtest_report,
    export_backtest_report_json,
    run_candle_backtest,
)
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
    strategy_version: str = "test-v1",
    sizing: BacktestSizingConfig | None = None,
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
        strategy_version=strategy_version,
        strategy_parameters=strategy_parameters,
        sizing=sizing or BacktestSizingConfig(),
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


class ScheduledTargetStrategy:
    def __init__(self, targets: Sequence[str]) -> None:
        self._targets = tuple(Decimal(target) for target in targets)
        self._index = 0

    @property
    def name(self) -> str:
        return "scheduled_target"

    @property
    def parameters(self) -> StrategyParameters:
        return {"targets": ",".join(str(target) for target in self._targets)}

    def on_candle(
        self,
        *,
        candle: NormalizedCandle,
        history: Sequence[NormalizedCandle],
    ) -> StrategySignal:
        target = self._targets[self._index]
        self._index += 1
        return StrategySignal(
            symbol=candle.symbol,
            timestamp=candle.timestamp,
            target_position=target,
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
    assert result.metrics.trades_count == result.trades_count
    assert result.metrics.final_equity == result.final_equity
    assert result.metrics.total_return == result.total_return
    assert result.metrics.max_drawdown == result.max_drawdown
    assert result.metrics.fees_paid == result.fees_paid


def test_backtest_calculates_turnover_exposure_benchmark_and_excess_return() -> None:
    strategy = ScheduledTargetStrategy(("1", "0", "0"))
    candles = (
        make_candle(0, open_="100", close="100"),
        make_candle(1, open_="100", close="100"),
        make_candle(2, open_="200", close="200"),
    )

    result = run_candle_backtest(
        candles=candles,
        dataset_hash="dataset-a",
        config=make_config(
            strategy_name=strategy.name,
            strategy_parameters=strategy.parameters,
        ),
        strategy=strategy,
    )

    assert result.trades_count == 2
    assert result.metrics.turnover == Decimal("3")
    assert result.metrics.average_exposure == Decimal("1") / Decimal("3")
    assert result.metrics.benchmark_total_return == Decimal("1")
    assert result.metrics.excess_return == Decimal("0")
    assert result.metrics.return_observations == 2
    assert result.metrics.positive_return_periods == 1
    assert result.metrics.negative_return_periods == 0
    assert result.metrics.return_mean == Decimal("0.5")
    assert result.metrics.return_stddev == Decimal("0.5")
    assert result.metrics.sharpe_like == Decimal(str(2**0.5))


def test_backtest_sizing_config_caps_exposure_and_reserves_cash() -> None:
    strategy = AlwaysLongStrategy()
    candles = (
        make_candle(0, open_="100", close="100"),
        make_candle(1, open_="100", close="100"),
    )

    result = run_candle_backtest(
        candles=candles,
        dataset_hash="dataset-a",
        config=make_config(
            strategy_name=strategy.name,
            strategy_parameters=strategy.parameters,
            sizing=BacktestSizingConfig(
                max_exposure=Decimal("0.5"),
                cash_reserve=Decimal("0.25"),
                min_trade_notional=Decimal("0"),
            ),
        ),
        strategy=strategy,
    )

    assert result.trades_count == 1
    assert result.trades[0].quantity == Decimal("5")
    assert result.final_equity == Decimal("1000")
    assert result.metrics.average_exposure == Decimal("0.25")


def test_backtest_sizing_config_skips_small_trades() -> None:
    strategy = AlwaysLongStrategy()
    candles = (
        make_candle(0, open_="100", close="100"),
        make_candle(1, open_="100", close="100"),
    )

    result = run_candle_backtest(
        candles=candles,
        dataset_hash="dataset-a",
        config=make_config(
            strategy_name=strategy.name,
            strategy_parameters=strategy.parameters,
            sizing=BacktestSizingConfig(min_trade_notional=Decimal("1000.01")),
        ),
        strategy=strategy,
    )

    assert result.trades_count == 0
    assert result.final_equity == Decimal("1000")


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


def test_strategy_version_and_sizing_are_part_of_config_and_result_hashes() -> None:
    strategy = AlwaysLongStrategy()
    candles = (
        make_candle(0, open_="100", close="100"),
        make_candle(1, open_="100", close="100"),
    )

    first = run_candle_backtest(
        candles=candles,
        dataset_hash="dataset-a",
        config=make_config(
            strategy_name=strategy.name,
            strategy_parameters=strategy.parameters,
            strategy_version="version-a",
        ),
        strategy=strategy,
    )
    second = run_candle_backtest(
        candles=candles,
        dataset_hash="dataset-a",
        config=make_config(
            strategy_name=strategy.name,
            strategy_parameters=strategy.parameters,
            strategy_version="version-b",
        ),
        strategy=strategy,
    )
    third = run_candle_backtest(
        candles=candles,
        dataset_hash="dataset-a",
        config=make_config(
            strategy_name=strategy.name,
            strategy_parameters=strategy.parameters,
            strategy_version="version-a",
            sizing=BacktestSizingConfig(max_exposure=Decimal("0.5")),
        ),
        strategy=strategy,
    )

    assert first.config_hash != second.config_hash
    assert first.config_hash != third.config_hash
    assert first.result_hash != second.result_hash
    assert first.result_hash != third.result_hash


def test_backtest_report_export_is_reproducible_with_explicit_generated_at() -> None:
    generated_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    first_strategy = MovingAverageCrossoverStrategy(short_window=1, long_window=2)
    second_strategy = MovingAverageCrossoverStrategy(short_window=1, long_window=2)
    config = make_config(
        strategy_name=first_strategy.name,
        strategy_parameters=first_strategy.parameters,
    )
    candles = (
        make_candle(0, open_="100", close="100"),
        make_candle(1, open_="101", close="102"),
        make_candle(2, open_="103", close="104"),
    )

    first_result = run_candle_backtest(
        candles=candles,
        dataset_hash="dataset-a",
        config=config,
        strategy=first_strategy,
    )
    second_result = run_candle_backtest(
        candles=tuple(reversed(candles)),
        dataset_hash="dataset-a",
        config=config,
        strategy=second_strategy,
    )
    first_report = build_backtest_report(first_result, config, generated_at)
    second_report = build_backtest_report(second_result, config, generated_at)

    first_json = export_backtest_report_json(first_report)
    second_json = export_backtest_report_json(second_report)
    decoded = json.loads(first_json)

    assert first_report.report_hash == second_report.report_hash
    assert first_json == second_json
    assert decoded["report_hash"] == first_report.report_hash
    assert decoded["strategy_version"] == "test-v1"
    assert decoded["sizing"] == {
        "cash_reserve": "0",
        "max_exposure": "1",
        "min_trade_notional": "0",
    }
    assert decoded["metrics"]["final_equity"] == str(first_result.final_equity)
    assert decoded["generated_at"] == generated_at.isoformat()


@pytest.mark.parametrize(
    "generated_at",
    [
        datetime(2026, 1, 2, 3, 4, 5),
        datetime(2026, 1, 2, 7, 4, 5, tzinfo=timezone(timedelta(hours=4))),
    ],
)
def test_backtest_report_requires_explicit_utc_generated_at(generated_at: datetime) -> None:
    strategy = AlwaysLongStrategy()
    config = make_config(strategy_name=strategy.name, strategy_parameters=strategy.parameters)
    result = run_candle_backtest(
        candles=(
            make_candle(0, open_="100", close="100"),
            make_candle(1, open_="100", close="100"),
        ),
        dataset_hash="dataset-a",
        config=config,
        strategy=strategy,
    )

    with pytest.raises(ValueError, match="generated_at must"):
        build_backtest_report(result, config, generated_at)


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
