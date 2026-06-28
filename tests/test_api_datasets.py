from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from trading.apps.api import create_app
from trading.apps.api.dependencies import get_dataset_service
from trading.core.settings import Settings
from trading.services.datasets import DatasetNotFoundError


class FakeDatasetService:
    def __init__(self) -> None:
        self.created = datetime(2026, 1, 1, tzinfo=UTC)

    def _dataset(self, **overrides: object) -> SimpleNamespace:
        defaults = {
            "id": 42,
            "name": "backtest:binance:BTC/USDT:1m:2026-01-01T00:00:00Z",
            "dataset_hash": "d" * 64,
            "decision_time": datetime(2026, 1, 1, 1, tzinfo=UTC),
            "artifact_id": None,
            "created_at": self.created,
            "backtest_run_count": 2,
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def get_dataset(self, dataset_id: int) -> SimpleNamespace:
        if dataset_id != 42:
            raise DatasetNotFoundError(str(dataset_id))
        return self._dataset()

    def list_datasets(self, *, limit: int = 50) -> list[SimpleNamespace]:
        datasets = [
            self._dataset(),
            self._dataset(
                id=43,
                name="binance:ETH/USDT:1m",
                artifact_id=7,
                backtest_run_count=0,
            ),
        ]
        return datasets[:limit]


def client_with_fake_service() -> TestClient:
    app = create_app(Settings(APP_ENV="test"))
    app.dependency_overrides[get_dataset_service] = lambda: FakeDatasetService()
    return TestClient(app)


def test_get_dataset_returns_registered_metadata() -> None:
    with client_with_fake_service() as client:
        response = client.get("/datasets/42")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "id": 42,
        "name": "backtest:binance:BTC/USDT:1m:2026-01-01T00:00:00Z",
        "dataset_hash": "d" * 64,
        "decision_time": "2026-01-01T01:00:00Z",
        "artifact_id": None,
        "created_at": "2026-01-01T00:00:00Z",
        "backtest_run_count": 2,
    }


def test_get_dataset_returns_404_for_missing_dataset() -> None:
    with client_with_fake_service() as client:
        response = client.get("/datasets/43")

    assert response.status_code == 404
    assert response.json() == {"detail": "dataset not found"}


def test_list_datasets_returns_envelope_and_honors_limit() -> None:
    with client_with_fake_service() as client:
        response = client.get("/datasets?limit=1")

    assert response.status_code == 200
    body = response.json()
    assert list(body) == ["datasets"]
    assert len(body["datasets"]) == 1
    assert body["datasets"][0]["id"] == 42


def test_list_datasets_rejects_invalid_limits() -> None:
    with client_with_fake_service() as client:
        too_low = client.get("/datasets?limit=0")
        too_high = client.get("/datasets?limit=101")

    assert too_low.status_code == 422
    assert too_high.status_code == 422
