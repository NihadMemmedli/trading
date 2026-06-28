"""Split definition and model experiment APIs."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status

from trading.apps.api.dependencies import ModelExperimentServiceDependency
from trading.apps.api.schemas.model_experiments import (
    ModelExperimentCreateRequest,
    ModelExperimentListResponse,
    ModelExperimentResponse,
    SplitDefinitionCreateRequest,
    SplitDefinitionListResponse,
    SplitDefinitionResponse,
)
from trading.services.model_experiments import (
    ModelExperimentLineageError,
    ModelExperimentNotFoundError,
    SplitDefinitionNotFoundError,
    SplitValidationError,
)

router = APIRouter(prefix="/modeling", tags=["modeling"])


@router.post("/splits", response_model=SplitDefinitionResponse)
def create_split_definition(
    payload: SplitDefinitionCreateRequest,
    service: ModelExperimentServiceDependency,
) -> SplitDefinitionResponse:
    try:
        split_definition = service.create_split_definition(payload.to_service_request())
    except ModelExperimentLineageError as exc:
        _raise_lineage_http_error(exc)
    except SplitValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return SplitDefinitionResponse.model_validate(split_definition)


@router.get("/splits/{split_definition_id}", response_model=SplitDefinitionResponse)
def get_split_definition(
    split_definition_id: Annotated[int, Path(ge=1)],
    service: ModelExperimentServiceDependency,
) -> SplitDefinitionResponse:
    try:
        split_definition = service.get_split_definition(split_definition_id)
    except SplitDefinitionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="split definition not found",
        ) from exc
    return SplitDefinitionResponse.model_validate(split_definition)


@router.get("/splits", response_model=SplitDefinitionListResponse)
def list_split_definitions(
    service: ModelExperimentServiceDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    dataset_id: Annotated[int | None, Query(ge=1)] = None,
    feature_set_id: Annotated[int | None, Query(ge=1)] = None,
) -> SplitDefinitionListResponse:
    split_definitions = [
        SplitDefinitionResponse.model_validate(split_definition)
        for split_definition in service.list_split_definitions(
            limit=limit,
            dataset_id=dataset_id,
            feature_set_id=feature_set_id,
        )
    ]
    return SplitDefinitionListResponse(split_definitions=split_definitions)


@router.post("/experiments", response_model=ModelExperimentResponse)
def create_model_experiment(
    payload: ModelExperimentCreateRequest,
    service: ModelExperimentServiceDependency,
) -> ModelExperimentResponse:
    try:
        experiment = service.create_model_experiment(payload.to_service_request())
    except SplitDefinitionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="split definition not found",
        ) from exc
    except ModelExperimentLineageError as exc:
        _raise_lineage_http_error(exc)
    except SplitValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return ModelExperimentResponse.model_validate(experiment)


@router.get("/experiments/{experiment_id}", response_model=ModelExperimentResponse)
def get_model_experiment(
    experiment_id: uuid.UUID,
    service: ModelExperimentServiceDependency,
) -> ModelExperimentResponse:
    try:
        experiment = service.get_model_experiment(experiment_id)
    except ModelExperimentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="model experiment not found",
        ) from exc
    return ModelExperimentResponse.model_validate(experiment)


@router.get("/experiments", response_model=ModelExperimentListResponse)
def list_model_experiments(
    service: ModelExperimentServiceDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    dataset_id: Annotated[int | None, Query(ge=1)] = None,
    feature_set_id: Annotated[int | None, Query(ge=1)] = None,
    split_definition_id: Annotated[int | None, Query(ge=1)] = None,
) -> ModelExperimentListResponse:
    experiments = [
        ModelExperimentResponse.model_validate(experiment)
        for experiment in service.list_model_experiments(
            limit=limit,
            dataset_id=dataset_id,
            feature_set_id=feature_set_id,
            split_definition_id=split_definition_id,
        )
    ]
    return ModelExperimentListResponse(model_experiments=experiments)


def _raise_lineage_http_error(exc: Exception) -> None:
    message = str(exc)
    if "not found" in message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=message,
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=message,
    ) from exc
