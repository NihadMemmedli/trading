"""Pydantic schemas for split definitions and model experiments."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading.data.market import require_utc
from trading.services.model_experiments import (
    DEFAULT_BASELINE_NAME,
    SplitWindowCreateRequest,
)
from trading.services.model_experiments import (
    BaselineEvaluationRequest as ServiceBaselineEvaluationRequest,
)
from trading.services.model_experiments import (
    ModelExperimentCreateRequest as ServiceModelExperimentCreateRequest,
)
from trading.services.model_experiments import (
    SplitDefinitionCreateRequest as ServiceSplitDefinitionCreateRequest,
)


class SplitWindowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_index: int = Field(ge=0)
    split_name: str = Field(min_length=1, max_length=32)
    start: datetime
    end: datetime
    decision_time: datetime

    @field_validator("split_name")
    @classmethod
    def normalize_split_name(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"train", "validation", "test"}:
            raise ValueError("split_name must be train, validation, or test")
        return normalized

    @field_validator("start", "end", "decision_time")
    @classmethod
    def validate_datetime(cls, value: datetime) -> datetime:
        return require_utc(value, field_name="split window datetime")

    @model_validator(mode="after")
    def validate_range(self) -> SplitWindowRequest:
        if self.start >= self.end:
            raise ValueError("start must be earlier than end")
        if self.end > self.decision_time:
            raise ValueError("end must not be after decision_time")
        return self

    def to_service_request(self) -> SplitWindowCreateRequest:
        return SplitWindowCreateRequest(
            window_index=self.window_index,
            split_name=self.split_name,
            start=self.start,
            end=self.end,
            decision_time=self.decision_time,
        )


class SplitDefinitionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: int = Field(ge=1)
    feature_set_id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=128)
    split_type: str = Field(default="holdout", min_length=1, max_length=32)
    windows: list[SplitWindowRequest] = Field(min_length=3)
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("split_type")
    @classmethod
    def normalize_split_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"holdout", "walk_forward"}:
            raise ValueError("split_type must be holdout or walk_forward")
        return normalized

    def to_service_request(self) -> ServiceSplitDefinitionCreateRequest:
        return ServiceSplitDefinitionCreateRequest(
            dataset_id=self.dataset_id,
            feature_set_id=self.feature_set_id,
            name=self.name,
            split_type=self.split_type,
            windows=[window.to_service_request() for window in self.windows],
            config=self.config,
        )


class ModelExperimentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: int = Field(ge=1)
    feature_set_id: int = Field(ge=1)
    split_definition_id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=128)
    model_name: str = Field(min_length=1, max_length=128)
    parameters: dict[str, Any] = Field(default_factory=dict)
    code_version: str = Field(min_length=1, max_length=64)
    metrics: dict[str, Any] = Field(default_factory=dict)
    status: str = Field(default="created", min_length=1, max_length=32)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @field_validator("status")
    @classmethod
    def normalize_status(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"created", "running", "succeeded", "failed"}:
            raise ValueError("status must be created, running, succeeded, or failed")
        return normalized

    @field_validator("started_at", "completed_at")
    @classmethod
    def validate_optional_datetime(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return require_utc(value, field_name="experiment datetime")

    @model_validator(mode="after")
    def validate_timestamps(self) -> ModelExperimentCreateRequest:
        if self.started_at is not None and self.completed_at is not None:
            if self.completed_at < self.started_at:
                raise ValueError("completed_at must be after started_at")
        if self.status in {"succeeded", "failed"} and self.completed_at is None:
            raise ValueError("completed_at is required for terminal experiments")
        return self

    def to_service_request(self) -> ServiceModelExperimentCreateRequest:
        return ServiceModelExperimentCreateRequest(
            dataset_id=self.dataset_id,
            feature_set_id=self.feature_set_id,
            split_definition_id=self.split_definition_id,
            name=self.name,
            model_name=self.model_name,
            parameters=self.parameters,
            code_version=self.code_version,
            metrics=self.metrics,
            status=self.status,
            started_at=self.started_at,
            completed_at=self.completed_at,
        )


class BaselineEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: int = Field(ge=1)
    feature_set_id: int = Field(ge=1)
    split_definition_id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=128)
    baseline_name: str = Field(default=DEFAULT_BASELINE_NAME, min_length=1, max_length=128)
    code_version: str = Field(default="baseline_evaluator_v1", min_length=1, max_length=64)
    parameters: dict[str, Any] = Field(default_factory=dict)

    def to_service_request(self) -> ServiceBaselineEvaluationRequest:
        return ServiceBaselineEvaluationRequest(
            dataset_id=self.dataset_id,
            feature_set_id=self.feature_set_id,
            split_definition_id=self.split_definition_id,
            name=self.name,
            baseline_name=self.baseline_name,
            code_version=self.code_version,
            parameters=self.parameters,
        )


class SplitWindowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    window_index: int
    split_name: str
    start: datetime
    end: datetime
    decision_time: datetime


class SplitDefinitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dataset_id: int
    feature_set_id: int
    name: str
    split_type: str
    split_hash: str
    config: dict[str, Any]
    created_at: datetime
    windows: list[SplitWindowResponse] = Field(default_factory=list)


class SplitDefinitionListResponse(BaseModel):
    split_definitions: list[SplitDefinitionResponse] = Field(default_factory=list)


class ModelExperimentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    dataset_id: int
    feature_set_id: int
    split_definition_id: int
    name: str
    model_name: str
    parameter_hash: str
    experiment_hash: str
    code_version: str
    parameters: dict[str, Any]
    metrics: dict[str, Any]
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ModelExperimentListResponse(BaseModel):
    model_experiments: list[ModelExperimentResponse] = Field(default_factory=list)
