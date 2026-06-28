from __future__ import annotations

import json
import os
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, OperationalError

from alembic import command
from trading.apps.api import create_app
from trading.core.settings import Settings
from trading.data.market import NormalizedCandle, RawOhlcvBatch
from trading.data.quality import normalize_ohlcv_batch
from trading.db.session import create_db_engine, create_session_factory
from trading.features import FeatureSetLeakageError
from trading.services.backtests import deterministic_candle_dataset_hash
from trading.services.feature_sets import FeatureSetCreateRequest, FeatureSetService
from trading.services.ingestion import IngestionService

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


def assert_integrity_error(
    engine: sa.Engine,
    statement: str,
    params: dict[str, object],
) -> None:
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(sa.text(statement), params)


def test_feature_set_registry_migration_and_materialized_rows() -> None:
    settings = require_postgres()
    config = alembic_config(settings)
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    engine = create_db_engine(settings)
    session_factory = create_session_factory(engine)
    ingestion = IngestionService(session_factory)
    batch = RawOhlcvBatch(
        exchange="binance",
        symbol="BTC/USDT",
        timeframe="1m",
        rows=[
            ["2026-06-01T00:00:00Z", "100", "100", "100", "100", "10"],
            ["2026-06-01T00:01:00Z", "110", "110", "110", "110", "11"],
            ["2026-06-01T00:02:00Z", "121", "121", "121", "121", "12"],
        ],
    )
    normalized = normalize_ohlcv_batch(
        batch,
        raw_checksum="feature-integration",
        now=datetime(2026, 6, 1, 1, tzinfo=UTC),
    )
    ingestion.insert_candles(normalized)
    candles = ingestion.point_in_time_candles(
        exchange="binance",
        symbol="BTC/USDT",
        timeframe="1m",
        start_time=datetime(2026, 6, 1, 0, 0, tzinfo=UTC),
        end_time=datetime(2026, 6, 1, 0, 3, tzinfo=UTC),
        decision_time=datetime(2026, 6, 1, 1, tzinfo=UTC),
        source="binance",
    )
    assert len(candles) == 3
    dataset_hash = deterministic_candle_dataset_hash(
        tuple(
            NormalizedCandle(
                exchange="binance",
                symbol="BTC/USDT",
                timeframe=candle.timeframe,
                timestamp=candle.timestamp,
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
                volume=candle.volume,
                available_at=candle.available_at,
                raw_checksum=candle.raw_checksum,
                quality_flags=candle.quality_flags,
            )
            for candle in candles
        )
    )
    dataset = ingestion.persist_dataset(
        name=(
            "backtest:binance:BTC/USDT:1m:"
            "2026-06-01T00:00:00Z:2026-06-01T00:02:00Z:2026-06-01T01:00:00Z"
        ),
        dataset_hash=dataset_hash,
        decision_time=datetime(2026, 6, 1, 1, tzinfo=UTC),
        artifact_id=None,
    )
    service = FeatureSetService(session_factory)

    feature_set = service.create_feature_set(
        FeatureSetCreateRequest(
            dataset_id=dataset.id,
            name="mvp-candles",
            parameters={"lookback": 2},
            code_version="candle_features_v1",
        )
    )
    fetched = service.get_feature_set(feature_set.id)
    listed = service.list_feature_sets(dataset_id=dataset.id)
    repeated = service.create_feature_set(
        FeatureSetCreateRequest(
            dataset_id=dataset.id,
            name="mvp-candles",
            parameters={"lookback": 2},
            code_version="candle_features_v1",
        )
    )

    assert feature_set.id == repeated.id
    assert fetched.dataset_id == dataset.id
    assert fetched.feature_row_count == 2
    assert [row.features["close_return_1"] for row in fetched.rows] == ["0.1", "0.1"]
    assert listed[0].feature_row_count == 2
    assert listed[0].rows == ()

    with engine.begin() as connection:
        feature_parameters_type = connection.execute(
            sa.text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'feature_sets' AND column_name = 'parameters_json'"
            )
        ).scalar_one()
        feature_values_type = connection.execute(
            sa.text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'feature_rows' AND column_name = 'features_json'"
            )
        ).scalar_one()
        feature_set_index = connection.execute(
            sa.text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'feature_sets' "
                "AND indexname = 'ix_feature_sets_dataset_id'"
            )
        ).scalar_one()
        feature_row_index = connection.execute(
            sa.text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'feature_rows' "
                "AND indexname = 'ix_feature_rows_pair_timeframe_available_at'"
            )
        ).scalar_one()
        relationship_count = connection.execute(
            sa.text(
                "SELECT count(*) FROM feature_sets fs "
                "JOIN datasets d ON d.id = fs.dataset_id "
                "JOIN feature_rows fr ON fr.feature_set_id = fs.id "
                "JOIN trading_pairs tp ON tp.id = fr.pair_id "
                "WHERE d.id = :dataset_id AND tp.symbol = 'BTC/USDT'"
            ),
            {"dataset_id": dataset.id},
        ).scalar_one()
        leaked_rows = connection.execute(
            sa.text("SELECT count(*) FROM feature_rows WHERE available_at > decision_time")
        ).scalar_one()
        persisted_row = (
            connection.execute(
                sa.text(
                    "SELECT fr.feature_set_id, fr.pair_id, fr.timeframe, fr.timestamp, "
                    "fr.decision_time, fr.available_at, fr.features_json, fr.feature_hash "
                    "FROM feature_rows fr "
                    "WHERE fr.feature_set_id = :feature_set_id "
                    "ORDER BY fr.timestamp "
                    "LIMIT 1"
                ),
                {"feature_set_id": feature_set.id},
            )
            .mappings()
            .one()
        )

    assert feature_parameters_type == "jsonb"
    assert feature_values_type == "jsonb"
    assert feature_set_index == "ix_feature_sets_dataset_id"
    assert feature_row_index == "ix_feature_rows_pair_timeframe_available_at"
    assert relationship_count == 2
    assert leaked_rows == 0

    assert_integrity_error(
        engine,
        """
        INSERT INTO feature_sets (
            dataset_id, name, dataset_hash, feature_set_hash, parameter_hash,
            code_version, parameters_json, feature_names_json, selector_json
        )
        VALUES (
            :dataset_id, :name, :dataset_hash, :feature_set_hash, :parameter_hash,
            :code_version, CAST(:parameters_json AS jsonb),
            CAST(:feature_names_json AS jsonb), CAST(:selector_json AS jsonb)
        )
        """,
        {
            "dataset_id": dataset.id,
            "name": feature_set.name,
            "dataset_hash": feature_set.dataset_hash,
            "feature_set_hash": "x" * 64,
            "parameter_hash": feature_set.parameter_hash,
            "code_version": feature_set.code_version,
            "parameters_json": json.dumps(feature_set.parameters),
            "feature_names_json": json.dumps(feature_set.feature_names),
            "selector_json": json.dumps(feature_set.selector),
        },
    )
    assert_integrity_error(
        engine,
        """
        INSERT INTO feature_sets (
            dataset_id, name, dataset_hash, feature_set_hash, parameter_hash,
            code_version, parameters_json, feature_names_json, selector_json
        )
        VALUES (
            :dataset_id, :name, :dataset_hash, :feature_set_hash, :parameter_hash,
            :code_version, CAST(:parameters_json AS jsonb),
            CAST(:feature_names_json AS jsonb), CAST(:selector_json AS jsonb)
        )
        """,
        {
            "dataset_id": 999_999,
            "name": "orphaned-feature-set",
            "dataset_hash": "d" * 64,
            "feature_set_hash": "s" * 64,
            "parameter_hash": "p" * 64,
            "code_version": "candle_features_v1",
            "parameters_json": json.dumps({"lookback": 2}),
            "feature_names_json": json.dumps(["close_return_1"]),
            "selector_json": json.dumps(feature_set.selector),
        },
    )
    assert_integrity_error(
        engine,
        """
        INSERT INTO feature_rows (
            feature_set_id, pair_id, timeframe, timestamp, decision_time, available_at,
            features_json, feature_hash
        )
        VALUES (
            :feature_set_id, :pair_id, :timeframe, :timestamp, :decision_time,
            :available_at, CAST(:features_json AS jsonb), :feature_hash
        )
        """,
        {
            "feature_set_id": persisted_row["feature_set_id"],
            "pair_id": persisted_row["pair_id"],
            "timeframe": persisted_row["timeframe"],
            "timestamp": persisted_row["timestamp"],
            "decision_time": persisted_row["decision_time"],
            "available_at": persisted_row["available_at"],
            "features_json": json.dumps(dict(persisted_row["features_json"])),
            "feature_hash": "u" * 64,
        },
    )
    assert_integrity_error(
        engine,
        """
        INSERT INTO feature_rows (
            feature_set_id, pair_id, timeframe, timestamp, decision_time, available_at,
            features_json, feature_hash
        )
        VALUES (
            :feature_set_id, :pair_id, :timeframe, :timestamp, :decision_time,
            :available_at, CAST(:features_json AS jsonb), :feature_hash
        )
        """,
        {
            "feature_set_id": 999_999,
            "pair_id": persisted_row["pair_id"],
            "timeframe": "1m",
            "timestamp": datetime(2026, 6, 1, 0, 3, tzinfo=UTC),
            "decision_time": datetime(2026, 6, 1, 1, tzinfo=UTC),
            "available_at": datetime(2026, 6, 1, 1, tzinfo=UTC),
            "features_json": json.dumps({"close_return_1": "0"}),
            "feature_hash": "f" * 64,
        },
    )
    assert_integrity_error(
        engine,
        """
        INSERT INTO feature_rows (
            feature_set_id, pair_id, timeframe, timestamp, decision_time, available_at,
            features_json, feature_hash
        )
        VALUES (
            :feature_set_id, :pair_id, :timeframe, :timestamp, :decision_time,
            :available_at, CAST(:features_json AS jsonb), :feature_hash
        )
        """,
        {
            "feature_set_id": feature_set.id,
            "pair_id": persisted_row["pair_id"],
            "timeframe": "1m",
            "timestamp": datetime(2026, 6, 1, 0, 4, tzinfo=UTC),
            "decision_time": datetime(2026, 6, 1, 1, tzinfo=UTC),
            "available_at": datetime(2026, 6, 1, 2, tzinfo=UTC),
            "features_json": json.dumps({"close_return_1": "0"}),
            "feature_hash": "c" * 64,
        },
    )

    with engine.begin() as connection:
        connection.execute(
            sa.text("DELETE FROM feature_sets WHERE id = :feature_set_id"),
            {"feature_set_id": feature_set.id},
        )
        orphaned_feature_rows = connection.execute(
            sa.text("SELECT count(*) FROM feature_rows WHERE feature_set_id = :feature_set_id"),
            {"feature_set_id": feature_set.id},
        ).scalar_one()

    assert orphaned_feature_rows == 0

    command.downgrade(config, "base")
    command.upgrade(config, "head")


