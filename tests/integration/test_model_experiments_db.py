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
from trading.services.backtests import deterministic_candle_dataset_hash
from trading.services.feature_sets import FeatureSetCreateRequest, FeatureSetService
from trading.services.ingestion import IngestionService
from trading.services.model_experiments import (
    ModelExperimentCreateRequest,
    ModelExperimentService,
    SplitDefinitionCreateRequest,
    SplitValidationError,
    SplitWindowCreateRequest,
)

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


def seed_feature_set(session_factory: sa.orm.sessionmaker[sa.orm.Session]) -> tuple[int, int]:
    ingestion = IngestionService(session_factory)
    batch = RawOhlcvBatch(
        exchange="binance",
        symbol="BTC/USDT",
        timeframe="1m",
        rows=[
            ["2026-06-01T00:00:00Z", "100", "100", "100", "100", "10"],
            ["2026-06-01T00:01:00Z", "101", "101", "101", "101", "11"],
            ["2026-06-01T00:02:00Z", "102", "102", "102", "102", "12"],
            ["2026-06-01T00:03:00Z", "103", "103", "103", "103", "13"],
            ["2026-06-01T00:04:00Z", "104", "104", "104", "104", "14"],
        ],
    )
    normalized = normalize_ohlcv_batch(
        batch,
        raw_checksum="model-experiment-spine",
        now=datetime(2026, 6, 1, 1, tzinfo=UTC),
    )
    ingestion.insert_candles(normalized)
    candles = ingestion.point_in_time_candles(
        exchange="binance",
        symbol="BTC/USDT",
        timeframe="1m",
        start_time=datetime(2026, 6, 1, 0, 0, tzinfo=UTC),
        end_time=datetime(2026, 6, 1, 0, 5, tzinfo=UTC),
        decision_time=datetime(2026, 6, 1, 1, tzinfo=UTC),
        source="binance",
    )
    dataset = ingestion.persist_dataset(
        name=(
            "backtest:binance:BTC/USDT:1m:"
            "2026-06-01T00:00:00Z:2026-06-01T00:04:00Z:2026-06-01T01:00:00Z"
        ),
        dataset_hash=deterministic_candle_dataset_hash(
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
        ),
        decision_time=datetime(2026, 6, 1, 1, tzinfo=UTC),
        artifact_id=None,
    )
    feature_set = FeatureSetService(session_factory).create_feature_set(
        FeatureSetCreateRequest(
            dataset_id=dataset.id,
            name="model-spine-features",
            parameters={"lookback": 2},
            code_version="candle_features_v1",
        )
    )
    return dataset.id, feature_set.id


def split_windows(
    *,
    decision_time: datetime = datetime(2026, 6, 1, 1, tzinfo=UTC),
) -> tuple[SplitWindowCreateRequest, ...]:
    return (
        SplitWindowCreateRequest(
            window_index=0,
            split_name="train",
            start=datetime(2026, 6, 1, 0, 1, tzinfo=UTC),
            end=datetime(2026, 6, 1, 0, 1, 30, tzinfo=UTC),
            decision_time=decision_time,
        ),
        SplitWindowCreateRequest(
            window_index=0,
            split_name="validation",
            start=datetime(2026, 6, 1, 0, 2, tzinfo=UTC),
            end=datetime(2026, 6, 1, 0, 2, 30, tzinfo=UTC),
            decision_time=decision_time,
        ),
        SplitWindowCreateRequest(
            window_index=0,
            split_name="test",
            start=datetime(2026, 6, 1, 0, 3, tzinfo=UTC),
            end=datetime(2026, 6, 1, 0, 4, 30, tzinfo=UTC),
            decision_time=decision_time,
        ),
    )


def split_payload(dataset_id: int, feature_set_id: int, *, name: str) -> dict[str, object]:
    return {
        "dataset_id": dataset_id,
        "feature_set_id": feature_set_id,
        "name": name,
        "split_type": "holdout",
        "config": {"seed": 7},
        "windows": [
            {
                "window_index": window.window_index,
                "split_name": window.split_name,
                "start": window.start.isoformat().replace("+00:00", "Z"),
                "end": window.end.isoformat().replace("+00:00", "Z"),
                "decision_time": window.decision_time.isoformat().replace("+00:00", "Z"),
            }
            for window in split_windows()
        ],
    }


