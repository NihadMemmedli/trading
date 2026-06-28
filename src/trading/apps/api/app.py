"""FastAPI app factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from trading.apps.api.routers import (
    agents,
    backtests,
    config,
    datasets,
    feature_sets,
    health,
    ingestion,
    model_experiments,
    risk,
    trade_proposals,
    version,
)
from trading.core.logging import configure_logging
from trading.core.settings import Settings, load_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_app_settings(app)
    settings.enforce_safety_policy()
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or load_settings()
    configure_logging(app_settings.LOG_LEVEL)

    app = FastAPI(
        title=app_settings.APP_NAME,
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.include_router(health.router)
    app.include_router(version.router)
    app.include_router(config.router)
    app.include_router(ingestion.router)
    app.include_router(datasets.router)
    app.include_router(feature_sets.router)
    app.include_router(model_experiments.router)
    app.include_router(backtests.router)
    app.include_router(agents.router)
    app.include_router(trade_proposals.router)
    app.include_router(risk.router)
    return app


def get_app_settings(app: FastAPI) -> Settings:
    settings = getattr(app.state, "settings", None)
    if not isinstance(settings, Settings):
        raise RuntimeError("Application settings are not initialized")
    return settings


app = create_app()
