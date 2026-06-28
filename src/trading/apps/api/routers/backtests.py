"""Persisted synchronous backtest run API."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from trading.apps.api.dependencies import BacktestServiceDependency
from trading.apps.api.schemas.backtests import (
    BacktestRunCreateRequest,
    BacktestRunListResponse,
    BacktestRunResponse,
)
from trading.services.backtests import BacktestRunNotFoundError

router = APIRouter(prefix="/backtests", tags=["backtests"])


@router.post("/runs", response_model=BacktestRunResponse)
def create_backtest_run(
    request: BacktestRunCreateRequest,
    service: BacktestServiceDependency,
) -> BacktestRunResponse:
    run = service.run_backtest(request.to_service_request())
    return BacktestRunResponse.from_run(run)


@router.get("/runs/{run_id}", response_model=BacktestRunResponse)
def get_backtest_run(
    run_id: uuid.UUID,
    service: BacktestServiceDependency,
) -> BacktestRunResponse:
    try:
        run = service.get_run(run_id)
    except BacktestRunNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="backtest run not found",
        ) from exc
    return BacktestRunResponse.from_run(run)


@router.get("/runs", response_model=BacktestRunListResponse)
def list_backtest_runs(
    service: BacktestServiceDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> BacktestRunListResponse:
    runs = [BacktestRunResponse.from_run(run) for run in service.list_runs(limit=limit)]
    return BacktestRunListResponse(runs=runs)
