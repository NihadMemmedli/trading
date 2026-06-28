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
from trading.data.market import (
    IngestionStatus,
    OhlcvRequest,
    RawDerivativesMetricBatch,
    RawOhlcvBatch,
    RawOrderBookBatch,
    RawTradeBatch,
)
from trading.data.quality import (
    normalize_derivatives_metric_batch,
    normalize_ohlcv_batch,
    normalize_order_book_batch,
    normalize_trade_batch,
)
from trading.db.session import create_db_engine, create_session_factory
from trading.services.ingestion import (
    DuplicateCandleError,
    DuplicateDerivativesMetricError,
    DuplicateOrderBookSnapshotError,
    DuplicateTradeError,
    IngestionService,
)
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
        order_book_hypertable = connection.execute(
            sa.text(
                "SELECT table_name FROM _timescaledb_catalog.hypertable "
                "WHERE table_name = 'order_book_snapshots'"
            )
        ).scalar_one()
        derivatives_hypertable = connection.execute(
            sa.text(
                "SELECT table_name FROM _timescaledb_catalog.hypertable "
                "WHERE table_name = 'derivatives_metrics'"
            )
        ).scalar_one()

    assert extension == "timescaledb"
    assert hypertable == "candles"
    assert trades_hypertable == "trades"
    assert order_book_hypertable == "order_book_snapshots"
    assert derivatives_hypertable == "derivatives_metrics"

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

    order_book_batch = RawOrderBookBatch(
        exchange="binance",
        symbol="ETH/USDT",
        rows=[
            {
                "timestamp": "2026-06-01T00:00:20Z",
                "bids": [["105.00", "1.0"], ["104.90", "2.0"]],
                "asks": [["105.10", "1.5"], ["105.20", "2.5"]],
            },
            {
                "timestamp": "2026-06-01T00:01:20Z",
                "bids": [["110.00", "1.0"], ["109.90", "2.0"]],
                "asks": [["110.10", "1.5"], ["110.20", "2.5"]],
            },
        ],
    )
    order_books = normalize_order_book_batch(
        order_book_batch,
        raw_checksum="integration-order-books",
        now=datetime(2026, 6, 1, 1, 0, tzinfo=UTC),
    )

    assert service.insert_order_book_snapshots(order_books) == 2
    with pytest.raises(DuplicateOrderBookSnapshotError):
        service.insert_order_book_snapshots(order_books)

    before_order_books_available = service.point_in_time_order_books(
        exchange="binance",
        symbol="ETH/USDT",
        decision_time=datetime(2026, 6, 1, 0, 30, tzinfo=UTC),
    )
    bounded_order_book_replay = service.point_in_time_order_books(
        exchange="binance",
        symbol="ETH/USDT",
        decision_time=datetime(2026, 6, 1, 1, 0, tzinfo=UTC),
        start_time=datetime(2026, 6, 1, 0, 1, tzinfo=UTC),
        end_time=datetime(2026, 6, 1, 0, 2, tzinfo=UTC),
        source="binance",
    )
    missing_order_book_pair = service.point_in_time_order_books(
        exchange="binance",
        symbol="BTC/USDT",
        decision_time=datetime(2026, 6, 1, 1, 0, tzinfo=UTC),
    )

    assert before_order_books_available == []
    assert [snapshot.best_bid for snapshot in bounded_order_book_replay] == [Decimal("110.00")]
    assert missing_order_book_pair == []

    derivatives_batch = RawDerivativesMetricBatch(
        exchange="binance",
        symbol="ETH/USDT",
        rows=[
            {
                "timestamp": "2026-06-01T00:00:00Z",
                "funding_rate": "0.0001",
                "open_interest": "1000",
            },
            {
                "timestamp": "2026-06-01T00:01:00Z",
                "funding_rate": "-0.0002",
                "long_short_ratio": "1.5",
                "liquidation_long_volume": "3",
                "liquidation_short_volume": "4",
            },
        ],
    )
    derivatives_metrics = normalize_derivatives_metric_batch(
        derivatives_batch,
        raw_checksum="integration-derivatives",
        now=datetime(2026, 6, 1, 1, 0, tzinfo=UTC),
    )

    assert service.insert_derivatives_metrics(derivatives_metrics) == 2
    with pytest.raises(DuplicateDerivativesMetricError):
        service.insert_derivatives_metrics(derivatives_metrics)

    before_derivatives_available = service.point_in_time_derivatives_metrics(
        exchange="binance",
        symbol="ETH/USDT",
        decision_time=datetime(2026, 6, 1, 0, 30, tzinfo=UTC),
    )
    bounded_derivatives_replay = service.point_in_time_derivatives_metrics(
        exchange="binance",
        symbol="ETH/USDT",
        decision_time=datetime(2026, 6, 1, 1, 0, tzinfo=UTC),
        start_time=datetime(2026, 6, 1, 0, 1, tzinfo=UTC),
        end_time=datetime(2026, 6, 1, 0, 2, tzinfo=UTC),
        source="binance",
    )
    missing_derivatives_pair = service.point_in_time_derivatives_metrics(
        exchange="binance",
        symbol="BTC/USDT",
        decision_time=datetime(2026, 6, 1, 1, 0, tzinfo=UTC),
    )

    assert before_derivatives_available == []
    assert [metric.funding_rate for metric in bounded_derivatives_replay] == [Decimal("-0.0002")]
    assert missing_derivatives_pair == []

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
        order_book_pit_index = connection.execute(
            sa.text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'order_book_snapshots' "
                "AND indexname = 'ix_order_book_pit_replay'"
            )
        ).scalar_one()
        derivatives_pit_index = connection.execute(
            sa.text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'derivatives_metrics' "
                "AND indexname = 'ix_derivatives_metrics_pit_replay'"
            )
        ).scalar_one()

    assert btc_pair_count == 0
    assert pit_index == "ix_candles_pit_replay"
    assert trade_pit_index == "ix_trades_pit_replay"
    assert order_book_pit_index == "ix_order_book_pit_replay"
    assert derivatives_pit_index == "ix_derivatives_metrics_pit_replay"

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
