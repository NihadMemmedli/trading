"""Pydantic schemas for split definitions and model experiments."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
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
    LabelCreateRequest as ServiceLabelCreateRequest,
)
from trading.services.model_experiments import (
    ModelExperimentCreateRequest as ServiceModelExperimentCreateRequest,
)
from trading.services.model_experiments import (
    ModelPredictionCreateRequest as ServiceModelPredictionCreateRequest,
)
from trading.services.model_experiments import (
    PromotionGateRequest as ServicePromotionGateRequest,
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
    persist_predictions: bool = False
    persist_labels: bool = False

    def to_service_request(self) -> ServiceBaselineEvaluationRequest:
        return ServiceBaselineEvaluationRequest(
            dataset_id=self.dataset_id,
            feature_set_id=self.feature_set_id,
            split_definition_id=self.split_definition_id,
            name=self.name,
            baseline_name=self.baseline_name,
            code_version=self.code_version,
            parameters=self.parameters,
            persist_predictions=self.persist_predictions,
            persist_labels=self.persist_labels,
        )


class BaselineMaterializationRequest(BaselineEvaluationRequest):
    persist_predictions: bool = True
    persist_labels: bool = True

    @model_validator(mode="after")
    def validate_materialization_options(self) -> BaselineMaterializationRequest:
        if not self.persist_predictions and not self.persist_labels:
            raise ValueError("at least one of persist_predictions or persist_labels must be true")
        return self


class LabelCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: int = Field(ge=1)
    feature_set_id: int = Field(ge=1)
    feature_row_id: int = Field(ge=1)
    feature_hash: str = Field(min_length=64, max_length=64)
    label_name: str = Field(min_length=1, max_length=128)
    label_value: dict[str, Any]
    observed_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("feature_hash")
    @classmethod
    def normalize_feature_hash(cls, value: str) -> str:
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
            raise ValueError("feature_hash must be a SHA-256 hex digest")
        return normalized

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: datetime) -> datetime:
        return require_utc(value, field_name="observed_at")

    def to_service_request(self) -> ServiceLabelCreateRequest:
        return ServiceLabelCreateRequest(
            dataset_id=self.dataset_id,
            feature_set_id=self.feature_set_id,
            feature_row_id=self.feature_row_id,
            feature_hash=self.feature_hash,
            label_name=self.label_name,
            label_value=self.label_value,
            observed_at=self.observed_at,
            metadata=self.metadata,
        )


class ModelPredictionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_experiment_id: uuid.UUID
    feature_set_id: int = Field(ge=1)
    feature_row_id: int = Field(ge=1)
    feature_hash: str = Field(min_length=64, max_length=64)
    prediction_value: dict[str, Any]
    confidence: Decimal = Field(ge=0, le=1)
    decision_time: datetime
    lineage: dict[str, Any] = Field(default_factory=dict)

    @field_validator("feature_hash")
    @classmethod
    def normalize_feature_hash(cls, value: str) -> str:
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
            raise ValueError("feature_hash must be a SHA-256 hex digest")
        return normalized

    @field_validator("decision_time")
    @classmethod
    def validate_decision_time(cls, value: datetime) -> datetime:
        return require_utc(value, field_name="decision_time")

    def to_service_request(self) -> ServiceModelPredictionCreateRequest:
        return ServiceModelPredictionCreateRequest(
            model_experiment_id=self.model_experiment_id,
            feature_set_id=self.feature_set_id,
            feature_row_id=self.feature_row_id,
            feature_hash=self.feature_hash,
            prediction_value=self.prediction_value,
            confidence=self.confidence,
            decision_time=self.decision_time,
            lineage=self.lineage,
        )


class PromotionGateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_path: str = Field(min_length=1, max_length=256)
    minimum_value: Decimal

    def to_service_request(self) -> ServicePromotionGateRequest:
        return ServicePromotionGateRequest(
            metric_path=self.metric_path,
            minimum_value=self.minimum_value,
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


class BaselineMaterializationWindowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    window_index: int
    split_name: str
    prediction_count: int
    label_count: int
    skipped_first_row_count: int


class BaselineMaterializationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    experiment_id: uuid.UUID
    experiment: ModelExperimentResponse
    prediction_count: int
    label_count: int
    skipped_first_row_count: int
    split_counts: dict[str, dict[str, int]]
    window_counts: list[BaselineMaterializationWindowResponse] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def add_experiment_id(cls, value: Any) -> Any:
        if hasattr(value, "experiment"):
            return {
                "experiment_id": value.experiment.id,
                "experiment": value.experiment,
                "prediction_count": value.prediction_count,
                "label_count": value.label_count,
                "skipped_first_row_count": value.skipped_first_row_count,
                "split_counts": value.split_counts,
                "window_counts": value.window_counts,
            }
        return value


class LabelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dataset_id: int
    feature_set_id: int
    feature_row_id: int
    pair_id: int
    timeframe: str
    timestamp: datetime
    feature_hash: str
    label_name: str
    label_value: dict[str, Any]
    label_hash: str
    decision_time: datetime
    observed_at: datetime
    metadata: dict[str, Any]
    created_at: datetime


class LabelListResponse(BaseModel):
    labels: list[LabelResponse] = Field(default_factory=list)


class ModelPredictionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    model_experiment_id: uuid.UUID
    dataset_id: int
    feature_set_id: int
    split_definition_id: int
    feature_row_id: int
    pair_id: int
    timeframe: str
    timestamp: datetime
    feature_hash: str
    prediction_value: dict[str, Any]
    confidence: Decimal
    decision_time: datetime
    feature_row_decision_time: datetime
    prediction_hash: str
    lineage: dict[str, Any]
    created_at: datetime


class ModelPredictionListResponse(BaseModel):
    model_predictions: list[ModelPredictionResponse] = Field(default_factory=list)


class PromotionGateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    model_experiment_id: uuid.UUID
    approved: bool
    metric_path: str
    metric_value: Decimal | None
    minimum_value: Decimal
    reason: str
