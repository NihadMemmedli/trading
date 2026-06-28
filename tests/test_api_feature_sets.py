from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from trading.apps.api import create_app
from trading.apps.api.dependencies import get_feature_set_service
from trading.core.settings import Settings
from trading.features import FeatureMaterializationError
from trading.services.feature_sets import (
    FeatureSetCreateRequest as ServiceFeatureSetCreateRequest,
)
from trading.services.feature_sets import (
    FeatureSetDatasetNotFoundError,
    FeatureSetNotFoundError,
)


class FakeFeatureSetService:
    def __init__(self) -> None:
        self.created = datetime(2026, 1, 1, tzinfo=UTC)
        self.requests: list[object] = []

    def _row(self) -> SimpleNamespace:
        return SimpleNamespace(
            id=7,
            timestamp=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
            decision_time=datetime(2026, 1, 1, 1, tzinfo=UTC),
            available_at=datetime(2026, 1, 1, 1, tzinfo=UTC),
            features={
                "close_return_1": "0.1",
                "close_sma_2": "105",
                "volume_sma_2": "10.5",
            },
            feature_hash="f" * 64,
        )

    def _feature_set(self, **overrides: object) -> SimpleNamespace:
        defaults = {
            "id": 42,
            "dataset_id": 11,
            "name": "mvp-candles",
            "dataset_hash": "d" * 64,
            "feature_set_hash": "s" * 64,
            "parameter_hash": "p" * 64,
            "code_version": "candle_features_v1",
            "parameters": {"lookback": 2},
            "feature_names": ["close_return_1", "close_sma_2", "volume_sma_2"],
            "selector": {
                "exchange": "binance",
                "symbol": "BTC/USDT",
                "timeframe": "1m",
                "start": "2026-01-01T00:00:00Z",
                "end": "2026-01-01T00:05:00Z",
                "decision_time": "2026-01-01T01:00:00Z",
            },
            "output_location": None,
            "created_at": self.created,
            "feature_row_count": 1,
            "rows": [self._row()],
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def create_feature_set(self, request: ServiceFeatureSetCreateRequest) -> SimpleNamespace:
        self.requests.append(request)
        if request.dataset_id == 404:
            raise FeatureSetDatasetNotFoundError(str(request.dataset_id))
        if request.parameters.get("lookback") == 1:
            raise FeatureMaterializationError("lookback must be at least 2")
        return self._feature_set(
            dataset_id=request.dataset_id,
            name=request.name,
            parameters=dict(request.parameters),
            code_version=request.code_version,
            output_location=request.output_location,
        )

    def get_feature_set(self, feature_set_id: int) -> SimpleNamespace:
        if feature_set_id != 42:
            raise FeatureSetNotFoundError(str(feature_set_id))
        return self._feature_set()

    def list_feature_sets(
        self,
        *,
        limit: int = 50,
        dataset_id: int | None = None,
    ) -> list[SimpleNamespace]:
        feature_sets = [self._feature_set(rows=[])]
        if dataset_id is not None:
            feature_sets = [self._feature_set(dataset_id=dataset_id, rows=[])]
        return feature_sets[:limit]


def client_with_fake_service(service: FakeFeatureSetService | None = None) -> TestClient:
    fake_service = service or FakeFeatureSetService()
    app = create_app(Settings(APP_ENV="test"))
    app.dependency_overrides[get_feature_set_service] = lambda: fake_service
    return TestClient(app)


def valid_payload() -> dict[str, object]:
    return {
        "dataset_id": 11,
        "name": "mvp-candles",
        "parameters": {"lookback": 2},
        "code_version": "candle_features_v1",
    }


def test_create_feature_set_returns_materialized_rows() -> None:
    service = FakeFeatureSetService()

    with client_with_fake_service(service) as client:
        response = client.post("/feature-sets", json=valid_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 42
    assert body["dataset_id"] == 11
    assert body["feature_names"] == ["close_return_1", "close_sma_2", "volume_sma_2"]
    assert body["feature_row_count"] == 1
    assert body["rows"][0]["features"] == {
        "close_return_1": "0.1",
        "close_sma_2": "105",
        "volume_sma_2": "10.5",
    }
    created_request = service.requests[0]
    assert isinstance(created_request, ServiceFeatureSetCreateRequest)
    assert created_request.dataset_id == 11


def test_create_feature_set_maps_service_errors() -> None:
    missing_payload = valid_payload()
    missing_payload["dataset_id"] = 404
    invalid_payload = valid_payload()
    invalid_payload["parameters"] = {"lookback": 1}

    with client_with_fake_service() as client:
        missing = client.post("/feature-sets", json=missing_payload)
        invalid = client.post("/feature-sets", json=invalid_payload)

    assert missing.status_code == 404
    assert missing.json() == {"detail": "dataset not found"}
    assert invalid.status_code == 422
    assert invalid.json() == {"detail": "lookback must be at least 2"}


def test_get_feature_set_returns_404_for_missing() -> None:
    with client_with_fake_service() as client:
        found = client.get("/feature-sets/42")
        missing = client.get("/feature-sets/43")

    assert found.status_code == 200
    assert found.json()["rows"][0]["feature_hash"] == "f" * 64
    assert missing.status_code == 404
    assert missing.json() == {"detail": "feature set not found"}


def test_list_feature_sets_returns_envelope_and_filters_by_dataset() -> None:
    with client_with_fake_service() as client:
        response = client.get("/feature-sets?dataset_id=12&limit=1")

    assert response.status_code == 200
    body = response.json()
    assert list(body) == ["feature_sets"]
    assert len(body["feature_sets"]) == 1
    assert body["feature_sets"][0]["dataset_id"] == 12
    assert body["feature_sets"][0]["rows"] == []


def test_feature_set_routes_reject_invalid_bounds() -> None:
    with client_with_fake_service() as client:
        too_low_limit = client.get("/feature-sets?limit=0")
        too_high_limit = client.get("/feature-sets?limit=101")
        bad_dataset = client.get("/feature-sets?dataset_id=0")
        bad_id = client.get("/feature-sets/0")

    assert too_low_limit.status_code == 422
    assert too_high_limit.status_code == 422
    assert bad_dataset.status_code == 422
    assert bad_id.status_code == 422
