from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from trading.apps.api import create_app
from trading.apps.api.dependencies import get_ingestion_service
from trading.core.settings import Settings
from trading.services.ingestion import IngestionNotFoundError


class FakeIngestionService:
    def __init__(self) -> None:
        self.run_id = uuid.UUID("00000000-0000-4000-8000-000000000001")
        self.created = datetime(2026, 1, 1, tzinfo=UTC)

    def _run(self, **overrides: object) -> SimpleNamespace:
        defaults = {
            "id": self.run_id,
            "exchange": "binance",
            "symbol": "BTC/USDT",
            "timeframe": "1m",
            "status": "pending",
            "requested_since": None,
            "requested_until": None,
            "requested_limit": 500,
            "started_at": None,
            "completed_at": None,
            "error_message": None,
            "rows_raw": 0,
            "rows_normalized": 0,
            "created_at": self.created,
            "updated_at": self.created,
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def create_ohlcv_run(self, request) -> SimpleNamespace:  # noqa: ANN001
        return self._run(
            exchange=request.exchange,
            symbol=request.symbol,
            timeframe=request.timeframe,
            requested_since=request.since,
            requested_until=request.until,
            requested_limit=request.limit,
        )

    def get_run(self, run_id: uuid.UUID) -> SimpleNamespace:
        if run_id != self.run_id:
            raise IngestionNotFoundError(str(run_id))
        return self._run()

    def list_runs(self, *, limit: int = 50) -> list[SimpleNamespace]:
        return [self._run()][:limit]


def client_with_fake_service() -> TestClient:
    app = create_app(Settings(APP_ENV="test"))
    app.dependency_overrides[get_ingestion_service] = lambda: FakeIngestionService()
    return TestClient(app)


def test_create_ohlcv_ingestion_run_returns_metadata_without_fetching() -> None:
    with client_with_fake_service() as client:
        response = client.post(
            "/ingestion/ohlcv",
            json={"symbol": "btc_usdt", "timeframe": "1m", "limit": 10},
        )

    assert response.status_code == 202
    body = response.json()
    assert body["exchange"] == "binance"
    assert body["symbol"] == "BTC/USDT"
    assert body["timeframe"] == "1m"
    assert body["status"] == "pending"


def test_ingestion_request_rejects_unsupported_symbol_timeframe_and_order_fields() -> None:
    with client_with_fake_service() as client:
        unsupported_symbol = client.post(
            "/ingestion/ohlcv",
            json={"symbol": "DOGE/USDT", "timeframe": "1m"},
        )
        unsupported_timeframe = client.post(
            "/ingestion/ohlcv",
            json={"symbol": "BTC/USDT", "timeframe": "30m"},
        )
        order_like_field = client.post(
            "/ingestion/ohlcv",
            json={"symbol": "BTC/USDT", "timeframe": "1m", "side": "buy"},
        )

    assert unsupported_symbol.status_code == 422
    assert unsupported_timeframe.status_code == 422
    assert order_like_field.status_code == 422


def test_get_and_list_ingestion_runs() -> None:
    with client_with_fake_service() as client:
        get_response = client.get("/ingestion/runs/00000000-0000-4000-8000-000000000001")
        missing_response = client.get("/ingestion/runs/00000000-0000-4000-8000-000000000002")
        list_response = client.get("/ingestion/runs?limit=1")

    assert get_response.status_code == 200
    assert missing_response.status_code == 404
    assert list_response.status_code == 200
    assert len(list_response.json()["runs"]) == 1
