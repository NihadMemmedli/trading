from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.exc import OperationalError

from alembic import command
from trading.backtesting import BacktestRunStatus
from trading.core.settings import Settings
from trading.data.market import RawOhlcvBatch
from trading.data.quality import normalize_ohlcv_batch
from trading.db.models import BacktestEquityPoint, BacktestRun, BacktestTrade
from trading.db.session import create_db_engine, create_session_factory
from trading.services.backtests import BacktestRunRequest, BacktestService
from trading.services.ingestion import IngestionService

pytestmark = pytest.mark.integration


def db_settings() -> Settings:
    return Settings(
        DATABASE_URL=os.environ.get(
            "DATABASE_URL",
            "postgresql://trading:trading@localhost:55432/trading",
        )
    )


def require_postgres() -> Settings:
    settings = db_settings()
    engine = None
    try:
        engine = create_db_engine(settings)
        with engine.connect() as connection:
            connection.execute(sa.text("SELECT 1"))
    except (ModuleNotFoundError, OperationalError) as exc:
        pytest.skip(f"Postgres is not reachable: {exc}")
    finally:
        if engine is not None:
            engine.dispose()
    return settings


def alembic_config(settings: Settings) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
    return config


def backtest_request() -> BacktestRunRequest:
    return BacktestRunRequest(
        exchange="binance",
        symbol="BTC/USDT",
        timeframe="1m",
        start=datetime(2026, 6, 1, 0, 0, tzinfo=UTC),
        end=datetime(2026, 6, 1, 0, 4, tzinfo=UTC),
        decision_time=datetime(2026, 6, 1, 1, 0, tzinfo=UTC),
        generated_at=datetime(2026, 6, 1, 2, 0, tzinfo=UTC),
        initial_capital=Decimal("1000"),
        fee_bps=Decimal("1"),
        slippage_bps=Decimal("2"),
        strategy_name="moving_average_crossover",
        strategy_parameters={"short_window": 1, "long_window": 2},
    )


def insert_candles(service: IngestionService) -> None:
    batch = RawOhlcvBatch(
        exchange="binance",
        symbol="BTC/USDT",
        timeframe="1m",
        rows=[
            ["2026-06-01T00:00:00Z", "100", "100", "100", "100", "10"],
            ["2026-06-01T00:01:00Z", "100", "102", "100", "102", "10"],
            ["2026-06-01T00:02:00Z", "102", "104", "102", "104", "10"],
            ["2026-06-01T00:03:00Z", "104", "104", "101", "101", "10"],
        ],
    )
    candles = normalize_ohlcv_batch(
        batch,
        raw_checksum="backtest-integration",
        now=datetime(2026, 6, 1, 1, 0, tzinfo=UTC),
    )
    assert service.insert_candles(candles) == 4