def test_feature_set_materialization_rejects_dataset_hash_with_unavailable_candle() -> None:
    settings = require_postgres()
    config = alembic_config(settings)
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    engine = create_db_engine(settings)
    session_factory = create_session_factory(engine)
    ingestion = IngestionService(session_factory)
    first_batch = RawOhlcvBatch(
        exchange="binance",
        symbol="ETH/USDT",
        timeframe="1m",
        rows=[
            ["2026-06-01T00:00:00Z", "100", "100", "100", "100", "10"],
            ["2026-06-01T00:01:00Z", "110", "110", "110", "110", "11"],
        ],
    )
    leaked_batch = RawOhlcvBatch(
        exchange="binance",
        symbol="ETH/USDT",
        timeframe="1m",
        rows=[["2026-06-01T00:02:00Z", "121", "121", "121", "121", "12"]],
    )
    eligible = normalize_ohlcv_batch(
        first_batch,
        raw_checksum="feature-eligible",
        now=datetime(2026, 6, 1, 1, tzinfo=UTC),
    )
    leaked = normalize_ohlcv_batch(
        leaked_batch,
        raw_checksum="feature-leaked",
        now=datetime(2026, 6, 1, 2, tzinfo=UTC),
    )
    ingestion.insert_candles([*eligible, *leaked])
    registered_hash = deterministic_candle_dataset_hash(tuple([*eligible, *leaked]))
    dataset = ingestion.persist_dataset(
        name=(
            "backtest:binance:ETH/USDT:1m:"
            "2026-06-01T00:00:00Z:2026-06-01T00:02:00Z:2026-06-01T01:00:00Z"
        ),
        dataset_hash=registered_hash,
        decision_time=datetime(2026, 6, 1, 1, tzinfo=UTC),
        artifact_id=None,
    )
    service = FeatureSetService(session_factory)

    with pytest.raises(FeatureSetLeakageError, match="point-in-time candles"):
        service.create_feature_set(
            FeatureSetCreateRequest(
                dataset_id=dataset.id,
                name="mvp-candles",
                parameters={"lookback": 2},
                code_version="candle_features_v1",
            )
        )

    command.downgrade(config, "base")
    command.upgrade(config, "head")


