"""Split definition and model experiment APIs."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status

from trading.apps.api.dependencies import ModelExperimentServiceDependency
from trading.apps.api.schemas.model_experiments import (
    BaselineEvaluationRequest,
    LabelCreateRequest,
    LabelListResponse,
    LabelResponse,
    ModelExperimentCreateRequest,
    ModelExperimentListResponse,
    ModelExperimentResponse,
    ModelPredictionCreateRequest,
    ModelPredictionListResponse,
    ModelPredictionResponse,
    PromotionGateRequest,
    PromotionGateResponse,
    SplitDefinitionCreateRequest,
    SplitDefinitionListResponse,
    SplitDefinitionResponse,
)
from trading.services.model_experiments import (
    LabelNotFoundError,
    ModelExperimentLineageError,
    ModelExperimentNotFoundError,
    ModelingConflictError,
    ModelPredictionNotFoundError,
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


@router.post("/evaluations/baseline", response_model=ModelExperimentResponse)
def evaluate_baseline_model(
    payload: BaselineEvaluationRequest,
    service: ModelExperimentServiceDependency,
) -> ModelExperimentResponse:
    try:
        experiment = service.evaluate_baseline_model(payload.to_service_request())
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


@router.post(
    "/labels",
    response_model=LabelResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"description": "Referenced lineage record was not found"},
        409: {"description": "Label already exists"},
        422: {"description": "Invalid label payload or lineage"},
    },
)
def create_label(
    payload: LabelCreateRequest,
    service: ModelExperimentServiceDependency,
) -> LabelResponse:
    try:
        label = service.create_label(payload.to_service_request())
    except ModelingConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ModelExperimentLineageError as exc:
        _raise_lineage_http_error(exc)
    except SplitValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return LabelResponse.model_validate(label)


@router.get("/labels/{label_id}", response_model=LabelResponse)
def get_label(
    label_id: Annotated[int, Path(ge=1)],
    service: ModelExperimentServiceDependency,
) -> LabelResponse:
    try:
        label = service.get_label(label_id)
    except LabelNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="label not found",
        ) from exc
    return LabelResponse.model_validate(label)


@router.get("/labels", response_model=LabelListResponse)
def list_labels(
    service: ModelExperimentServiceDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    dataset_id: Annotated[int | None, Query(ge=1)] = None,
    feature_set_id: Annotated[int | None, Query(ge=1)] = None,
    feature_row_id: Annotated[int | None, Query(ge=1)] = None,
    label_name: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
) -> LabelListResponse:
    labels = [
        LabelResponse.model_validate(label)
        for label in service.list_labels(
            limit=limit,
            dataset_id=dataset_id,
            feature_set_id=feature_set_id,
            feature_row_id=feature_row_id,
            label_name=label_name,
        )
    ]
    return LabelListResponse(labels=labels)


@router.post(
    "/predictions",
    response_model=ModelPredictionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"description": "Referenced experiment or lineage record was not found"},
        409: {"description": "Model prediction already exists"},
        422: {"description": "Invalid prediction payload or lineage"},
    },
)
def create_model_prediction(
    payload: ModelPredictionCreateRequest,
    service: ModelExperimentServiceDependency,
) -> ModelPredictionResponse:
    try:
        prediction = service.create_model_prediction(payload.to_service_request())
    except (ModelExperimentNotFoundError, ModelPredictionNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="model experiment not found",
        ) from exc
    except ModelingConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ModelExperimentLineageError as exc:
        _raise_lineage_http_error(exc)
    except SplitValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return ModelPredictionResponse.model_validate(prediction)


@router.get("/predictions/{prediction_id}", response_model=ModelPredictionResponse)
def get_model_prediction(
    prediction_id: Annotated[int, Path(ge=1)],
    service: ModelExperimentServiceDependency,
) -> ModelPredictionResponse:
    try:
        prediction = service.get_model_prediction(prediction_id)
    except ModelPredictionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="model prediction not found",
        ) from exc
    return ModelPredictionResponse.model_validate(prediction)


@router.get("/predictions", response_model=ModelPredictionListResponse)
def list_model_predictions(
    service: ModelExperimentServiceDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    model_experiment_id: uuid.UUID | None = None,
    feature_set_id: Annotated[int | None, Query(ge=1)] = None,
    feature_row_id: Annotated[int | None, Query(ge=1)] = None,
) -> ModelPredictionListResponse:
    predictions = [
        ModelPredictionResponse.model_validate(prediction)
        for prediction in service.list_model_predictions(
            limit=limit,
            model_experiment_id=model_experiment_id,
            feature_set_id=feature_set_id,
            feature_row_id=feature_row_id,
        )
    ]
    return ModelPredictionListResponse(model_predictions=predictions)


@router.post(
    "/experiments/{experiment_id}/promotion-gate",
    response_model=PromotionGateResponse,
    responses={
        404: {"description": "Model experiment was not found"},
        422: {"description": "Invalid promotion gate payload"},
    },
)
def evaluate_promotion_gate(
    experiment_id: uuid.UUID,
    payload: PromotionGateRequest,
    service: ModelExperimentServiceDependency,
) -> PromotionGateResponse:
    try:
        decision = service.evaluate_promotion_gate(experiment_id, payload.to_service_request())
    except ModelExperimentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="model experiment not found",
        ) from exc
    except SplitValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return PromotionGateResponse.model_validate(decision)


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