def test_backtest_runs_migration_and_real_db_persistence(tmp_path: Path) -> None:
    settings = require_postgres()
    config = alembic_config(settings)
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    engine = create_db_engine(settings)
    with engine.begin() as connection:
        table_name = connection.execute(
            sa.text("SELECT to_regclass('public.backtest_runs')")
        ).scalar_one()
        trades_table_name = connection.execute(
            sa.text("SELECT to_regclass('public.backtest_trades')")
        ).scalar_one()
        equity_table_name = connection.execute(
            sa.text("SELECT to_regclass('public.backtest_equity_points')")
        ).scalar_one()
        status_index = connection.execute(
            sa.text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'backtest_runs' "
                "AND indexname = 'ix_backtest_runs_status_created_at'"
            )
        ).scalar_one()
        trades_index = connection.execute(
            sa.text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'backtest_trades' "
                "AND indexname = 'ix_backtest_trades_run_id_timestamp'"
            )
        ).scalar_one()
        equity_index = connection.execute(
            sa.text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'backtest_equity_points' "
                "AND indexname = 'ix_backtest_equity_points_run_id_timestamp'"
            )
        ).scalar_one()

    assert table_name == "backtest_runs"
    assert trades_table_name == "backtest_trades"
    assert equity_table_name == "backtest_equity_points"
    assert status_index == "ix_backtest_runs_status_created_at"
    assert trades_index == "ix_backtest_trades_run_id_timestamp"
    assert equity_index == "ix_backtest_equity_points_run_id_timestamp"

    session_factory = create_session_factory(engine)
    insert_candles(IngestionService(session_factory))
    service = BacktestService(session_factory, reports_dir=tmp_path)
    request = backtest_request()

    first = service.run_backtest(request)
    second = service.run_backtest(request)
    retrieved = service.get_run(first.id)
    listed = service.list_runs(limit=10)

    assert first.status == BacktestRunStatus.SUCCEEDED.value
    assert first.dataset_hash is not None
    assert first.config_hash is not None
    assert first.result_hash is not None
    assert first.report_hash is not None
    assert first.metrics_json is not None
    assert first.report_json is not None
    assert first.artifact_path is not None
    assert Path(first.artifact_path).read_text(encoding="utf-8") == Path(
        second.artifact_path or ""
    ).read_text(encoding="utf-8")
    assert first.report_json == second.report_json
    assert first.report_hash == second.report_hash
    assert retrieved.id == first.id
    assert len(first.trades) == first.metrics_json["trades_count"]
    assert len(first.equity_points) == 4
    assert len(retrieved.trades) == first.metrics_json["trades_count"]
    assert len(retrieved.equity_points) == 4
    assert retrieved.trades[0].symbol == "BTC/USDT"
    assert retrieved.trades[0].side == "buy"
    assert [trade.timestamp for trade in retrieved.trades] == [
        datetime(2026, 6, 1, 0, 2, tzinfo=UTC),
        datetime(2026, 6, 1, 0, 3, tzinfo=UTC),
    ]
    assert [point.timestamp for point in retrieved.equity_points] == [
        datetime(2026, 6, 1, 0, 0, tzinfo=UTC),
        datetime(2026, 6, 1, 0, 1, tzinfo=UTC),
        datetime(2026, 6, 1, 0, 2, tzinfo=UTC),
        datetime(2026, 6, 1, 0, 3, tzinfo=UTC),
    ]
    assert first.id in {run.id for run in listed}

    failed = service.run_backtest(
        BacktestRunRequest(
            **{
                **request.__dict__,
                "decision_time": datetime(2026, 6, 1, 0, 30, tzinfo=UTC),
            }
        )
    )

    assert failed.status == BacktestRunStatus.FAILED.value
    assert failed.error_message is not None
    assert "eligible candle" in failed.error_message
    assert failed.trades == []
    assert failed.equity_points == []

    with session_factory() as session:
        failed_trade_count = session.scalar(
            sa.select(sa.func.count())
            .select_from(BacktestTrade)
            .where(BacktestTrade.run_id == failed.id)
        )
        failed_equity_count = session.scalar(
            sa.select(sa.func.count())
            .select_from(BacktestEquityPoint)
            .where(BacktestEquityPoint.run_id == failed.id)
        )
        historical_run = BacktestRun(
            status=BacktestRunStatus.SUCCEEDED.value,
            exchange=request.exchange,
            symbol=request.symbol,
            timeframe=request.timeframe,
            start=request.start,
            end=request.end,
            decision_time=request.decision_time,
            generated_at=request.generated_at,
            initial_capital=request.initial_capital,
            fee_bps=request.fee_bps,
            slippage_bps=request.slippage_bps,
            strategy_name=request.strategy_name,
            strategy_parameters=dict(request.strategy_parameters),
            dataset_hash="d" * 64,
            config_hash="c" * 64,
            result_hash="r" * 64,
            report_hash="h" * 64,
            metrics_json={"trades_count": 0},
            report_json={"metrics": {"trades_count": 0}},
            artifact_path=None,
            started_at=datetime(2026, 6, 1, 3, 0, tzinfo=UTC),
            completed_at=datetime(2026, 6, 1, 3, 1, tzinfo=UTC),
            error_message=None,
        )
        session.add(historical_run)
        session.commit()
        historical_run_id = historical_run.id

    assert failed_trade_count == 0
    assert failed_equity_count == 0

    historical_retrieved = service.get_run(historical_run_id)
    assert historical_retrieved.trades == []
    assert historical_retrieved.equity_points == []
