"""Public market-data ingestion API."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from trading.apps.api.dependencies import IngestionServiceDependency
from trading.apps.api.schemas.ingestion import (
    IngestionRunListResponse,
    IngestionRunResponse,
    OhlcvIngestionRequest,
)
from trading.services.ingestion import IngestionNotFoundError

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


@router.post(
    "/ohlcv",
    response_model=IngestionRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_ohlcv_ingestion_run(
    request: OhlcvIngestionRequest,
    service: IngestionServiceDependency,
) -> IngestionRunResponse:
    run = service.create_ohlcv_run(request)
    return IngestionRunResponse.model_validate(run)


@router.get("/runs/{run_id}", response_model=IngestionRunResponse)
def get_ingestion_run(
    run_id: uuid.UUID,
    service: IngestionServiceDependency,
) -> IngestionRunResponse:
    try:
        run = service.get_run(run_id)
    except IngestionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="ingestion run not found"
        ) from exc
    return IngestionRunResponse.model_validate(run)


@router.get("/runs", response_model=IngestionRunListResponse)
def list_ingestion_runs(
    service: IngestionServiceDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> IngestionRunListResponse:
    runs = [IngestionRunResponse.model_validate(run) for run in service.list_runs(limit=limit)]
    return IngestionRunListResponse(runs=runs)
