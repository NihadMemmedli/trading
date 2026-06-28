from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.exc import OperationalError

from alembic import command
from trading.core.settings import Settings
from trading.data.market import IngestionStatus, OhlcvRequest, RawOhlcvBatch, RawTradeBatch
from trading.data.quality import normalize_ohlcv_batch, normalize_trade_batch
from trading.db.session import create_db_engine, create_session_factory
from trading.services.ingestion import DuplicateCandleError, DuplicateTradeError, IngestionService
from trading.services.ingestion_worker import OhlcvIngestionWorker

pytestmark = pytest.mark.integration


def db_settings() -> Settings:
    return Settings(
        DATABASE_URL=os.environ.get(
            "DATABASE_URL", "postgresql://trading:trading@localhost:55432/trading"
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


class FakeOhlcvAdapter:
    def __init__(self, batch: RawOhlcvBatch) -> None:
        self.batch = batch
        self.requests: list[OhlcvRequest] = []

    def fetch_ohlcv(self, request: OhlcvRequest) -> RawOhlcvBatch:
        self.requests.append(request)
        return self.batch


def test_alembic_timescale_candles_and_point_in_time_queries() -> None:
    settings = require_postgres()
    config = alembic_config(settings)
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    engine = create_db_engine(settings)
    with engine.begin() as connection:
        extension = connection.execute(
            sa.text("SELECT extname FROM pg_extension WHERE extname = 'timescaledb'")
        ).scalar_one()
        hypertable = connection.execute(
            sa.text(
                "SELECT table_name FROM _timescaledb_catalog.hypertable "
                "WHERE table_name = 'candles'"
            )
        ).scalar_one()
        trades_hypertable = connection.execute(
            sa.text(
                "SELECT table_name FROM _timescaledb_catalog.hypertable WHERE table_name = 'trades'"
            )
        ).scalar_one()

    assert extension == "timescaledb"
    assert hypertable == "candles"
    assert trades_hypertable == "trades"

    service = IngestionService(create_session_factory(engine))
    batch = RawOhlcvBatch(
        exchange="binance",
        symbol="ETH/USDT",
        timeframe="1m",
        rows=[
            ["2026-06-01T00:00:00Z", "100", "110", "95", "105", "10"],
            ["2026-06-01T00:01:00Z", "105", "115", "100", "110", "11"],
        ],
    )
    candles = normalize_ohlcv_batch(
        batch,
        raw_checksum="integration",
        now=datetime(2026, 6, 1, 1, 0, tzinfo=UTC),
    )

    assert service.insert_candles(candles) == 2
    with pytest.raises(DuplicateCandleError):
        service.insert_candles(candles)

    before_available = service.point_in_time_candles(
        exchange="binance",
        symbol="ETH/USDT",
        timeframe="1m",
        decision_time=datetime(2026, 6, 1, 0, 30, tzinfo=UTC),
    )
    after_available = service.point_in_time_candles(
        exchange="binance",
        symbol="ETH/USDT",
        timeframe="1m",
        decision_time=datetime(2026, 6, 1, 1, 0, tzinfo=UTC),
    )
    bounded_replay = service.point_in_time_candles(
        exchange="binance",
        symbol="ETH/USDT",
        timeframe="1m",
        decision_time=datetime(2026, 6, 1, 1, 0, tzinfo=UTC),
        start_time=datetime(2026, 6, 1, 0, 1, tzinfo=UTC),
        end_time=datetime(2026, 6, 1, 0, 2, tzinfo=UTC),
        source="binance",
    )
    missing_pair = service.point_in_time_candles(
        exchange="binance",
        symbol="BTC/USDT",
        timeframe="1m",
        decision_time=datetime(2026, 6, 1, 1, 0, tzinfo=UTC),
    )

    assert before_available == []
    assert [candle.close for candle in after_available] == [Decimal("105"), Decimal("110")]
    assert [candle.close for candle in bounded_replay] == [Decimal("110")]
    assert missing_pair == []

    trade_batch = RawTradeBatch(
        exchange="binance",
        symbol="ETH/USDT",
        rows=[
            {
                "id": "eth-trade-1",
                "timestamp": "2026-06-01T00:00:10Z",
                "side": "buy",
                "price": "105.50",
                "amount": "1.25",
            },
            {
                "id": "eth-trade-2",
                "timestamp": "2026-06-01T00:01:10Z",
                "side": "sell",
                "price": "110.25",
                "amount": "0.75",
            },
        ],
    )
    trades = normalize_trade_batch(
        trade_batch,
        raw_checksum="integration-trades",
        now=datetime(2026, 6, 1, 1, 0, tzinfo=UTC),
    )

    assert service.insert_trades(trades) == 2
    with pytest.raises(DuplicateTradeError):
        service.insert_trades(trades)

    before_trades_available = service.point_in_time_trades(
        exchange="binance",
        symbol="ETH/USDT",
        decision_time=datetime(2026, 6, 1, 0, 30, tzinfo=UTC),
    )
    bounded_trade_replay = service.point_in_time_trades(
        exchange="binance",
        symbol="ETH/USDT",
        decision_time=datetime(2026, 6, 1, 1, 0, tzinfo=UTC),
        start_time=datetime(2026, 6, 1, 0, 1, tzinfo=UTC),
        end_time=datetime(2026, 6, 1, 0, 2, tzinfo=UTC),
        source="binance",
    )
    missing_trade_pair = service.point_in_time_trades(
        exchange="binance",
        symbol="BTC/USDT",
        decision_time=datetime(2026, 6, 1, 1, 0, tzinfo=UTC),
    )

    assert before_trades_available == []
    assert [trade.trade_id for trade in bounded_trade_replay] == ["eth-trade-2"]
    assert missing_trade_pair == []

    with engine.begin() as connection:
        btc_pair_count = connection.execute(
            sa.text("SELECT count(*) FROM trading_pairs WHERE symbol = 'BTC/USDT'")
        ).scalar_one()
        pit_index = connection.execute(
            sa.text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'candles' AND indexname = 'ix_candles_pit_replay'"
            )
        ).scalar_one()
        trade_pit_index = connection.execute(
            sa.text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'trades' AND indexname = 'ix_trades_pit_replay'"
            )
        ).scalar_one()

    assert btc_pair_count == 0
    assert pit_index == "ix_candles_pit_replay"
    assert trade_pit_index == "ix_trades_pit_replay"

    command.downgrade(config, "base")
    command.upgrade(config, "head")


