from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from trading.apps.api import create_app
from trading.apps.api.dependencies import get_model_experiment_service
from trading.core.settings import Settings
from trading.services.model_experiments import (
    ModelExperimentLineageError,
    ModelExperimentNotFoundError,
    SplitDefinitionNotFoundError,
    SplitValidationError,
)


class FakeModelExperimentService:
    def __init__(self) -> None:
        self.created_at = datetime(2026, 1, 1, tzinfo=UTC)
        self.experiment_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
        self.split_requests: list[object] = []
        self.experiment_requests: list[object] = []

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
