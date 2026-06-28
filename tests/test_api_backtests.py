from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from fastapi.testclient import TestClient

from trading.apps.api import create_app
from trading.apps.api.dependencies import get_backtest_service
from trading.core.settings import Settings
from trading.services.backtests import (
    BacktestDatasetNotExecutableError,
    BacktestDatasetNotFoundError,
    BacktestRunNotFoundError,
)


class FakeBacktestService:
    def __init__(self) -> None:
        self.run_id = uuid.UUID("00000000-0000-4000-8000-000000000011")
        self.historical_run_id = uuid.UUID("00000000-0000-4000-8000-000000000013")
        self.created = datetime(2026, 1, 1, tzinfo=UTC)
        self.requests: list[object] = []

    def _run(self, **overrides: object) -> SimpleNamespace:
        defaults = {
            "id": self.run_id,
            "status": "succeeded",
            "exchange": "binance",
            "symbol": "BTC/USDT",
            "timeframe": "1m",
            "start": datetime(2026, 1, 1, tzinfo=UTC),
            "end": datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
            "decision_time": datetime(2026, 1, 1, 1, tzinfo=UTC),
            "generated_at": datetime(2026, 1, 2, tzinfo=UTC),
            "initial_capital": Decimal("1000"),
            "fee_bps": Decimal("1"),
            "slippage_bps": Decimal("2"),
            "strategy_name": "moving_average_crossover",
            "strategy_parameters": {"short_window": 1, "long_window": 2},
            "dataset_id": 42,
            "dataset_hash": "d" * 64,
            "config_hash": "c" * 64,
            "result_hash": "r" * 64,
            "report_hash": "a" * 64,
            "metrics_json": {"trades_count": 1, "final_equity": "1001"},
            "report_json": {
                "report_hash": "a" * 64,
                "strategy_version": "1",
                "sizing": {
                    "max_exposure": "1",
                    "cash_reserve": "0",
                    "min_trade_notional": "0",
                },
                "metrics": {"trades_count": 1, "final_equity": "1001"},
            },
            "artifact_path": "/reports/report.json",
            "started_at": self.created,
            "completed_at": self.created,
            "error_message": None,
            "created_at": self.created,
            "updated_at": self.created,
            "trades": [
                SimpleNamespace(
                    id=1,
                    symbol="BTC/USDT",
                    timestamp=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
                    side="buy",
                    quantity=Decimal("1"),
                    fill_price=Decimal("100"),
                    fee=Decimal("0.1"),
                    slippage=Decimal("0.2"),
                )
            ],
            "equity_points": [
                SimpleNamespace(
                    id=1,
                    timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                    equity=Decimal("1000"),
                )
            ],
            "events": [
                SimpleNamespace(
                    id=1,
                    timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                    level="info",
                    event_type="backtest.started",
                    message="backtest run started",
                    metadata_json={"strategy_version": "1"},
                )
            ],
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def run_backtest(self, request) -> SimpleNamespace:  # noqa: ANN001
        self.requests.append(request)
        if request.dataset_id == 404:
            raise BacktestDatasetNotFoundError(str(request.dataset_id))
        if request.dataset_id == 422:
            raise BacktestDatasetNotExecutableError("only backtest-created datasets are executable")
        return self._run(
            dataset_id=getattr(request, "dataset_id", None) or 42,
            exchange=getattr(request, "exchange", "binance") or "binance",
            symbol=getattr(request, "symbol", "BTC/USDT") or "BTC/USDT",
            timeframe=getattr(request, "timeframe", "1m") or "1m",
            start=getattr(request, "start", datetime(2026, 1, 1, tzinfo=UTC))
            or datetime(2026, 1, 1, tzinfo=UTC),
            end=getattr(request, "end", datetime(2026, 1, 1, 0, 5, tzinfo=UTC))
            or datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
            decision_time=getattr(request, "decision_time", datetime(2026, 1, 1, 1, tzinfo=UTC))
            or datetime(2026, 1, 1, 1, tzinfo=UTC),
            generated_at=request.generated_at,
            initial_capital=request.initial_capital,
            fee_bps=request.fee_bps,
            slippage_bps=request.slippage_bps,
            strategy_name=request.strategy_name,
            strategy_parameters=request.strategy_parameters,
        )

    def get_run(self, run_id: uuid.UUID) -> SimpleNamespace:
        if run_id == self.historical_run_id:
            return self._run(
                id=self.historical_run_id,
                dataset_id=None,
                dataset_hash=None,
                trades=[],
                equity_points=[],
            )
        if run_id != self.run_id:
            raise BacktestRunNotFoundError(str(run_id))
        return self._run()

    def list_runs(self, *, limit: int = 50) -> list[SimpleNamespace]:
        return [self._run()][:limit]


def client_with_fake_service(service: FakeBacktestService | None = None) -> TestClient:
    fake_service = service or FakeBacktestService()
    app = create_app(Settings(APP_ENV="test"))
    app.dependency_overrides[get_backtest_service] = lambda: fake_service
    return TestClient(app)


def valid_payload() -> dict[str, object]:
    return {
        "exchange": "binance",
        "symbol": "btc_usdt",
        "timeframe": "1m",
        "start": "2026-01-01T00:00:00Z",
        "end": "2026-01-01T00:05:00Z",
        "decision_time": "2026-01-01T01:00:00Z",
        "generated_at": "2026-01-02T00:00:00Z",
        "initial_capital": "1000",
        "fee_bps": "1",
        "slippage_bps": "2",
        "strategy_name": "moving_average_crossover",
        "strategy_parameters": {"short_window": 1, "long_window": 2},
    }


def dataset_id_payload() -> dict[str, object]:
    return {
        "dataset_id": 42,
        "generated_at": "2026-01-02T00:00:00Z",
        "initial_capital": "1000",
        "fee_bps": "1",
        "slippage_bps": "2",
        "strategy_name": "moving_average_crossover",
        "strategy_parameters": {"short_window": 1, "long_window": 2},
    }


def dataset_id_payload_with(dataset_id: int) -> dict[str, object]:
    payload = dataset_id_payload()
    payload["dataset_id"] = dataset_id
    return payload


def test_create_backtest_run_returns_persisted_response() -> None:
    with client_with_fake_service() as client:
        response = client.post("/backtests/runs", json=valid_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "00000000-0000-4000-8000-000000000011"
    assert body["status"] == "succeeded"
    assert body["exchange"] == "binance"
    assert body["symbol"] == "BTC/USDT"
    assert body["strategy_parameters"] == {"short_window": 1, "long_window": 2}
    assert body["strategy_version"] == "1"
    assert body["sizing"] == {
        "max_exposure": "1",
        "cash_reserve": "0",
        "min_trade_notional": "0",
    }
    assert body["dataset_id"] == 42
    assert body["dataset_hash"] == "d" * 64
    assert body["metrics"] == {"trades_count": 1, "final_equity": "1001"}
    assert body["report"] == {
        "report_hash": "a" * 64,
        "strategy_version": "1",
        "sizing": {
            "max_exposure": "1",
            "cash_reserve": "0",
            "min_trade_notional": "0",
        },
        "metrics": {"trades_count": 1, "final_equity": "1001"},
    }
    assert body["trades"] == [
        {
            "id": 1,
            "symbol": "BTC/USDT",
            "timestamp": "2026-01-01T00:01:00Z",
            "side": "buy",
            "quantity": "1",
            "fill_price": "100",
            "fee": "0.1",
            "slippage": "0.2",
        }
    ]
    assert body["equity_curve"] == [
        {
            "id": 1,
            "timestamp": "2026-01-01T00:00:00Z",
            "equity": "1000",
        }
    ]
    assert body["events"] == [
        {
            "id": 1,
            "timestamp": "2026-01-01T00:00:00Z",
            "level": "info",
            "event_type": "backtest.started",
            "message": "backtest run started",
            "metadata": {"strategy_version": "1"},
        }
    ]
    assert body["artifact_path"] == "/reports/report.json"


def test_create_backtest_run_accepts_sizing_config() -> None:
    service = FakeBacktestService()
    payload = valid_payload()
    payload["sizing"] = {
        "max_exposure": "0.5",
        "cash_reserve": "0.1",
        "min_trade_notional": "25",
    }

    with client_with_fake_service(service) as client:
        response = client.post("/backtests/runs", json=payload)

    assert response.status_code == 200
    request = service.requests[0]
    assert request.sizing.max_exposure == Decimal("0.5")
    assert request.sizing.cash_reserve == Decimal("0.1")
    assert request.sizing.min_trade_notional == Decimal("25")


def test_create_backtest_run_accepts_dataset_id_mode() -> None:
    service = FakeBacktestService()

    with client_with_fake_service(service) as client:
        response = client.post("/backtests/runs", json=dataset_id_payload())

    assert response.status_code == 200
    assert response.json()["dataset_id"] == 42
    assert len(service.requests) == 1
    request = service.requests[0]
    assert request.dataset_id == 42
    assert request.exchange is None
    assert getattr(request, "symbol", None) is None
    assert getattr(request, "start", None) is None


def test_create_backtest_run_maps_dataset_id_errors() -> None:
    with client_with_fake_service() as client:
        missing_response = client.post("/backtests/runs", json=dataset_id_payload_with(404))
        unsupported_response = client.post("/backtests/runs", json=dataset_id_payload_with(422))

    assert missing_response.status_code == 404
    assert missing_response.json()["detail"] == "dataset not found"
    assert unsupported_response.status_code == 422
    assert "backtest-created" in unsupported_response.json()["detail"]


def test_get_backtest_run_returns_expanded_details_and_list_stays_summary_only() -> None:
    with client_with_fake_service() as client:
        get_response = client.get("/backtests/runs/00000000-0000-4000-8000-000000000011")
        missing_response = client.get("/backtests/runs/00000000-0000-4000-8000-000000000012")
        list_response = client.get("/backtests/runs?limit=1")

    assert get_response.status_code == 200
    get_body = get_response.json()
    assert get_body["dataset_id"] == 42
    assert get_body["dataset_hash"] == "d" * 64
    assert get_body["report"]["report_hash"] == "a" * 64
    assert get_body["trades"][0]["timestamp"] == "2026-01-01T00:01:00Z"
    assert get_body["equity_curve"][0]["timestamp"] == "2026-01-01T00:00:00Z"
    assert missing_response.status_code == 404
    assert list_response.status_code == 200
    list_body = list_response.json()
    assert len(list_body["runs"]) == 1
    assert list_body["runs"][0]["dataset_id"] == 42
    assert list_body["runs"][0]["dataset_hash"] == "d" * 64
    assert "report" not in list_body["runs"][0]
    assert "trades" not in list_body["runs"][0]
    assert "equity_curve" not in list_body["runs"][0]


def test_get_backtest_run_serializes_historical_run_without_dataset_id() -> None:
    with client_with_fake_service() as client:
        response = client.get("/backtests/runs/00000000-0000-4000-8000-000000000013")

    assert response.status_code == 200
    body = response.json()
    assert body["dataset_id"] is None
    assert body["dataset_hash"] is None
    assert body["trades"] == []
    assert body["equity_curve"] == []


def test_backtest_request_rejects_order_like_fields_and_non_utc_generated_at() -> None:
    order_payload = valid_payload()
    order_payload["side"] = "buy"
    non_utc_payload = valid_payload()
    non_utc_payload["generated_at"] = "2026-01-02T04:00:00+04:00"

    with client_with_fake_service() as client:
        order_like_response = client.post("/backtests/runs", json=order_payload)
        non_utc_response = client.post("/backtests/runs", json=non_utc_payload)

    assert order_like_response.status_code == 422
    assert non_utc_response.status_code == 422


def test_backtest_request_rejects_dataset_id_with_selector_fields() -> None:
    payload = valid_payload()
    payload["dataset_id"] = 42

    with client_with_fake_service() as client:
        response = client.post("/backtests/runs", json=payload)

    assert response.status_code == 422


def test_backtest_request_rejects_missing_dataset_id_and_incomplete_selector() -> None:
    payload = valid_payload()
    del payload["decision_time"]

    with client_with_fake_service() as client:
        response = client.post("/backtests/runs", json=payload)

    assert response.status_code == 422