def test_worker_processes_api_created_ohlcv_run(tmp_path) -> None:  # noqa: ANN001
    settings = require_postgres()
    config = alembic_config(settings)
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    engine = create_db_engine(settings)
    service = IngestionService(create_session_factory(engine))
    request = OhlcvRequest(symbol="BTC/USDT", timeframe="1m", limit=2)
    run = service.create_ohlcv_run(request)
    batch = RawOhlcvBatch(
        exchange="binance",
        symbol="BTC/USDT",
        timeframe="1m",
        fetched_at=datetime(2026, 6, 1, 1, 0, tzinfo=UTC),
        rows=[
            ["2026-06-01T00:00:00Z", "100", "110", "95", "105", "10"],
            ["2026-06-01T00:01:00Z", "105", "115", "100", "110", "11"],
        ],
    )
    adapter = FakeOhlcvAdapter(batch)
    worker = OhlcvIngestionWorker(service=service, adapter=adapter, archive_root=tmp_path)

    result = worker.process_next_pending_run()

    assert result is not None
    assert result.run_id == run.id
    assert result.status == IngestionStatus.SUCCEEDED
    assert adapter.requests[0].limit == 2

    completed = service.get_run(run.id)
    assert completed.status == IngestionStatus.SUCCEEDED.value
    assert completed.rows_raw == 2
    assert completed.rows_normalized == 2
    assert completed.started_at is not None
    assert completed.completed_at is not None

    candles = service.point_in_time_candles(
        exchange="binance",
        symbol="BTC/USDT",
        timeframe="1m",
        decision_time=datetime(2026, 6, 1, 1, 0, tzinfo=UTC),
    )
    assert len(candles) == 2

    duplicate_run = service.create_ohlcv_run(request)
    duplicate_result = worker.process_next_pending_run()
    assert duplicate_result is not None
    assert duplicate_result.run_id == duplicate_run.id
    assert duplicate_result.status == IngestionStatus.FAILED

    failed = service.get_run(duplicate_run.id)
    assert failed.status == IngestionStatus.FAILED.value
    assert failed.error_message is not None
    assert "DuplicateCandleError" in failed.error_message

    assert worker.process_next_pending_run() is None
