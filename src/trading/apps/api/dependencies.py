"""FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from trading.core.settings import Settings
from trading.db.session import create_db_engine, create_session_factory
from trading.services.backtests import BacktestService
from trading.services.datasets import DatasetService
from trading.services.ingestion import IngestionService


def get_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if not isinstance(settings, Settings):
        raise RuntimeError("Application settings are not initialized")
    return settings


SettingsDependency = Annotated[Settings, Depends(get_settings)]


def get_ingestion_service(settings: SettingsDependency) -> IngestionService:
    engine = create_db_engine(settings)
    return IngestionService(create_session_factory(engine))


IngestionServiceDependency = Annotated[IngestionService, Depends(get_ingestion_service)]


def get_dataset_service(settings: SettingsDependency) -> DatasetService:
    engine = create_db_engine(settings)
    return DatasetService(create_session_factory(engine))


DatasetServiceDependency = Annotated[DatasetService, Depends(get_dataset_service)]


def get_backtest_service(settings: SettingsDependency) -> BacktestService:
    engine = create_db_engine(settings)
    return BacktestService(create_session_factory(engine), reports_dir=settings.REPORTS_DIR)


BacktestServiceDependency = Annotated[BacktestService, Depends(get_backtest_service)]