def test_feature_set_api_create_get_list_with_real_db() -> None:
    settings = require_postgres()
    config = alembic_config(settings)
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    engine = create_db_engine(settings)
    session_factory = create_session_factory(engine)
    ingestion = IngestionService(session_factory)
    batch = RawOhlcvBatch(
        exchange="binance",
        symbol="SOL/USDT",
        timeframe="1m",
        rows=[
            ["2026-06-01T00:00:00Z", "20", "20", "20", "20", "100"],
            ["2026-06-01T00:01:00Z", "21", "21", "21", "21", "101"],
            ["2026-06-01T00:02:00Z", "22", "22", "22", "22", "102"],
        ],
    )
    normalized = normalize_ohlcv_batch(
        batch,
        raw_checksum="feature-api-smoke",
        now=datetime(2026, 6, 1, 1, tzinfo=UTC),
    )
    ingestion.insert_candles(normalized)
    candles = ingestion.point_in_time_candles(
        exchange="binance",
        symbol="SOL/USDT",
        timeframe="1m",
        start_time=datetime(2026, 6, 1, 0, 0, tzinfo=UTC),
        end_time=datetime(2026, 6, 1, 0, 3, tzinfo=UTC),
        decision_time=datetime(2026, 6, 1, 1, tzinfo=UTC),
        source="binance",
    )
    dataset = ingestion.persist_dataset(
        name=(
            "backtest:binance:SOL/USDT:1m:"
            "2026-06-01T00:00:00Z:2026-06-01T00:02:00Z:2026-06-01T01:00:00Z"
        ),
        dataset_hash=deterministic_candle_dataset_hash(
            tuple(
                NormalizedCandle(
                    exchange="binance",
                    symbol="SOL/USDT",
                    timeframe=candle.timeframe,
                    timestamp=candle.timestamp,
                    open=candle.open,
                    high=candle.high,
                    low=candle.low,
                    close=candle.close,
                    volume=candle.volume,
                    available_at=candle.available_at,
                    raw_checksum=candle.raw_checksum,
                    quality_flags=candle.quality_flags,
                )
                for candle in candles
            )
        ),
        decision_time=datetime(2026, 6, 1, 1, tzinfo=UTC),
        artifact_id=None,
    )
    app = create_app(Settings(APP_ENV="test", DATABASE_URL=settings.DATABASE_URL))

    with TestClient(app) as client:
        create_response = client.post(
            "/feature-sets",
            json={
                "dataset_id": dataset.id,
                "name": "api-candle-features",
                "parameters": {"lookback": 2},
                "code_version": "candle_features_v1",
            },
        )
        assert create_response.status_code == 200
        created = create_response.json()

        get_response = client.get(f"/feature-sets/{created['id']}")
        list_response = client.get(f"/feature-sets?dataset_id={dataset.id}&limit=10")

    assert created["dataset_id"] == dataset.id
    assert created["feature_row_count"] == 2
    assert len(created["rows"]) == 2
    assert get_response.status_code == 200
    assert get_response.json()["id"] == created["id"]
    assert list_response.status_code == 200
    listed = list_response.json()["feature_sets"]
    assert [item["id"] for item in listed] == [created["id"]]
    assert listed[0]["rows"] == []

    command.downgrade(config, "base")
    command.upgrade(config, "head")
