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
    BaselineEvaluationRequest,
    LabelCreateRequest,
    ModelExperimentCreateRequest,
    ModelExperimentService,
    ModelingConflictError,
    ModelPredictionCreateRequest,
    PromotionGateRequest,
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
            ["2026-06-01T00:05:00Z", "105", "105", "105", "105", "15"],
            ["2026-06-01T00:06:00Z", "106", "106", "106", "106", "16"],
            ["2026-06-01T00:07:00Z", "107", "107", "107", "107", "17"],
            ["2026-06-01T00:08:00Z", "108", "108", "108", "108", "18"],
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
        end_time=datetime(2026, 6, 1, 0, 9, tzinfo=UTC),
        decision_time=datetime(2026, 6, 1, 1, tzinfo=UTC),
        source="binance",
    )
    dataset = ingestion.persist_dataset(
        name=(
            "backtest:binance:BTC/USDT:1m:"
            "2026-06-01T00:00:00Z:2026-06-01T00:08:00Z:2026-06-01T01:00:00Z"
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


def baseline_split_windows(
    *,
    decision_time: datetime = datetime(2026, 6, 1, 1, tzinfo=UTC),
) -> tuple[SplitWindowCreateRequest, ...]:
    return (
        SplitWindowCreateRequest(
            window_index=0,
            split_name="train",
            start=datetime(2026, 6, 1, 0, 1, tzinfo=UTC),
            end=datetime(2026, 6, 1, 0, 2, 30, tzinfo=UTC),
            decision_time=decision_time,
        ),
        SplitWindowCreateRequest(
            window_index=0,
            split_name="validation",
            start=datetime(2026, 6, 1, 0, 3, tzinfo=UTC),
            end=datetime(2026, 6, 1, 0, 4, 30, tzinfo=UTC),
            decision_time=decision_time,
        ),
        SplitWindowCreateRequest(
            window_index=0,
            split_name="test",
            start=datetime(2026, 6, 1, 0, 5, tzinfo=UTC),
            end=datetime(2026, 6, 1, 0, 6, 30, tzinfo=UTC),
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


def baseline_split_payload(dataset_id: int, feature_set_id: int, *, name: str) -> dict[str, object]:
    return {
        "dataset_id": dataset_id,
        "feature_set_id": feature_set_id,
        "name": name,
        "split_type": "holdout",
        "config": {"purpose": "baseline-evaluation"},
        "windows": [
            {
                "window_index": window.window_index,
                "split_name": window.split_name,
                "start": window.start.isoformat().replace("+00:00", "Z"),
                "end": window.end.isoformat().replace("+00:00", "Z"),
                "decision_time": window.decision_time.isoformat().replace("+00:00", "Z"),
            }
            for window in baseline_split_windows()
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
    baseline_split = service.create_split_definition(
        SplitDefinitionCreateRequest(
            dataset_id=dataset_id,
            feature_set_id=feature_set_id,
            name="baseline-holdout",
            split_type="holdout",
            windows=baseline_split_windows(),
            config={"purpose": "baseline-evaluation"},
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
        feature_row = (
            connection.execute(
                sa.text(
                    "SELECT id, pair_id, timeframe, timestamp, feature_hash, decision_time "
                    "FROM feature_rows "
                    "WHERE feature_set_id = :feature_set_id "
                    "ORDER BY timestamp LIMIT 1"
                ),
                {"feature_set_id": feature_set_id},
            )
            .mappings()
            .one()
        )
        features_with_labels = connection.execute(
            sa.text(
                "SELECT count(*) FROM feature_rows "
                "WHERE feature_set_id = :feature_set_id "
                "AND (features_json ? 'label' "
                "OR features_json ? 'labels' "
                "OR features_json ? 'target')"
            ),
            {"feature_set_id": feature_set_id},
        ).scalar_one()

    assert features_with_labels == 0

    label = service.create_label(
        LabelCreateRequest(
            dataset_id=dataset_id,
            feature_set_id=feature_set_id,
            feature_row_id=feature_row["id"],
            feature_hash=feature_row["feature_hash"],
            label_name="forward_return_1",
            label_value={"direction": "up", "return": "0.01"},
            observed_at=datetime(2026, 6, 1, 1, 1, tzinfo=UTC),
            metadata={"horizon": "1m"},
        )
    )
    prediction = service.create_model_prediction(
        ModelPredictionCreateRequest(
            model_experiment_id=experiment.id,
            feature_set_id=feature_set_id,
            feature_row_id=feature_row["id"],
            feature_hash=feature_row["feature_hash"],
            prediction_value={"direction": "up", "score": "0.71"},
            confidence="0.71",
            decision_time=feature_row["decision_time"],
            lineage={"source": "integration"},
        )
    )
    gate = service.evaluate_promotion_gate(
        experiment.id,
        PromotionGateRequest(metric_path="auc", minimum_value="0.70"),
    )

    assert service.get_label(label.id).label_hash == label.label_hash
    assert service.list_labels(feature_set_id=feature_set_id)[0].id == label.id
    assert label.label_value == {"direction": "up", "return": "0.01"}
    assert service.get_model_prediction(prediction.id).prediction_hash == (
        prediction.prediction_hash
    )
    assert service.list_model_predictions(model_experiment_id=experiment.id)[0].id == prediction.id
    assert prediction.dataset_id == dataset_id
    assert prediction.split_definition_id == split.id
    assert gate.approved is True
    assert gate.reason == "metric threshold passed"

    with pytest.raises(ModelingConflictError, match="label already exists"):
        service.create_label(
            LabelCreateRequest(
                dataset_id=dataset_id,
                feature_set_id=feature_set_id,
                feature_row_id=feature_row["id"],
                feature_hash=feature_row["feature_hash"],
                label_name="forward_return_1",
                label_value={"direction": "up", "return": "0.01"},
                observed_at=datetime(2026, 6, 1, 1, 1, tzinfo=UTC),
                metadata={"horizon": "1m"},
            )
        )
    with pytest.raises(ModelingConflictError, match="model prediction already exists"):
        service.create_model_prediction(
            ModelPredictionCreateRequest(
                model_experiment_id=experiment.id,
                feature_set_id=feature_set_id,
                feature_row_id=feature_row["id"],
                feature_hash=feature_row["feature_hash"],
                prediction_value={"direction": "up", "score": "0.71"},
                confidence="0.71",
                decision_time=feature_row["decision_time"],
                lineage={"source": "integration"},
            )
        )

    baseline_experiment = service.evaluate_baseline_model(
        BaselineEvaluationRequest(
            dataset_id=dataset_id,
            feature_set_id=feature_set_id,
            split_definition_id=baseline_split.id,
            name="service-previous-return",
            parameters={"note": "integration"},
        )
    )
    assert baseline_experiment.dataset_id == dataset_id
    assert baseline_experiment.feature_set_id == feature_set_id
    assert baseline_experiment.split_definition_id == baseline_split.id
    assert baseline_experiment.model_name == "previous_return_direction"
    assert baseline_experiment.status == "succeeded"
    assert baseline_experiment.parameters["parameters"] == {"note": "integration"}
    assert baseline_experiment.parameters["split_definition"]["split_hash"] == (
        baseline_split.split_hash
    )
    assert baseline_experiment.metrics["overall"]["observations"] == 3
    assert baseline_experiment.metrics["overall"]["accuracy"] == 1.0
    assert baseline_experiment.metrics["by_split"]["train"]["observations"] == 1

    baseline_materialization = service.evaluate_baseline_materialization(
        BaselineEvaluationRequest(
            dataset_id=dataset_id,
            feature_set_id=feature_set_id,
            split_definition_id=baseline_split.id,
            name="service-previous-return-materialized",
            parameters={"note": "integration-materialized"},
            persist_predictions=True,
            persist_labels=True,
        )
    )
    assert baseline_materialization.experiment.dataset_id == dataset_id
    assert baseline_materialization.experiment.split_definition_id == baseline_split.id
    assert baseline_materialization.prediction_count == 3
    assert baseline_materialization.label_count == 3
    assert baseline_materialization.skipped_first_row_count == 3
    assert baseline_materialization.split_counts["train"]["prediction_count"] == 1
    assert baseline_materialization.window_counts[0].skipped_first_row_count == 1

    with engine.begin() as connection:
        persisted_baseline_labels = connection.execute(
            sa.text(
                "SELECT count(*) FROM labels "
                "WHERE feature_set_id = :feature_set_id "
                "AND label_name = 'close_return_1_direction'"
            ),
            {"feature_set_id": feature_set_id},
        ).scalar_one()
        persisted_baseline_predictions = connection.execute(
            sa.text(
                "SELECT count(*) FROM model_predictions "
                "WHERE model_experiment_id = :model_experiment_id"
            ),
            {"model_experiment_id": str(baseline_materialization.experiment.id)},
        ).scalar_one()
        persisted_baseline_prediction_row = (
            connection.execute(
                sa.text(
                    "SELECT prediction_value_json, confidence, lineage_json "
                    "FROM model_predictions "
                    "WHERE model_experiment_id = :model_experiment_id "
                    "ORDER BY timestamp LIMIT 1"
                ),
                {"model_experiment_id": str(baseline_materialization.experiment.id)},
            )
            .mappings()
            .one()
        )

    assert persisted_baseline_labels == 3
    assert persisted_baseline_predictions == 3
    assert persisted_baseline_prediction_row["prediction_value_json"]["source_feature"] == (
        "close_return_1"
    )
    assert persisted_baseline_prediction_row["confidence"] == 1
    assert persisted_baseline_prediction_row["lineage_json"]["producer"] == (
        "previous_return_direction"
    )

    with pytest.raises(ModelingConflictError, match="label already exists"):
        service.evaluate_baseline_materialization(
            BaselineEvaluationRequest(
                dataset_id=dataset_id,
                feature_set_id=feature_set_id,
                split_definition_id=baseline_split.id,
                name="service-previous-return-duplicate-labels",
                persist_predictions=False,
                persist_labels=True,
            )
        )

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
        label_table = connection.execute(
            sa.text("SELECT to_regclass('public.labels')")
        ).scalar_one()
        prediction_table = connection.execute(
            sa.text("SELECT to_regclass('public.model_predictions')")
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
        label_value_type = connection.execute(
            sa.text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'labels' AND column_name = 'label_value_json'"
            )
        ).scalar_one()
        prediction_value_type = connection.execute(
            sa.text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'model_predictions' "
                "AND column_name = 'prediction_value_json'"
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
        label_index = connection.execute(
            sa.text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'labels' "
                "AND indexname = 'ix_labels_dataset_feature_set'"
            )
        ).scalar_one()
        prediction_index = connection.execute(
            sa.text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'model_predictions' "
                "AND indexname = 'ix_model_predictions_experiment_decision'"
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
    assert label_table == "labels"
    assert prediction_table == "model_predictions"
    assert split_config_type == "jsonb"
    assert experiment_metrics_type == "jsonb"
    assert label_value_type == "jsonb"
    assert prediction_value_type == "jsonb"
    assert split_index == "ix_split_definitions_dataset_feature_set"
    assert experiment_index == "ix_model_experiments_status_created_at"
    assert label_index == "ix_labels_dataset_feature_set"
    assert prediction_index == "ix_model_predictions_experiment_decision"
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
    assert_integrity_error(
        engine,
        """
        INSERT INTO labels (
            dataset_id, feature_set_id, feature_row_id, pair_id, timeframe, timestamp,
            feature_hash, label_name, label_value_json, label_hash, decision_time,
            observed_at, metadata_json
        )
        VALUES (
            :dataset_id, :feature_set_id, :feature_row_id, :pair_id, :timeframe,
            :timestamp, :feature_hash, :label_name, CAST(:label_value_json AS jsonb),
            :label_hash, :decision_time, :observed_at, CAST(:metadata_json AS jsonb)
        )
        """,
        {
            "dataset_id": 999_999,
            "feature_set_id": feature_set_id,
            "feature_row_id": feature_row["id"],
            "pair_id": feature_row["pair_id"],
            "timeframe": feature_row["timeframe"],
            "timestamp": feature_row["timestamp"],
            "feature_hash": feature_row["feature_hash"],
            "label_name": "orphaned-label",
            "label_value_json": json.dumps({"direction": "up"}),
            "label_hash": "l" * 64,
            "decision_time": feature_row["decision_time"],
            "observed_at": datetime(2026, 6, 1, 1, 1, tzinfo=UTC),
            "metadata_json": json.dumps({}),
        },
    )
    assert_integrity_error(
        engine,
        """
        INSERT INTO model_predictions (
            model_experiment_id, dataset_id, feature_set_id, split_definition_id,
            feature_row_id, pair_id, timeframe, timestamp, feature_hash,
            prediction_value_json, confidence, decision_time,
            feature_row_decision_time, prediction_hash, lineage_json
        )
        VALUES (
            :model_experiment_id, :dataset_id, :feature_set_id, :split_definition_id,
            :feature_row_id, :pair_id, :timeframe, :timestamp, :feature_hash,
            CAST(:prediction_value_json AS jsonb), :confidence, :decision_time,
            :feature_row_decision_time, :prediction_hash, CAST(:lineage_json AS jsonb)
        )
        """,
        {
            "model_experiment_id": str(experiment.id),
            "dataset_id": dataset_id,
            "feature_set_id": feature_set_id,
            "split_definition_id": split.id,
            "feature_row_id": feature_row["id"],
            "pair_id": feature_row["pair_id"],
            "timeframe": feature_row["timeframe"],
            "timestamp": feature_row["timestamp"],
            "feature_hash": feature_row["feature_hash"],
            "prediction_value_json": json.dumps({"direction": "down"}),
            "confidence": "1.1",
            "decision_time": feature_row["decision_time"],
            "feature_row_decision_time": feature_row["decision_time"],
            "prediction_hash": "z" * 64,
            "lineage_json": json.dumps({}),
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
        create_baseline_split_response = client.post(
            "/modeling/splits",
            json=baseline_split_payload(dataset_id, feature_set_id, name="api-baseline-holdout"),
        )
        assert create_baseline_split_response.status_code == 200
        api_baseline_split = create_baseline_split_response.json()
        create_baseline_response = client.post(
            "/modeling/evaluations/baseline",
            json={
                "dataset_id": dataset_id,
                "feature_set_id": feature_set_id,
                "split_definition_id": api_baseline_split["id"],
                "name": "api-previous-return",
                "parameters": {"note": "api"},
            },
        )
        assert create_baseline_response.status_code == 200
        api_baseline = create_baseline_response.json()
        create_baseline_materialization_response = client.post(
            "/modeling/evaluations/baseline/materialize",
            json={
                "dataset_id": dataset_id,
                "feature_set_id": feature_set_id,
                "split_definition_id": api_baseline_split["id"],
                "name": "api-previous-return-materialized",
                "parameters": {"note": "api-materialized"},
                "persist_predictions": True,
                "persist_labels": False,
            },
        )
        assert create_baseline_materialization_response.status_code == 200
        api_baseline_materialization = create_baseline_materialization_response.json()
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
    assert api_baseline["split_definition_id"] == api_baseline_split["id"]
    assert api_baseline["model_name"] == "previous_return_direction"
    assert api_baseline["status"] == "succeeded"
    assert api_baseline["metrics"]["overall"]["observations"] == 3
    assert api_baseline["parameters"]["split_definition"]["id"] == api_baseline_split["id"]
    assert api_baseline_materialization["prediction_count"] == 3
    assert api_baseline_materialization["label_count"] == 0
    assert api_baseline_materialization["skipped_first_row_count"] == 3

    with engine.begin() as connection:
        connection.execute(
            sa.text("DELETE FROM feature_rows WHERE id = :feature_row_id"),
            {"feature_row_id": feature_row["id"]},
        )
        cascaded_label_count = connection.execute(
            sa.text("SELECT count(*) FROM labels WHERE id = :label_id"),
            {"label_id": label.id},
        ).scalar_one()
        cascaded_prediction_count = connection.execute(
            sa.text("SELECT count(*) FROM model_predictions WHERE id = :prediction_id"),
            {"prediction_id": prediction.id},
        ).scalar_one()

    assert cascaded_label_count == 0
    assert cascaded_prediction_count == 0

    command.downgrade(config, "base")
    command.upgrade(config, "head")
