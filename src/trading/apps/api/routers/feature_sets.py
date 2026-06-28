"""Feature-set registry API."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, status

from trading.apps.api.dependencies import FeatureSetServiceDependency
from trading.apps.api.schemas.feature_sets import (
    FeatureSetCreateRequest,
    FeatureSetListResponse,
    FeatureSetResponse,
)
from trading.data.market import MarketDataError
from trading.features import FeatureMaterializationError
from trading.services.feature_sets import (
    FeatureSetCreateRequest as ServiceFeatureSetCreateRequest,
)
from trading.services.feature_sets import (
    FeatureSetDatasetNotFoundError,
    FeatureSetDatasetNotMaterializableError,
    FeatureSetNotFoundError,
)

router = APIRouter(prefix="/feature-sets", tags=["feature-sets"])


@router.post("", response_model=FeatureSetResponse)
def create_feature_set(
    payload: FeatureSetCreateRequest,
    service: FeatureSetServiceDependency,
) -> FeatureSetResponse:
    try:
        feature_set = service.create_feature_set(
            ServiceFeatureSetCreateRequest(
                dataset_id=payload.dataset_id,
                name=payload.name,
                parameters=payload.parameters,
                code_version=payload.code_version,
                output_location=payload.output_location,
            )
        )
    except FeatureSetDatasetNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="dataset not found",
        ) from exc
    except (
        FeatureMaterializationError,
        FeatureSetDatasetNotMaterializableError,
        MarketDataError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return FeatureSetResponse.model_validate(feature_set)


@router.get("", response_model=FeatureSetListResponse)
def list_feature_sets(
    service: FeatureSetServiceDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    dataset_id: Annotated[int | None, Query(ge=1)] = None,
) -> FeatureSetListResponse:
    feature_sets = [
        FeatureSetResponse.model_validate(feature_set)
        for feature_set in service.list_feature_sets(limit=limit, dataset_id=dataset_id)
    ]
    return FeatureSetListResponse(feature_sets=feature_sets)


@router.get("/{feature_set_id}", response_model=FeatureSetResponse)
def get_feature_set(
    feature_set_id: Annotated[int, Path(ge=1)],
    service: FeatureSetServiceDependency,
) -> FeatureSetResponse:
    try:
        feature_set = service.get_feature_set(feature_set_id)
    except FeatureSetNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="feature set not found",
        ) from exc
    return FeatureSetResponse.model_validate(feature_set)
