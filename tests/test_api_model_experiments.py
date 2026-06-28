from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from trading.apps.api import create_app
from trading.apps.api.dependencies import get_model_experiment_service
from trading.core.settings import Settings
from trading.services.model_experiments import (
    LabelNotFoundError,
    ModelExperimentLineageError,
    ModelExperimentNotFoundError,
    ModelingConflictError,
    ModelPredictionNotFoundError,
    SplitDefinitionNotFoundError,
    SplitValidationError,
)


class FakeModelExperimentService:
    def __init__(self) -> None:
        self.created_at = datetime(2026, 1, 1, tzinfo=UTC)
        self.experiment_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
        self.split_requests: list[object] = []
        self.experiment_requests: list[object] = []
        self.baseline_requests: list[object] = []
        self.label_requests: list[object] = []
        self.prediction_requests: list[object] = []
        self.promotion_gate_requests: list[object] = []

    def _window(self) -> SimpleNamespace:
        return SimpleNamespace(
            id=7,
            window_index=0,
            split_name="train",
            start=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
            end=datetime(2026, 1, 1, 0, 2, tzinfo=UTC),
            decision_time=datetime(2026, 1, 1, 1, tzinfo=UTC),
        )

    def _split_definition(self, **overrides: object) -> SimpleNamespace:
        defaults = {
            "id": 42,
            "dataset_id": 11,
            "feature_set_id": 12,
            "name": "holdout-v1",
            "split_type": "holdout",
            "split_hash": "s" * 64,
            "config": {"seed": 7},
            "created_at": self.created_at,
            "windows": [self._window()],
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def _experiment(self, **overrides: object) -> SimpleNamespace:
        defaults = {
            "id": self.experiment_id,
            "dataset_id": 11,
            "feature_set_id": 12,
            "split_definition_id": 42,
            "name": "baseline",
            "model_name": "logistic_regression",
            "parameter_hash": "p" * 64,
            "experiment_hash": "e" * 64,
            "code_version": "model_v1",
            "parameters": {"alpha": 1},
            "metrics": {"auc": "0.71"},
            "status": "succeeded",
            "started_at": datetime(2026, 1, 1, 2, tzinfo=UTC),
            "completed_at": datetime(2026, 1, 1, 2, 5, tzinfo=UTC),
            "created_at": self.created_at,
            "updated_at": self.created_at,
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def _label(self, **overrides: object) -> SimpleNamespace:
        defaults = {
            "id": 17,
            "dataset_id": 11,
            "feature_set_id": 12,
            "feature_row_id": 101,
            "pair_id": 1,
            "timeframe": "1m",
            "timestamp": datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
            "feature_hash": "a" * 64,
            "label_name": "forward_return_1",
            "label_value": {"direction": "up", "return": "0.01"},
            "label_hash": "l" * 64,
            "decision_time": datetime(2026, 1, 1, 1, tzinfo=UTC),
            "observed_at": datetime(2026, 1, 1, 1, 1, tzinfo=UTC),
            "metadata": {"horizon": "1m"},
            "created_at": self.created_at,
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def _prediction(self, **overrides: object) -> SimpleNamespace:
        defaults = {
            "id": 19,
            "model_experiment_id": self.experiment_id,
            "dataset_id": 11,
            "feature_set_id": 12,
            "split_definition_id": 42,
            "feature_row_id": 101,
            "pair_id": 1,
            "timeframe": "1m",
            "timestamp": datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
            "feature_hash": "a" * 64,
            "prediction_value": {"direction": "up"},
            "confidence": Decimal("0.75"),
            "decision_time": datetime(2026, 1, 1, 1, tzinfo=UTC),
            "feature_row_decision_time": datetime(2026, 1, 1, 1, tzinfo=UTC),
            "prediction_hash": "q" * 64,
            "lineage": {"source": "api-test"},
            "created_at": self.created_at,
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def _promotion_gate(self, **overrides: object) -> SimpleNamespace:
        defaults = {
            "model_experiment_id": self.experiment_id,
            "approved": True,
            "metric_path": "overall.accuracy",
            "metric_value": Decimal("0.8"),
            "minimum_value": Decimal("0.7"),
            "reason": "metric threshold passed",
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def create_split_definition(self, request: Any) -> SimpleNamespace:
        self.split_requests.append(request)
        dataset_id = request.dataset_id
        if dataset_id == 404:
            raise ModelExperimentLineageError("dataset not found")
        split_type = request.split_type
        if split_type == "walk_forward":
            raise SplitValidationError("window 0 must include train, validation, and test splits")
        return self._split_definition(dataset_id=dataset_id)

    def get_split_definition(self, split_definition_id: int) -> SimpleNamespace:
        if split_definition_id != 42:
            raise SplitDefinitionNotFoundError(str(split_definition_id))
        return self._split_definition()

    def list_split_definitions(
        self,
        *,
        limit: int = 50,
        dataset_id: int | None = None,
        feature_set_id: int | None = None,
    ) -> list[SimpleNamespace]:
        return [
            self._split_definition(
                dataset_id=dataset_id or 11,
                feature_set_id=feature_set_id or 12,
                windows=[],
            )
        ][:limit]

    def create_model_experiment(self, request: Any) -> SimpleNamespace:
        self.experiment_requests.append(request)
        split_definition_id = request.split_definition_id
        if split_definition_id == 404:
            raise SplitDefinitionNotFoundError(str(split_definition_id))
        status = request.status
        return self._experiment(status=status)

    def evaluate_baseline_model(self, request: Any) -> SimpleNamespace:
        self.baseline_requests.append(request)
        if request.dataset_id == 404:
            raise ModelExperimentLineageError("dataset not found")
        if request.dataset_id == 422:
            raise ModelExperimentLineageError("feature set dataset_id mismatch")
        if request.split_definition_id == 404:
            raise SplitDefinitionNotFoundError(str(request.split_definition_id))
        if request.split_definition_id == 422:
            raise SplitValidationError("test window 0 has no baseline observations")
        return self._experiment(
            name=request.name,
            model_name=request.baseline_name,
            code_version=request.code_version,
            parameters={
                "baseline": {"name": request.baseline_name},
                "parameters": request.parameters,
            },
            metrics={"overall": {"observations": 3, "accuracy": 1.0}},
            status="succeeded",
        )

    def get_model_experiment(self, experiment_id: uuid.UUID) -> SimpleNamespace:
        if experiment_id != self.experiment_id:
            raise ModelExperimentNotFoundError(str(experiment_id))
        return self._experiment()

    def list_model_experiments(
        self,
        *,
        limit: int = 50,
        dataset_id: int | None = None,
        feature_set_id: int | None = None,
        split_definition_id: int | None = None,
    ) -> list[SimpleNamespace]:
        return [
            self._experiment(
                dataset_id=dataset_id or 11,
                feature_set_id=feature_set_id or 12,
                split_definition_id=split_definition_id or 42,
            )
        ][:limit]

    def create_label(self, request: Any) -> SimpleNamespace:
        self.label_requests.append(request)
        if request.dataset_id == 404:
            raise ModelExperimentLineageError("dataset not found")
        if request.dataset_id == 422:
            raise ModelExperimentLineageError("feature set dataset_id mismatch")
        if request.label_name == "duplicate":
            raise ModelingConflictError("label already exists")
        return self._label(
            dataset_id=request.dataset_id,
            feature_set_id=request.feature_set_id,
            feature_row_id=request.feature_row_id,
            feature_hash=request.feature_hash,
            label_name=request.label_name,
            label_value=request.label_value,
            observed_at=request.observed_at,
            metadata=request.metadata,
        )

    def get_label(self, label_id: int) -> SimpleNamespace:
        if label_id != 17:
            raise LabelNotFoundError(str(label_id))
        return self._label()

    def list_labels(
        self,
        *,
        limit: int = 50,
        dataset_id: int | None = None,
        feature_set_id: int | None = None,
        feature_row_id: int | None = None,
        label_name: str | None = None,
    ) -> list[SimpleNamespace]:
        return [
            self._label(
                dataset_id=dataset_id or 11,
                feature_set_id=feature_set_id or 12,
                feature_row_id=feature_row_id or 101,
                label_name=label_name or "forward_return_1",
            )
        ][:limit]

    def create_model_prediction(self, request: Any) -> SimpleNamespace:
        self.prediction_requests.append(request)
        if request.model_experiment_id == uuid.UUID("22222222-2222-2222-2222-222222222222"):
            raise ModelExperimentNotFoundError(str(request.model_experiment_id))
        if request.feature_set_id == 422:
            raise ModelExperimentLineageError("model experiment feature_set_id mismatch")
        if request.feature_set_id == 409:
            raise ModelingConflictError("model prediction already exists")
        return self._prediction(
            model_experiment_id=request.model_experiment_id,
            feature_set_id=request.feature_set_id,
            feature_row_id=request.feature_row_id,
            feature_hash=request.feature_hash,
            prediction_value=request.prediction_value,
            confidence=request.confidence,
            decision_time=request.decision_time,
            lineage=request.lineage,
        )

    def get_model_prediction(self, prediction_id: int) -> SimpleNamespace:
        if prediction_id != 19:
            raise ModelPredictionNotFoundError(str(prediction_id))
        return self._prediction()

    def list_model_predictions(
        self,
        *,
        limit: int = 50,
        model_experiment_id: uuid.UUID | None = None,
        feature_set_id: int | None = None,
        feature_row_id: int | None = None,
    ) -> list[SimpleNamespace]:
        return [
            self._prediction(
                model_experiment_id=model_experiment_id or self.experiment_id,
                feature_set_id=feature_set_id or 12,
                feature_row_id=feature_row_id or 101,
            )
        ][:limit]

    def evaluate_promotion_gate(self, experiment_id: uuid.UUID, request: Any) -> SimpleNamespace:
        self.promotion_gate_requests.append(request)
        if experiment_id != self.experiment_id:
            raise ModelExperimentNotFoundError(str(experiment_id))
        if request.metric_path == "bad":
            raise SplitValidationError("metric_path must contain non-empty path segments")
        return self._promotion_gate(
            model_experiment_id=experiment_id,
            metric_path=request.metric_path,
            minimum_value=request.minimum_value,
        )


def client_with_fake_service(
    service: FakeModelExperimentService | None = None,
) -> TestClient:
    fake_service = service or FakeModelExperimentService()
    app = create_app(Settings(APP_ENV="test"))
    app.dependency_overrides[get_model_experiment_service] = lambda: fake_service
    return TestClient(app)


def split_payload() -> dict[str, object]:
    return {
        "dataset_id": 11,
        "feature_set_id": 12,
        "name": "holdout-v1",
        "split_type": "holdout",
        "config": {"seed": 7},
        "windows": [
            {
                "window_index": 0,
                "split_name": "train",
                "start": "2026-01-01T00:01:00Z",
                "end": "2026-01-01T00:02:00Z",
                "decision_time": "2026-01-01T01:00:00Z",
            },
            {
                "window_index": 0,
                "split_name": "validation",
                "start": "2026-01-01T00:02:00Z",
                "end": "2026-01-01T00:03:00Z",
                "decision_time": "2026-01-01T01:00:00Z",
            },
            {
                "window_index": 0,
                "split_name": "test",
                "start": "2026-01-01T00:03:00Z",
                "end": "2026-01-01T00:04:00Z",
                "decision_time": "2026-01-01T01:00:00Z",
            },
        ],
    }


def experiment_payload() -> dict[str, object]:
    return {
        "dataset_id": 11,
        "feature_set_id": 12,
        "split_definition_id": 42,
        "name": "baseline",
        "model_name": "logistic_regression",
        "parameters": {"alpha": 1},
        "code_version": "model_v1",
        "metrics": {"auc": "0.71"},
        "status": "succeeded",
        "started_at": "2026-01-01T02:00:00Z",
        "completed_at": "2026-01-01T02:05:00Z",
    }


def baseline_evaluation_payload() -> dict[str, object]:
    return {
        "dataset_id": 11,
        "feature_set_id": 12,
        "split_definition_id": 42,
        "name": "previous-return-holdout",
        "parameters": {"note": "api-test"},
    }


def label_payload() -> dict[str, object]:
    return {
        "dataset_id": 11,
        "feature_set_id": 12,
        "feature_row_id": 101,
        "feature_hash": "a" * 64,
        "label_name": "forward_return_1",
        "label_value": {"direction": "up", "return": "0.01"},
        "observed_at": "2026-01-01T01:01:00Z",
        "metadata": {"horizon": "1m"},
    }


def prediction_payload(
    *,
    model_experiment_id: uuid.UUID | None = None,
) -> dict[str, object]:
    experiment_id = model_experiment_id or uuid.UUID("11111111-1111-1111-1111-111111111111")
    return {
        "model_experiment_id": str(experiment_id),
        "feature_set_id": 12,
        "feature_row_id": 101,
        "feature_hash": "a" * 64,
        "prediction_value": {"direction": "up"},
        "confidence": "0.75",
        "decision_time": "2026-01-01T01:00:00Z",
        "lineage": {"source": "api-test"},
    }


def test_create_get_and_list_split_definitions() -> None:
    service = FakeModelExperimentService()

    with client_with_fake_service(service) as client:
        created = client.post("/modeling/splits", json=split_payload())
        fetched = client.get("/modeling/splits/42")
        listed = client.get("/modeling/splits?dataset_id=11&feature_set_id=12&limit=1")

    assert created.status_code == 200
    assert created.json()["dataset_id"] == 11
    assert created.json()["windows"][0]["split_name"] == "train"
    assert fetched.status_code == 200
    assert listed.status_code == 200
    assert len(listed.json()["split_definitions"]) == 1
    assert service.split_requests


def test_split_routes_map_errors() -> None:
    missing_payload = split_payload()
    missing_payload["dataset_id"] = 404
    invalid_payload = split_payload()
    invalid_payload["split_type"] = "walk_forward"

    with client_with_fake_service() as client:
        missing = client.post("/modeling/splits", json=missing_payload)
        invalid = client.post("/modeling/splits", json=invalid_payload)
        not_found = client.get("/modeling/splits/43")

    assert missing.status_code == 404
    assert missing.json() == {"detail": "dataset not found"}
    assert invalid.status_code == 422
    assert not_found.status_code == 404


def test_create_get_and_list_model_experiments() -> None:
    service = FakeModelExperimentService()

    with client_with_fake_service(service) as client:
        created = client.post("/modeling/experiments", json=experiment_payload())
        experiment_id = created.json()["id"]
        fetched = client.get(f"/modeling/experiments/{experiment_id}")
        listed = client.get("/modeling/experiments?split_definition_id=42&limit=1")

    assert created.status_code == 200
    assert created.json()["status"] == "succeeded"
    assert fetched.status_code == 200
    assert listed.status_code == 200
    assert len(listed.json()["model_experiments"]) == 1
    assert service.experiment_requests


def test_create_baseline_evaluation() -> None:
    service = FakeModelExperimentService()

    with client_with_fake_service(service) as client:
        created = client.post("/modeling/evaluations/baseline", json=baseline_evaluation_payload())

    assert created.status_code == 200
    assert created.json()["status"] == "succeeded"
    assert created.json()["model_name"] == "previous_return_direction"
    assert created.json()["metrics"]["overall"]["observations"] == 3
    assert service.baseline_requests
    assert service.baseline_requests[0].code_version == "baseline_evaluator_v1"


def test_baseline_evaluation_route_maps_errors() -> None:
    missing_payload = baseline_evaluation_payload()
    missing_payload["dataset_id"] = 404
    bad_lineage_payload = baseline_evaluation_payload()
    bad_lineage_payload["dataset_id"] = 422
    insufficient_payload = baseline_evaluation_payload()
    insufficient_payload["split_definition_id"] = 422

    with client_with_fake_service() as client:
        missing = client.post("/modeling/evaluations/baseline", json=missing_payload)
        bad_lineage = client.post("/modeling/evaluations/baseline", json=bad_lineage_payload)
        insufficient = client.post("/modeling/evaluations/baseline", json=insufficient_payload)

    assert missing.status_code == 404
    assert missing.json() == {"detail": "dataset not found"}
    assert bad_lineage.status_code == 422
    assert bad_lineage.json() == {"detail": "feature set dataset_id mismatch"}
    assert insufficient.status_code == 422
    assert insufficient.json() == {"detail": "test window 0 has no baseline observations"}


def test_model_experiment_routes_map_errors_and_validate_bounds() -> None:
    missing_payload = experiment_payload()
    missing_payload["split_definition_id"] = 404

    with client_with_fake_service() as client:
        missing = client.post("/modeling/experiments", json=missing_payload)
        bad_limit = client.get("/modeling/experiments?limit=0")
        not_found = client.get("/modeling/experiments/22222222-2222-2222-2222-222222222222")

    assert missing.status_code == 404
    assert bad_limit.status_code == 422
    assert not_found.status_code == 404


def test_create_get_and_list_labels() -> None:
    service = FakeModelExperimentService()

    with client_with_fake_service(service) as client:
        created = client.post("/modeling/labels", json=label_payload())
        fetched = client.get("/modeling/labels/17")
        listed = client.get(
            "/modeling/labels?dataset_id=11&feature_set_id=12"
            "&feature_row_id=101&label_name=forward_return_1&limit=1"
        )

    assert created.status_code == 201
    assert created.json()["label_value"] == {"direction": "up", "return": "0.01"}
    assert created.json()["feature_hash"] == "a" * 64
    assert fetched.status_code == 200
    assert listed.status_code == 200
    assert len(listed.json()["labels"]) == 1
    assert service.label_requests
    assert service.label_requests[0].observed_at == datetime(2026, 1, 1, 1, 1, tzinfo=UTC)


def test_label_routes_map_errors_and_validate_bounds() -> None:
    missing_payload = label_payload()
    missing_payload["dataset_id"] = 404
    bad_lineage_payload = label_payload()
    bad_lineage_payload["dataset_id"] = 422
    duplicate_payload = label_payload()
    duplicate_payload["label_name"] = "duplicate"
    bad_hash_payload = label_payload()
    bad_hash_payload["feature_hash"] = "x" * 64

    with client_with_fake_service() as client:
        missing = client.post("/modeling/labels", json=missing_payload)
        bad_lineage = client.post("/modeling/labels", json=bad_lineage_payload)
        duplicate = client.post("/modeling/labels", json=duplicate_payload)
        bad_hash = client.post("/modeling/labels", json=bad_hash_payload)
        bad_limit = client.get("/modeling/labels?limit=0")
        not_found = client.get("/modeling/labels/18")

    assert missing.status_code == 404
    assert missing.json() == {"detail": "dataset not found"}
    assert bad_lineage.status_code == 422
    assert bad_lineage.json() == {"detail": "feature set dataset_id mismatch"}
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "label already exists"}
    assert bad_hash.status_code == 422
    assert bad_limit.status_code == 422
    assert not_found.status_code == 404


def test_create_get_and_list_model_predictions() -> None:
    service = FakeModelExperimentService()

    with client_with_fake_service(service) as client:
        created = client.post("/modeling/predictions", json=prediction_payload())
        fetched = client.get("/modeling/predictions/19")
        listed = client.get(
            f"/modeling/predictions?model_experiment_id={service.experiment_id}"
            "&feature_set_id=12&feature_row_id=101&limit=1"
        )

    assert created.status_code == 201
    assert created.json()["prediction_value"] == {"direction": "up"}
    assert created.json()["confidence"] == "0.75"
    assert fetched.status_code == 200
    assert listed.status_code == 200
    assert len(listed.json()["model_predictions"]) == 1
    assert service.prediction_requests
    assert service.prediction_requests[0].model_experiment_id == service.experiment_id


def test_prediction_routes_map_errors_and_validate_bounds() -> None:
    missing_payload = prediction_payload(
        model_experiment_id=uuid.UUID("22222222-2222-2222-2222-222222222222")
    )
    bad_lineage_payload = prediction_payload()
    bad_lineage_payload["feature_set_id"] = 422
    duplicate_payload = prediction_payload()
    duplicate_payload["feature_set_id"] = 409
    bad_confidence_payload = prediction_payload()
    bad_confidence_payload["confidence"] = "1.1"

    with client_with_fake_service() as client:
        missing = client.post("/modeling/predictions", json=missing_payload)
        bad_lineage = client.post("/modeling/predictions", json=bad_lineage_payload)
        duplicate = client.post("/modeling/predictions", json=duplicate_payload)
        bad_confidence = client.post("/modeling/predictions", json=bad_confidence_payload)
        bad_limit = client.get("/modeling/predictions?limit=0")
        not_found = client.get("/modeling/predictions/20")

    assert missing.status_code == 404
    assert missing.json() == {"detail": "model experiment not found"}
    assert bad_lineage.status_code == 422
    assert bad_lineage.json() == {"detail": "model experiment feature_set_id mismatch"}
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "model prediction already exists"}
    assert bad_confidence.status_code == 422
    assert bad_limit.status_code == 422
    assert not_found.status_code == 404


def test_promotion_gate_route_and_openapi_docs() -> None:
    service = FakeModelExperimentService()

    with client_with_fake_service(service) as client:
        decision = client.post(
            f"/modeling/experiments/{service.experiment_id}/promotion-gate",
            json={"metric_path": "overall.accuracy", "minimum_value": "0.7"},
        )
        missing = client.post(
            "/modeling/experiments/22222222-2222-2222-2222-222222222222/promotion-gate",
            json={"metric_path": "overall.accuracy", "minimum_value": "0.7"},
        )
        openapi = client.get("/openapi.json")

    assert decision.status_code == 200
    assert decision.json()["approved"] is True
    assert decision.json()["reason"] == "metric threshold passed"
    assert missing.status_code == 404
    paths = openapi.json()["paths"]
    assert "404" in paths["/modeling/labels"]["post"]["responses"]
    assert "409" in paths["/modeling/labels"]["post"]["responses"]
    assert "422" in paths["/modeling/predictions"]["post"]["responses"]