def test_model_split_and_experiment_migration_service_and_api() -> None:
    settings = require_postgres()
    config = alembic_config(settings)
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    engine = create_db_engine(settings)
    session_factory = create_session_factory(engine)
    dataset_id, feature_set_id = seed_feature_set(session_factory)
    service = ModelExperimentService(session_factory)

    split = service.create_split_definition(
        SplitDefinitionCreateRequest(
            dataset_id=dataset_id,
            feature_set_id=feature_set_id,
            name="service-holdout",
            split_type="holdout",
            windows=split_windows(),
            config={"seed": 7},
        )
    )
    repeated_split = service.create_split_definition(
        SplitDefinitionCreateRequest(
            dataset_id=dataset_id,
            feature_set_id=feature_set_id,
            name="service-holdout",
            split_type="holdout",
            windows=split_windows(),
            config={"seed": 7},
        )
    )
    cascade_split = service.create_split_definition(
        SplitDefinitionCreateRequest(
            dataset_id=dataset_id,
            feature_set_id=feature_set_id,
            name="cascade-holdout",
            split_type="holdout",
            windows=split_windows(),
            config={},
        )
    )

    assert repeated_split.id == split.id
    assert split.dataset_id == dataset_id
    assert split.feature_set_id == feature_set_id
    assert split.split_hash == repeated_split.split_hash
    assert len(split.windows) == 3

    with pytest.raises(SplitValidationError, match="unavailable rows"):
        service.create_split_definition(
            SplitDefinitionCreateRequest(
                dataset_id=dataset_id,
                feature_set_id=feature_set_id,
                name="leaking-holdout",
                split_type="holdout",
                windows=split_windows(decision_time=datetime(2026, 6, 1, 0, 30, tzinfo=UTC)),
                config={},
            )
        )

    experiment = service.create_model_experiment(
        ModelExperimentCreateRequest(
            dataset_id=dataset_id,
            feature_set_id=feature_set_id,
            split_definition_id=split.id,
            name="baseline",
            model_name="logistic_regression",
            parameters={"alpha": 1},
            code_version="model_v1",
            metrics={"auc": "0.71"},
            status="succeeded",
            started_at=datetime(2026, 6, 1, 2, tzinfo=UTC),
            completed_at=datetime(2026, 6, 1, 2, 5, tzinfo=UTC),
        )
    )
    retrieved_experiment = service.get_model_experiment(experiment.id)
    listed_experiments = service.list_model_experiments(split_definition_id=split.id)

    assert retrieved_experiment.experiment_hash == experiment.experiment_hash
    assert listed_experiments[0].id == experiment.id
    assert experiment.parameter_hash

    with engine.begin() as connection:
        split_table = connection.execute(
            sa.text("SELECT to_regclass('public.split_definitions')")
        ).scalar_one()
        window_table = connection.execute(
            sa.text("SELECT to_regclass('public.split_windows')")
        ).scalar_one()
        experiment_table = connection.execute(
            sa.text("SELECT to_regclass('public.model_experiments')")
        ).scalar_one()
        split_config_type = connection.execute(
            sa.text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'split_definitions' AND column_name = 'config_json'"
            )
        ).scalar_one()
        experiment_metrics_type = connection.execute(
            sa.text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'model_experiments' AND column_name = 'metrics_json'"
            )
        ).scalar_one()
        split_index = connection.execute(
            sa.text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'split_definitions' "
                "AND indexname = 'ix_split_definitions_dataset_feature_set'"
            )
        ).scalar_one()
        experiment_index = connection.execute(
            sa.text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'model_experiments' "
                "AND indexname = 'ix_model_experiments_status_created_at'"
            )
        ).scalar_one()
        connection.execute(
            sa.text("DELETE FROM split_definitions WHERE id = :split_id"),
            {"split_id": cascade_split.id},
        )
        cascade_window_count = connection.execute(
            sa.text("SELECT count(*) FROM split_windows WHERE split_definition_id = :split_id"),
            {"split_id": cascade_split.id},
        ).scalar_one()

    assert split_table == "split_definitions"
    assert window_table == "split_windows"
    assert experiment_table == "model_experiments"
    assert split_config_type == "jsonb"
    assert experiment_metrics_type == "jsonb"
    assert split_index == "ix_split_definitions_dataset_feature_set"
    assert experiment_index == "ix_model_experiments_status_created_at"
    assert cascade_window_count == 0

    assert_integrity_error(
        engine,
        """
        INSERT INTO split_definitions (
            dataset_id, feature_set_id, name, split_type, split_hash, config_json
        )
        VALUES (
            :dataset_id, :feature_set_id, :name, :split_type, :split_hash,
            CAST(:config_json AS jsonb)
        )
        """,
        {
            "dataset_id": 999_999,
            "feature_set_id": feature_set_id,
            "name": "orphaned-split",
            "split_type": "holdout",
            "split_hash": "s" * 64,
            "config_json": json.dumps({}),
        },
    )
    assert_integrity_error(
        engine,
        """
        INSERT INTO model_experiments (
            id, dataset_id, feature_set_id, split_definition_id, name, model_name,
            parameter_hash, experiment_hash, code_version, parameters_json,
            metrics_json, status
        )
        VALUES (
            :id, :dataset_id, :feature_set_id, :split_definition_id, :name, :model_name,
            :parameter_hash, :experiment_hash, :code_version,
            CAST(:parameters_json AS jsonb), CAST(:metrics_json AS jsonb), :status
        )
        """,
        {
            "id": "22222222-2222-2222-2222-222222222222",
            "dataset_id": dataset_id,
            "feature_set_id": feature_set_id,
            "split_definition_id": 999_999,
            "name": "orphaned-experiment",
            "model_name": "logistic_regression",
            "parameter_hash": "p" * 64,
            "experiment_hash": "e" * 64,
            "code_version": "model_v1",
            "parameters_json": json.dumps({}),
            "metrics_json": json.dumps({}),
            "status": "created",
        },
    )

    app = create_app(Settings(APP_ENV="test", DATABASE_URL=settings.DATABASE_URL))
    with TestClient(app) as client:
        create_split_response = client.post(
            "/modeling/splits",
            json=split_payload(dataset_id, feature_set_id, name="api-holdout"),
        )
        assert create_split_response.status_code == 200
        api_split = create_split_response.json()
        get_split_response = client.get(f"/modeling/splits/{api_split['id']}")
        list_split_response = client.get(f"/modeling/splits?dataset_id={dataset_id}&limit=10")
        create_experiment_response = client.post(
            "/modeling/experiments",
            json={
                "dataset_id": dataset_id,
                "feature_set_id": feature_set_id,
                "split_definition_id": api_split["id"],
                "name": "api-baseline",
                "model_name": "logistic_regression",
                "parameters": {"alpha": 1},
                "code_version": "model_v1",
                "metrics": {"auc": "0.72"},
                "status": "succeeded",
                "started_at": "2026-06-01T02:00:00Z",
                "completed_at": "2026-06-01T02:05:00Z",
            },
        )
        assert create_experiment_response.status_code == 200
        api_experiment = create_experiment_response.json()
        get_experiment_response = client.get(f"/modeling/experiments/{api_experiment['id']}")
        list_experiment_response = client.get(
            f"/modeling/experiments?split_definition_id={api_split['id']}&limit=10"
        )

    assert get_split_response.status_code == 200
    assert list_split_response.status_code == 200
    assert api_split["feature_set_id"] == feature_set_id
    assert len(api_split["windows"]) == 3
    assert get_experiment_response.status_code == 200
    assert list_experiment_response.status_code == 200
    assert api_experiment["dataset_id"] == dataset_id
    assert api_experiment["metrics"] == {"auc": "0.72"}

    command.downgrade(config, "base")
    command.upgrade(config, "head")
