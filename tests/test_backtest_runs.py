from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.orm import sessionmaker

from trading.services.backtests import BacktestRunRequest, BacktestService, build_backtest_strategy


def test_build_backtest_strategy_supports_only_moving_average_crossover() -> None:
    strategy = build_backtest_strategy(
        "moving_average_crossover",
        {"short_window": 1, "long_window": 2},
    )

    assert strategy.name == "moving_average_crossover"
    assert strategy.parameters == {"short_window": 1, "long_window": 2}

    with pytest.raises(ValueError, match="unsupported strategy_name"):
        build_backtest_strategy("other", {"short_window": 1, "long_window": 2})


@pytest.mark.parametrize(
    "parameters",
    [
        {"short_window": 1},
        {"short_window": "1", "long_window": 2},
        {"short_window": 2, "long_window": 2},
    ],
)
def test_build_backtest_strategy_rejects_malformed_parameters(
    parameters: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        build_backtest_strategy("moving_average_crossover", parameters)


@pytest.mark.parametrize(
    "generated_at",
    [
        datetime(2026, 1, 2, 3, 4, 5),
        datetime(2026, 1, 2, 7, 4, 5, tzinfo=timezone(timedelta(hours=4))),
    ],
)
def test_backtest_service_rejects_non_exact_utc_generated_at(generated_at: datetime) -> None:
    service = BacktestService(sessionmaker(), reports_dir="reports")

    with pytest.raises(ValueError, match="generated_at must"):
        service.run_backtest(
            BacktestRunRequest(
                exchange="binance",
                symbol="BTC/USDT",
                timeframe="1m",
                start=datetime(2026, 1, 1, tzinfo=UTC),
                end=datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
                decision_time=datetime(2026, 1, 1, 1, tzinfo=UTC),
                generated_at=generated_at,
                initial_capital=Decimal("1000"),
                fee_bps=Decimal("0"),
                slippage_bps=Decimal("0"),
                strategy_name="moving_average_crossover",
                strategy_parameters={"short_window": 1, "long_window": 2},
            )
        )
