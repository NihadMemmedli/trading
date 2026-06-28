"""Registered dataset API."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status

from trading.apps.api.dependencies import DatasetServiceDependency
from trading.apps.api.schemas.datasets import DatasetListResponse, DatasetResponse
from trading.services.datasets import DatasetNotFoundError

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.get("", response_model=DatasetListResponse)
def list_datasets(
    service: DatasetServiceDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> DatasetListResponse:
    datasets = [
        DatasetResponse.model_validate(dataset) for dataset in service.list_datasets(limit=limit)
    ]
    return DatasetListResponse(datasets=datasets)


@router.get("/{dataset_id}", response_model=DatasetResponse)
def get_dataset(
    dataset_id: Annotated[int, Path(ge=1)],
    service: DatasetServiceDependency,
) -> DatasetResponse:
    try:
        dataset = service.get_dataset(dataset_id)
    except DatasetNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="dataset not found",
        ) from exc
    return DatasetResponse.model_validate(dataset)
