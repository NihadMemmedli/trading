from __future__ import annotations

from fastapi.testclient import TestClient

from trading.apps.api import create_app
from trading.core.settings import Settings


def test_health_does_not_initialize_external_services(monkeypatch) -> None:
    def fail_if_called(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("External service initialization should not run")

    monkeypatch.setattr("socket.create_connection", fail_if_called)

    app = create_app(Settings())
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_version_contract() -> None:
    app = create_app(Settings(APP_NAME="test-trading", APP_ENV="test"))
    with TestClient(app) as client:
        response = client.get("/version")

    assert response.status_code == 200
    assert response.json() == {
        "app": "test-trading",
        "version": "0.1.0",
        "environment": "test",
        "git_sha": None,
    }


def test_config_summary_is_safe_and_redacted() -> None:
    settings = Settings(
        EXCHANGE_API_KEY="raw-exchange-key",
        EXCHANGE_API_SECRET="raw-exchange-secret",
        EXCHANGE_API_PASSPHRASE="raw-passphrase",
        MODEL_API_KEY="raw-model-key",
        POSTGRES_PASSWORD="raw-password",
        DATABASE_URL="postgresql://user:raw-password@localhost:5432/db",
        REDIS_URL="redis://:secret@localhost:6379/0",
        SENTRY_DSN="https://raw-dsn@example.test/1",
    )
    app = create_app(settings)

    with TestClient(app) as client:
        response = client.get("/config/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["capabilities"] == {
        "live_trading_enabled": False,
        "order_execution_enabled": False,
        "sandbox_order_execution_enabled": False,
        "leverage_enabled": False,
        "withdrawals_enabled": False,
        "custody_enabled": False,
    }
    assert body["infrastructure"]["POSTGRES_PASSWORD"] == "********"
    assert body["infrastructure"]["DATABASE_URL"] == "********"
    assert body["infrastructure"]["REDIS_URL"] == "********"
    assert body["infrastructure"]["SENTRY_DSN"] == "********"
    assert body["providers"]["EXCHANGE_API_KEY"] == "********"
    assert body["providers"]["EXCHANGE_API_SECRET"] == "********"
    assert body["providers"]["EXCHANGE_API_PASSPHRASE"] == "********"
    assert body["providers"]["MODEL_API_KEY"] == "********"
    assert "raw-" not in str(body)
