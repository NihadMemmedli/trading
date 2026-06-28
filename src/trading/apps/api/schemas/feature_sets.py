"""Pydantic schemas for feature-set endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from trading.features import DEFAULT_FEATURE_CODE_VERSION


class FeatureSetCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=128)
    parameters: dict[str, Any] = Field(default_factory=lambda: {"lookback": 3})
    code_version: str = Field(default=DEFAULT_FEATURE_CODE_VERSION, min_length=1, max_length=64)
    output_location: str | None = None


class FeatureRowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: datetime
    decision_time: datetime
    available_at: datetime
    features: dict[str, Any]
    feature_hash: str


class FeatureSetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dataset_id: int
    name: str
    dataset_hash: str
    feature_set_hash: str
    parameter_hash: str
    code_version: str
    parameters: dict[str, Any]
    feature_names: list[str]
    selector: dict[str, Any]
    output_location: str | None
    created_at: datetime
    feature_row_count: int
    rows: list[FeatureRowResponse] = Field(default_factory=list)


class FeatureSetListResponse(BaseModel):
    feature_sets: list[FeatureSetResponse] = Field(default_factory=list)
