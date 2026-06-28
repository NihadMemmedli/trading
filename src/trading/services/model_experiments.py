"""Split definition and model experiment metadata service."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from trading.data.market import require_utc
from trading.db.models import (
    Dataset,
    FeatureRow,
    FeatureSet,
    Label,
    ModelExperiment,
    ModelPrediction,
    SplitDefinition,
    SplitWindow,
)
from trading.db.session import session_scope

SPLIT_NAMES = ("train", "validation", "test")
SPLIT_TYPES = ("holdout", "walk_forward")
EXPERIMENT_STATUSES = ("created", "running", "succeeded", "failed")
DEFAULT_BASELINE_NAME = "previous_return_direction"
BASELINE_RETURN_FEATURE = "close_return_1"


class SplitDefinitionNotFoundError(LookupError):
    """Raised when a split definition cannot be found."""


class ModelExperimentNotFoundError(LookupError):
    """Raised when a model experiment cannot be found."""


class LabelNotFoundError(LookupError):
    """Raised when a label cannot be found."""


class ModelPredictionNotFoundError(LookupError):
    """Raised when a model prediction cannot be found."""


class ModelingConflictError(ValueError):
    """Raised when a modeling record violates a uniqueness contract."""


class ModelExperimentLineageError(ValueError):
    """Raised when dataset, feature-set, or split lineage is inconsistent."""


class SplitValidationError(ValueError):
    """Raised when a split definition violates point-in-time validation."""


@dataclass(frozen=True)
class SplitWindowCreateRequest:
    window_index: int
    split_name: str
    start: datetime
    end: datetime
    decision_time: datetime


@dataclass(frozen=True)
class SplitDefinitionCreateRequest:
    dataset_id: int
    feature_set_id: int
    name: str
    split_type: str
    windows: Sequence[SplitWindowCreateRequest]
    config: Mapping[str, Any]


@dataclass(frozen=True)
class ModelExperimentCreateRequest:
    dataset_id: int
    feature_set_id: int
    split_definition_id: int
    name: str
    model_name: str
    parameters: Mapping[str, Any]
    code_version: str
    metrics: Mapping[str, Any]
    status: str = "created"
    started_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass(frozen=True)
class BaselineEvaluationRequest:
    dataset_id: int
    feature_set_id: int
    split_definition_id: int
    name: str
    baseline_name: str = DEFAULT_BASELINE_NAME
    code_version: str = "baseline_evaluator_v1"
    parameters: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class LabelCreateRequest:
    dataset_id: int
    feature_set_id: int
    feature_row_id: int
    feature_hash: str
    label_name: str
    label_value: Mapping[str, Any]
    observed_at: datetime
    metadata: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ModelPredictionCreateRequest:
    model_experiment_id: uuid.UUID
    feature_set_id: int
    feature_row_id: int
    feature_hash: str
    prediction_value: Mapping[str, Any]
    confidence: Decimal
    decision_time: datetime
    lineage: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class PromotionGateRequest:
    metric_path: str
    minimum_value: Decimal


@dataclass(frozen=True)
class SplitWindowRecord:
    id: int
    window_index: int
    split_name: str
    start: datetime
    end: datetime
    decision_time: datetime


@dataclass(frozen=True)
class SplitDefinitionRecord:
    id: int
    dataset_id: int
    feature_set_id: int
    name: str
    split_type: str
    split_hash: str
    config: dict[str, Any]
    created_at: datetime
    windows: tuple[SplitWindowRecord, ...] = ()


@dataclass(frozen=True)
class ModelExperimentRecord:
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


@dataclass(frozen=True)
class LabelRecord:
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


@dataclass(frozen=True)
class ModelPredictionRecord:
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


@dataclass(frozen=True)
class PromotionGateRecord:
    model_experiment_id: uuid.UUID
    approved: bool
    metric_path: str
    metric_value: Decimal | None
    minimum_value: Decimal
    reason: str


@dataclass(frozen=True)
class NormalizedSplitWindow:
    window_index: int
    split_name: str
    start: datetime
    end: datetime
    decision_time: datetime


@dataclass(frozen=True)
class BaselineFeatureRow:
    id: int
    pair_id: int
    timeframe: str
    timestamp: datetime
    features: Mapping[str, Any]


@dataclass(frozen=True)
class BaselineEvaluationWindow:
    window_index: int
    split_name: str
    start: datetime
    end: datetime
    decision_time: datetime
    rows: Sequence[BaselineFeatureRow]


@dataclass
class BaselineMetricCounts:
    observations: int = 0
    true_positives: int = 0
    false_positives: int = 0
    true_negatives: int = 0
    false_negatives: int = 0

    def add(self, *, predicted_positive: bool, target_positive: bool) -> None:
        self.observations += 1
        if predicted_positive and target_positive:
            self.true_positives += 1
        elif predicted_positive and not target_positive:
            self.false_positives += 1
        elif not predicted_positive and target_positive:
            self.false_negatives += 1
        else:
            self.true_negatives += 1

    def extend(self, other: BaselineMetricCounts) -> None:
        self.observations += other.observations
        self.true_positives += other.true_positives
        self.false_positives += other.false_positives
        self.true_negatives += other.true_negatives
        self.false_negatives += other.false_negatives


class ModelExperimentService:
    """Persists split definitions and model experiment metadata records."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_split_definition(
        self,
        request: SplitDefinitionCreateRequest,
    ) -> SplitDefinitionRecord:
        name = _normalize_name(request.name, field_name="split name")
        split_type = _normalize_choice(request.split_type, SPLIT_TYPES, field_name="split_type")
        config = _json_copy(dict(request.config), field_name="split config")
        windows = _normalize_windows(request.windows)
        _validate_window_shape(split_type, windows)

        with session_scope(self._session_factory) as session:
            self._validate_lineage(session, request.dataset_id, request.feature_set_id)
            self._validate_feature_windows(session, request.feature_set_id, windows)
            split_hash = deterministic_split_hash(
                dataset_id=request.dataset_id,
                feature_set_id=request.feature_set_id,
                name=name,
                split_type=split_type,
                config=config,
                windows=windows,
            )
            existing = _find_existing_split_definition(
                session,
                dataset_id=request.dataset_id,
                feature_set_id=request.feature_set_id,
                name=name,
                split_hash=split_hash,
            )
            if existing is not None:
                return _split_record_from_model(existing)

            split_definition = SplitDefinition(
                dataset_id=request.dataset_id,
                feature_set_id=request.feature_set_id,
                name=name,
                split_type=split_type,
                split_hash=split_hash,
                config_json=config,
            )
            session.add(split_definition)
            session.flush()
            session.add_all(
                SplitWindow(
                    split_definition_id=split_definition.id,
                    window_index=window.window_index,
                    split_name=window.split_name,
                    start_at=window.start,
                    end_at=window.end,
                    decision_time=window.decision_time,
                )
                for window in windows
            )
            session.flush()
            loaded = _load_split_definition(session, split_definition.id)
            return _split_record_from_model(loaded)

    def get_split_definition(self, split_definition_id: int) -> SplitDefinitionRecord:
        if isinstance(split_definition_id, bool) or split_definition_id < 1:
            raise SplitDefinitionNotFoundError(str(split_definition_id))

        with session_scope(self._session_factory) as session:
            split_definition = _load_split_definition(session, split_definition_id)
            return _split_record_from_model(split_definition)

    def list_split_definitions(
        self,
        *,
        limit: int = 50,
        dataset_id: int | None = None,
        feature_set_id: int | None = None,
    ) -> list[SplitDefinitionRecord]:
        _validate_positive_limit(limit)
        _validate_optional_positive_id(dataset_id, field_name="dataset_id")
        _validate_optional_positive_id(feature_set_id, field_name="feature_set_id")

        with session_scope(self._session_factory) as session:
            query = select(SplitDefinition).options(selectinload(SplitDefinition.windows))
            if dataset_id is not None:
                query = query.where(SplitDefinition.dataset_id == dataset_id)
            if feature_set_id is not None:
                query = query.where(SplitDefinition.feature_set_id == feature_set_id)
            rows = session.execute(
                query.order_by(SplitDefinition.created_at.desc(), SplitDefinition.id.desc()).limit(
                    limit
                )
            ).scalars()
            return [_split_record_from_model(split_definition) for split_definition in rows]

    def create_model_experiment(
        self,
        request: ModelExperimentCreateRequest,
    ) -> ModelExperimentRecord:
        name = _normalize_name(request.name, field_name="experiment name")
        model_name = _normalize_name(request.model_name, field_name="model_name")
        code_version = _normalize_name(request.code_version, field_name="code_version", max_len=64)
        status = _normalize_choice(request.status, EXPERIMENT_STATUSES, field_name="status")
        parameters = _json_copy(dict(request.parameters), field_name="parameters")
        metrics = _json_copy(dict(request.metrics), field_name="metrics")
        started_at = _normalize_optional_utc(request.started_at, field_name="started_at")
        completed_at = _normalize_optional_utc(request.completed_at, field_name="completed_at")
        if started_at is not None and completed_at is not None and completed_at < started_at:
            raise SplitValidationError("completed_at must be after started_at")
        if status in {"succeeded", "failed"} and completed_at is None:
            raise SplitValidationError("completed_at is required for terminal experiments")

        parameter_hash = deterministic_model_parameter_hash(parameters)
        with session_scope(self._session_factory) as session:
            self._validate_lineage(session, request.dataset_id, request.feature_set_id)
            split_definition = _load_split_definition(session, request.split_definition_id)
            if split_definition.dataset_id != request.dataset_id:
                raise ModelExperimentLineageError("split definition dataset_id mismatch")
            if split_definition.feature_set_id != request.feature_set_id:
                raise ModelExperimentLineageError("split definition feature_set_id mismatch")
            self._validate_feature_windows(
                session,
                request.feature_set_id,
                _normalized_windows_from_model(split_definition),
            )
            experiment_hash = deterministic_experiment_hash(
                dataset_id=request.dataset_id,
                feature_set_id=request.feature_set_id,
                split_definition_id=request.split_definition_id,
                split_hash=split_definition.split_hash,
                name=name,
                model_name=model_name,
                code_version=code_version,
                parameters=parameters,
                metrics=metrics,
                status=status,
            )
            experiment = ModelExperiment(
                dataset_id=request.dataset_id,
                feature_set_id=request.feature_set_id,
                split_definition_id=request.split_definition_id,
                name=name,
                model_name=model_name,
                parameter_hash=parameter_hash,
                experiment_hash=experiment_hash,
                code_version=code_version,
                parameters_json=parameters,
                metrics_json=metrics,
                status=status,
                started_at=started_at,
                completed_at=completed_at,
            )
            session.add(experiment)
            session.flush()
            session.refresh(experiment)
            return _experiment_record_from_model(experiment)

    def evaluate_baseline_model(
        self,
        request: BaselineEvaluationRequest,
    ) -> ModelExperimentRecord:
        name = _normalize_name(request.name, field_name="experiment name")
        baseline_name = _normalize_name(request.baseline_name, field_name="baseline_name")
        if baseline_name != DEFAULT_BASELINE_NAME:
            raise SplitValidationError(f"baseline_name must be {DEFAULT_BASELINE_NAME}")
        code_version = _normalize_name(request.code_version, field_name="code_version", max_len=64)
        user_parameters = _json_copy(dict(request.parameters or {}), field_name="parameters")
        started_at = datetime.now(UTC)

        with session_scope(self._session_factory) as session:
            self._validate_lineage(session, request.dataset_id, request.feature_set_id)
            split_definition = _load_split_definition(session, request.split_definition_id)
            if split_definition.dataset_id != request.dataset_id:
                raise ModelExperimentLineageError("split definition dataset_id mismatch")
            if split_definition.feature_set_id != request.feature_set_id:
                raise ModelExperimentLineageError("split definition feature_set_id mismatch")

            windows = _normalized_windows_from_model(split_definition)
            self._validate_feature_windows(session, request.feature_set_id, windows)
            evaluation_windows = _load_baseline_evaluation_windows(
                session,
                feature_set_id=request.feature_set_id,
                windows=windows,
            )
            metrics = evaluate_previous_return_direction_baseline(evaluation_windows)
            parameters = _baseline_parameters(
                baseline_name=baseline_name,
                user_parameters=user_parameters,
                split_definition=split_definition,
            )
            completed_at = datetime.now(UTC)
            parameter_hash = deterministic_model_parameter_hash(parameters)
            experiment_hash = deterministic_experiment_hash(
                dataset_id=request.dataset_id,
                feature_set_id=request.feature_set_id,
                split_definition_id=request.split_definition_id,
                split_hash=split_definition.split_hash,
                name=name,
                model_name=baseline_name,
                code_version=code_version,
                parameters=parameters,
                metrics=metrics,
                status="succeeded",
            )
            experiment = ModelExperiment(
                dataset_id=request.dataset_id,
                feature_set_id=request.feature_set_id,
                split_definition_id=request.split_definition_id,
                name=name,
                model_name=baseline_name,
                parameter_hash=parameter_hash,
                experiment_hash=experiment_hash,
                code_version=code_version,
                parameters_json=parameters,
                metrics_json=metrics,
                status="succeeded",
                started_at=started_at,
                completed_at=completed_at,
            )
            session.add(experiment)
            session.flush()
            session.refresh(experiment)
            return _experiment_record_from_model(experiment)

    def get_model_experiment(self, experiment_id: uuid.UUID) -> ModelExperimentRecord:
        with session_scope(self._session_factory) as session:
            experiment = session.get(ModelExperiment, experiment_id)
            if experiment is None:
                raise ModelExperimentNotFoundError(str(experiment_id))
            return _experiment_record_from_model(experiment)

    def list_model_experiments(
        self,
        *,
        limit: int = 50,
        dataset_id: int | None = None,
        feature_set_id: int | None = None,
        split_definition_id: int | None = None,
    ) -> list[ModelExperimentRecord]:
        _validate_positive_limit(limit)
        _validate_optional_positive_id(dataset_id, field_name="dataset_id")
        _validate_optional_positive_id(feature_set_id, field_name="feature_set_id")
        _validate_optional_positive_id(split_definition_id, field_name="split_definition_id")

        with session_scope(self._session_factory) as session:
            query = select(ModelExperiment)
            if dataset_id is not None:
                query = query.where(ModelExperiment.dataset_id == dataset_id)
            if feature_set_id is not None:
                query = query.where(ModelExperiment.feature_set_id == feature_set_id)
            if split_definition_id is not None:
                query = query.where(ModelExperiment.split_definition_id == split_definition_id)
            rows = session.execute(
                query.order_by(
                    ModelExperiment.created_at.desc(),
                    ModelExperiment.id.desc(),
                ).limit(limit)
            ).scalars()
            return [_experiment_record_from_model(experiment) for experiment in rows]

    def create_label(self, request: LabelCreateRequest) -> LabelRecord:
        label_name = _normalize_name(request.label_name, field_name="label_name")
        label_value = _json_copy(dict(request.label_value), field_name="label_value")
        metadata = _json_copy(dict(request.metadata or {}), field_name="metadata")
        observed_at = require_utc(request.observed_at, field_name="observed_at")
        feature_hash = _normalize_hash(request.feature_hash, field_name="feature_hash")

        with session_scope(self._session_factory) as session:
            self._validate_lineage(session, request.dataset_id, request.feature_set_id)
            feature_row = _load_feature_row_for_lineage(
                session,
                feature_set_id=request.feature_set_id,
                feature_row_id=request.feature_row_id,
                feature_hash=feature_hash,
            )
            if observed_at < feature_row.decision_time:
                raise SplitValidationError(
                    "observed_at must not be before feature row decision_time"
                )
            existing = _find_existing_label(
                session,
                feature_set_id=request.feature_set_id,
                feature_row_id=request.feature_row_id,
                label_name=label_name,
            )
            if existing is not None:
                raise ModelingConflictError("label already exists")
            label_hash = deterministic_label_hash(
                dataset_id=request.dataset_id,
                feature_set_id=request.feature_set_id,
                feature_row_id=request.feature_row_id,
                feature_hash=feature_hash,
                label_name=label_name,
                label_value=label_value,
                decision_time=feature_row.decision_time,
                observed_at=observed_at,
                metadata=metadata,
            )
            label = Label(
                dataset_id=request.dataset_id,
                feature_set_id=request.feature_set_id,
                feature_row_id=request.feature_row_id,
                pair_id=feature_row.pair_id,
                timeframe=feature_row.timeframe,
                timestamp=feature_row.timestamp,
                feature_hash=feature_hash,
                label_name=label_name,
                label_value_json=label_value,
                label_hash=label_hash,
                decision_time=feature_row.decision_time,
                observed_at=observed_at,
                metadata_json=metadata,
            )
            session.add(label)
            session.flush()
            session.refresh(label)
            return _label_record_from_model(label)

    def get_label(self, label_id: int) -> LabelRecord:
        if isinstance(label_id, bool) or label_id < 1:
            raise LabelNotFoundError(str(label_id))

        with session_scope(self._session_factory) as session:
            label = session.get(Label, label_id)
            if label is None:
                raise LabelNotFoundError(str(label_id))
            return _label_record_from_model(label)

    def list_labels(
        self,
        *,
        limit: int = 50,
        dataset_id: int | None = None,
        feature_set_id: int | None = None,
        feature_row_id: int | None = None,
        label_name: str | None = None,
    ) -> list[LabelRecord]:
        _validate_positive_limit(limit)
        _validate_optional_positive_id(dataset_id, field_name="dataset_id")
        _validate_optional_positive_id(feature_set_id, field_name="feature_set_id")
        _validate_optional_positive_id(feature_row_id, field_name="feature_row_id")
        normalized_label_name = (
            _normalize_name(label_name, field_name="label_name") if label_name is not None else None
        )

        with session_scope(self._session_factory) as session:
            query = select(Label)
            if dataset_id is not None:
                query = query.where(Label.dataset_id == dataset_id)
            if feature_set_id is not None:
                query = query.where(Label.feature_set_id == feature_set_id)
            if feature_row_id is not None:
                query = query.where(Label.feature_row_id == feature_row_id)
            if normalized_label_name is not None:
                query = query.where(Label.label_name == normalized_label_name)
            rows = session.execute(
                query.order_by(Label.created_at.desc(), Label.id.desc()).limit(limit)
            ).scalars()
            return [_label_record_from_model(label) for label in rows]

    def create_model_prediction(
        self,
        request: ModelPredictionCreateRequest,
    ) -> ModelPredictionRecord:
        feature_hash = _normalize_hash(request.feature_hash, field_name="feature_hash")
        prediction_value = _json_copy(dict(request.prediction_value), field_name="prediction_value")
        lineage = _json_copy(dict(request.lineage or {}), field_name="lineage")
        confidence = _normalize_confidence(request.confidence)
        decision_time = require_utc(request.decision_time, field_name="decision_time")

        with session_scope(self._session_factory) as session:
            experiment = session.get(ModelExperiment, request.model_experiment_id)
            if experiment is None:
                raise ModelExperimentNotFoundError(str(request.model_experiment_id))
            if experiment.status != "succeeded":
                raise SplitValidationError("model experiment must be succeeded")
            if not experiment.metrics_json:
                raise SplitValidationError("model experiment must include metrics")
            if experiment.feature_set_id != request.feature_set_id:
                raise ModelExperimentLineageError("model experiment feature_set_id mismatch")
            self._validate_lineage(session, experiment.dataset_id, request.feature_set_id)
            feature_row = _load_feature_row_for_lineage(
                session,
                feature_set_id=request.feature_set_id,
                feature_row_id=request.feature_row_id,
                feature_hash=feature_hash,
            )
            if feature_row.decision_time > decision_time:
                raise SplitValidationError(
                    "decision_time must not be before feature row decision_time"
                )
            if feature_row.available_at > decision_time:
                raise SplitValidationError("feature row is not available at decision_time")
            prediction_hash = deterministic_prediction_hash(
                model_experiment_id=request.model_experiment_id,
                dataset_id=experiment.dataset_id,
                feature_set_id=request.feature_set_id,
                split_definition_id=experiment.split_definition_id,
                feature_row_id=request.feature_row_id,
                feature_hash=feature_hash,
                prediction_value=prediction_value,
                confidence=confidence,
                decision_time=decision_time,
                lineage=lineage,
            )
            existing = _find_existing_model_prediction(
                session,
                model_experiment_id=request.model_experiment_id,
                feature_row_id=request.feature_row_id,
                prediction_hash=prediction_hash,
            )
            if existing is not None:
                raise ModelingConflictError("model prediction already exists")
            prediction = ModelPrediction(
                model_experiment_id=request.model_experiment_id,
                dataset_id=experiment.dataset_id,
                feature_set_id=request.feature_set_id,
                split_definition_id=experiment.split_definition_id,
                feature_row_id=request.feature_row_id,
                pair_id=feature_row.pair_id,
                timeframe=feature_row.timeframe,
                timestamp=feature_row.timestamp,
                feature_hash=feature_hash,
                prediction_value_json=prediction_value,
                confidence=confidence,
                decision_time=decision_time,
                feature_row_decision_time=feature_row.decision_time,
                prediction_hash=prediction_hash,
                lineage_json=lineage,
            )
            session.add(prediction)
            session.flush()
            session.refresh(prediction)
            return _prediction_record_from_model(prediction)

    def get_model_prediction(self, prediction_id: int) -> ModelPredictionRecord:
        if isinstance(prediction_id, bool) or prediction_id < 1:
            raise ModelPredictionNotFoundError(str(prediction_id))

        with session_scope(self._session_factory) as session:
            prediction = session.get(ModelPrediction, prediction_id)
            if prediction is None:
                raise ModelPredictionNotFoundError(str(prediction_id))
            return _prediction_record_from_model(prediction)

    def list_model_predictions(
        self,
        *,
        limit: int = 50,
        model_experiment_id: uuid.UUID | None = None,
        feature_set_id: int | None = None,
        feature_row_id: int | None = None,
    ) -> list[ModelPredictionRecord]:
        _validate_positive_limit(limit)
        _validate_optional_positive_id(feature_set_id, field_name="feature_set_id")
        _validate_optional_positive_id(feature_row_id, field_name="feature_row_id")

        with session_scope(self._session_factory) as session:
            query = select(ModelPrediction)
            if model_experiment_id is not None:
                query = query.where(ModelPrediction.model_experiment_id == model_experiment_id)
            if feature_set_id is not None:
                query = query.where(ModelPrediction.feature_set_id == feature_set_id)
            if feature_row_id is not None:
                query = query.where(ModelPrediction.feature_row_id == feature_row_id)
            rows = session.execute(
                query.order_by(
                    ModelPrediction.created_at.desc(),
                    ModelPrediction.id.desc(),
                ).limit(limit)
            ).scalars()
            return [_prediction_record_from_model(prediction) for prediction in rows]

    def evaluate_promotion_gate(
        self,
        experiment_id: uuid.UUID,
        request: PromotionGateRequest,
    ) -> PromotionGateRecord:
        metric_path = _normalize_metric_path(request.metric_path)
        minimum_value = _normalize_decimal(request.minimum_value, field_name="minimum_value")

        with session_scope(self._session_factory) as session:
            experiment = session.get(ModelExperiment, experiment_id)
            if experiment is None:
                raise ModelExperimentNotFoundError(str(experiment_id))
            if experiment.status != "succeeded":
                return PromotionGateRecord(
                    model_experiment_id=experiment_id,
                    approved=False,
                    metric_path=metric_path,
                    metric_value=None,
                    minimum_value=minimum_value,
                    reason="model experiment is not succeeded",
                )
            if not experiment.metrics_json:
                return PromotionGateRecord(
                    model_experiment_id=experiment_id,
                    approved=False,
                    metric_path=metric_path,
                    metric_value=None,
                    minimum_value=minimum_value,
                    reason="model experiment has no metrics",
                )
            raw_value = _metric_value_at_path(experiment.metrics_json, metric_path)
            if raw_value is None:
                return PromotionGateRecord(
                    model_experiment_id=experiment_id,
                    approved=False,
                    metric_path=metric_path,
                    metric_value=None,
                    minimum_value=minimum_value,
                    reason="metric not found",
                )
            metric_value = _normalize_decimal(raw_value, field_name="metric_value")
            approved = metric_value >= minimum_value
            return PromotionGateRecord(
                model_experiment_id=experiment_id,
                approved=approved,
                metric_path=metric_path,
                metric_value=metric_value,
                minimum_value=minimum_value,
                reason="metric threshold passed" if approved else "metric below threshold",
            )

    def _validate_lineage(
        self,
        session: Session,
        dataset_id: int,
        feature_set_id: int,
    ) -> None:
        if isinstance(dataset_id, bool) or dataset_id < 1:
            raise ModelExperimentLineageError("dataset not found")
        if isinstance(feature_set_id, bool) or feature_set_id < 1:
            raise ModelExperimentLineageError("feature set not found")
        dataset = session.get(Dataset, dataset_id)
        if dataset is None:
            raise ModelExperimentLineageError("dataset not found")
        feature_set = session.get(FeatureSet, feature_set_id)
        if feature_set is None:
            raise ModelExperimentLineageError("feature set not found")
        if feature_set.dataset_id != dataset.id:
            raise ModelExperimentLineageError("feature set dataset_id mismatch")
        if feature_set.dataset_hash != dataset.dataset_hash:
            raise ModelExperimentLineageError("feature set dataset_hash mismatch")

    def _validate_feature_windows(
        self,
        session: Session,
        feature_set_id: int,
        windows: Sequence[NormalizedSplitWindow],
    ) -> None:
        leaked_rows = session.scalar(
            select(func.count())
            .select_from(FeatureRow)
            .where(
                FeatureRow.feature_set_id == feature_set_id,
                FeatureRow.available_at > FeatureRow.decision_time,
            )
        )
        if leaked_rows:
            raise SplitValidationError("feature set contains rows unavailable at decision_time")

        for window in windows:
            total_rows = _feature_row_count(
                session,
                feature_set_id=feature_set_id,
                start=window.start,
                end=window.end,
            )
            if total_rows == 0:
                raise SplitValidationError(
                    f"{window.split_name} window {window.window_index} has no feature rows"
                )
            eligible_rows = _feature_row_count(
                session,
                feature_set_id=feature_set_id,
                start=window.start,
                end=window.end,
                decision_time=window.decision_time,
            )
            if eligible_rows != total_rows:
                raise SplitValidationError(
                    f"{window.split_name} window {window.window_index} includes unavailable rows"
                )


def deterministic_model_parameter_hash(parameters: Mapping[str, Any]) -> str:
    return _sha256_json({"parameters": _json_copy(dict(parameters), field_name="parameters")})


def deterministic_label_hash(
    *,
    dataset_id: int,
    feature_set_id: int,
    feature_row_id: int,
    feature_hash: str,
    label_name: str,
    label_value: Mapping[str, Any],
    decision_time: datetime,
    observed_at: datetime,
    metadata: Mapping[str, Any],
) -> str:
    return _sha256_json(
        {
            "dataset_id": dataset_id,
            "feature_set_id": feature_set_id,
            "feature_row_id": feature_row_id,
            "feature_hash": feature_hash,
            "label_name": label_name,
            "label_value": _json_copy(dict(label_value), field_name="label_value"),
            "decision_time": decision_time,
            "observed_at": observed_at,
            "metadata": _json_copy(dict(metadata), field_name="metadata"),
        }
    )


def deterministic_prediction_hash(
    *,
    model_experiment_id: uuid.UUID,
    dataset_id: int,
    feature_set_id: int,
    split_definition_id: int,
    feature_row_id: int,
    feature_hash: str,
    prediction_value: Mapping[str, Any],
    confidence: Decimal,
    decision_time: datetime,
    lineage: Mapping[str, Any],
) -> str:
    return _sha256_json(
        {
            "model_experiment_id": str(model_experiment_id),
            "dataset_id": dataset_id,
            "feature_set_id": feature_set_id,
            "split_definition_id": split_definition_id,
            "feature_row_id": feature_row_id,
            "feature_hash": feature_hash,
            "prediction_value": _json_copy(dict(prediction_value), field_name="prediction_value"),
            "confidence": str(confidence),
            "decision_time": decision_time,
            "lineage": _json_copy(dict(lineage), field_name="lineage"),
        }
    )


def deterministic_split_hash(
    *,
    dataset_id: int,
    feature_set_id: int,
    name: str,
    split_type: str,
    config: Mapping[str, Any],
    windows: Sequence[NormalizedSplitWindow],
) -> str:
    return _sha256_json(
        {
            "dataset_id": dataset_id,
            "feature_set_id": feature_set_id,
            "name": name,
            "split_type": split_type,
            "config": _json_copy(dict(config), field_name="split config"),
            "windows": [_window_json(window) for window in windows],
        }
    )


def deterministic_experiment_hash(
    *,
    dataset_id: int,
    feature_set_id: int,
    split_definition_id: int,
    split_hash: str,
    name: str,
    model_name: str,
    code_version: str,
    parameters: Mapping[str, Any],
    metrics: Mapping[str, Any],
    status: str,
) -> str:
    return _sha256_json(
        {
            "dataset_id": dataset_id,
            "feature_set_id": feature_set_id,
            "split_definition_id": split_definition_id,
            "split_hash": split_hash,
            "name": name,
            "model_name": model_name,
            "code_version": code_version,
            "parameter_hash": deterministic_model_parameter_hash(parameters),
            "metrics": _json_copy(dict(metrics), field_name="metrics"),
            "status": status,
        }
    )


def evaluate_previous_return_direction_baseline(
    windows: Sequence[BaselineEvaluationWindow],
) -> dict[str, Any]:
    if not windows:
        raise SplitValidationError("at least one evaluation window is required")

    overall = BaselineMetricCounts()
    by_split = {split_name: BaselineMetricCounts() for split_name in SPLIT_NAMES}
    window_metrics: list[dict[str, Any]] = []

    for window in windows:
        window_counts = _evaluate_baseline_window(window)
        if window_counts.observations == 0:
            raise SplitValidationError(
                f"{window.split_name} window {window.window_index} has no baseline observations"
            )
        overall.extend(window_counts)
        by_split[window.split_name].extend(window_counts)
        window_metrics.append(
            {
                "window_index": window.window_index,
                "split_name": window.split_name,
                "metrics": _metric_counts_json(window_counts),
            }
        )

    for split_name, split_counts in by_split.items():
        if split_counts.observations == 0:
            raise SplitValidationError(f"{split_name} split has no baseline observations")

    return {
        "overall": _metric_counts_json(overall),
        "by_split": {
            split_name: _metric_counts_json(by_split[split_name]) for split_name in SPLIT_NAMES
        },
        "windows": window_metrics,
    }


def _find_existing_split_definition(
    session: Session,
    *,
    dataset_id: int,
    feature_set_id: int,
    name: str,
    split_hash: str,
) -> SplitDefinition | None:
    return session.execute(
        select(SplitDefinition)
        .options(selectinload(SplitDefinition.windows))
        .where(
            SplitDefinition.dataset_id == dataset_id,
            SplitDefinition.feature_set_id == feature_set_id,
            SplitDefinition.name == name,
            SplitDefinition.split_hash == split_hash,
        )
    ).scalar_one_or_none()


def _find_existing_label(
    session: Session,
    *,
    feature_set_id: int,
    feature_row_id: int,
    label_name: str,
) -> Label | None:
    return session.execute(
        select(Label).where(
            Label.feature_set_id == feature_set_id,
            Label.feature_row_id == feature_row_id,
            Label.label_name == label_name,
        )
    ).scalar_one_or_none()


def _find_existing_model_prediction(
    session: Session,
    *,
    model_experiment_id: uuid.UUID,
    feature_row_id: int,
    prediction_hash: str,
) -> ModelPrediction | None:
    return session.execute(
        select(ModelPrediction).where(
            ModelPrediction.model_experiment_id == model_experiment_id,
            ModelPrediction.feature_row_id == feature_row_id,
            ModelPrediction.prediction_hash == prediction_hash,
        )
    ).scalar_one_or_none()


def _load_split_definition(session: Session, split_definition_id: int) -> SplitDefinition:
    split_definition = session.execute(
        select(SplitDefinition)
        .options(selectinload(SplitDefinition.windows))
        .where(SplitDefinition.id == split_definition_id)
    ).scalar_one_or_none()
    if split_definition is None:
        raise SplitDefinitionNotFoundError(str(split_definition_id))
    return split_definition


def _load_feature_row_for_lineage(
    session: Session,
    *,
    feature_set_id: int,
    feature_row_id: int,
    feature_hash: str,
) -> FeatureRow:
    if isinstance(feature_row_id, bool) or feature_row_id < 1:
        raise ModelExperimentLineageError("feature row not found")
    feature_row = session.get(FeatureRow, feature_row_id)
    if feature_row is None:
        raise ModelExperimentLineageError("feature row not found")
    if feature_row.feature_set_id != feature_set_id:
        raise ModelExperimentLineageError("feature row feature_set_id mismatch")
    if feature_row.feature_hash != feature_hash:
        raise ModelExperimentLineageError("feature row feature_hash mismatch")
    return feature_row


def _load_baseline_evaluation_windows(
    session: Session,
    *,
    feature_set_id: int,
    windows: Sequence[NormalizedSplitWindow],
) -> tuple[BaselineEvaluationWindow, ...]:
    evaluation_windows: list[BaselineEvaluationWindow] = []
    for window in windows:
        rows = session.execute(
            select(FeatureRow)
            .where(
                FeatureRow.feature_set_id == feature_set_id,
                FeatureRow.timestamp >= window.start,
                FeatureRow.timestamp <= window.end,
                FeatureRow.available_at <= window.decision_time,
            )
            .order_by(
                FeatureRow.pair_id,
                FeatureRow.timeframe,
                FeatureRow.timestamp,
                FeatureRow.id,
            )
        ).scalars()
        evaluation_windows.append(
            BaselineEvaluationWindow(
                window_index=window.window_index,
                split_name=window.split_name,
                start=window.start,
                end=window.end,
                decision_time=window.decision_time,
                rows=tuple(
                    BaselineFeatureRow(
                        id=row.id,
                        pair_id=row.pair_id,
                        timeframe=row.timeframe,
                        timestamp=row.timestamp,
                        features=dict(row.features_json),
                    )
                    for row in rows
                ),
            )
        )
    return tuple(evaluation_windows)


def _feature_row_count(
    session: Session,
    *,
    feature_set_id: int,
    start: datetime,
    end: datetime,
    decision_time: datetime | None = None,
) -> int:
    query: Select[tuple[int]] = (
        select(func.count())
        .select_from(FeatureRow)
        .where(
            FeatureRow.feature_set_id == feature_set_id,
            FeatureRow.timestamp >= start,
            FeatureRow.timestamp <= end,
        )
    )
    if decision_time is not None:
        query = query.where(
            FeatureRow.available_at <= decision_time,
            FeatureRow.decision_time <= decision_time,
        )
    return int(session.scalar(query) or 0)


def _normalize_windows(
    windows: Sequence[SplitWindowCreateRequest],
) -> tuple[NormalizedSplitWindow, ...]:
    if not windows:
        raise SplitValidationError("at least one split window is required")

    normalized = tuple(
        NormalizedSplitWindow(
            window_index=_normalize_window_index(window.window_index),
            split_name=_normalize_choice(window.split_name, SPLIT_NAMES, field_name="split_name"),
            start=require_utc(window.start, field_name="window start"),
            end=require_utc(window.end, field_name="window end"),
            decision_time=require_utc(window.decision_time, field_name="window decision_time"),
        )
        for window in windows
    )
    for window in normalized:
        if window.start >= window.end:
            raise SplitValidationError("window start must be earlier than end")
        if window.end > window.decision_time:
            raise SplitValidationError("window end must not be after decision_time")
    duplicates = {
        (window.window_index, window.split_name)
        for window in normalized
        if sum(
            1
            for other in normalized
            if other.window_index == window.window_index and other.split_name == window.split_name
        )
        > 1
    }
    if duplicates:
        raise SplitValidationError("duplicate split window index/name")
    return tuple(sorted(normalized, key=lambda item: (item.window_index, item.split_name)))


def _evaluate_baseline_window(window: BaselineEvaluationWindow) -> BaselineMetricCounts:
    counts = BaselineMetricCounts()
    grouped_rows: dict[tuple[int, str], list[BaselineFeatureRow]] = {}
    for row in window.rows:
        grouped_rows.setdefault((row.pair_id, row.timeframe), []).append(row)

    for rows in grouped_rows.values():
        previous_return: Decimal | None = None
        for row in sorted(rows, key=lambda item: (item.timestamp, item.id)):
            current_return = _close_return_1(row)
            if previous_return is None:
                previous_return = current_return
                continue
            counts.add(
                predicted_positive=previous_return > 0,
                target_positive=current_return > 0,
            )
            previous_return = current_return
    return counts


def _close_return_1(row: BaselineFeatureRow) -> Decimal:
    raw_value = row.features.get(BASELINE_RETURN_FEATURE)
    if raw_value is None or isinstance(raw_value, bool):
        raise SplitValidationError(f"feature row {row.id} is missing {BASELINE_RETURN_FEATURE}")
    try:
        value = Decimal(str(raw_value))
    except (InvalidOperation, ValueError) as exc:
        raise SplitValidationError(
            f"feature row {row.id} has invalid {BASELINE_RETURN_FEATURE}"
        ) from exc
    if not value.is_finite():
        raise SplitValidationError(f"feature row {row.id} has invalid {BASELINE_RETURN_FEATURE}")
    return value


def _metric_counts_json(counts: BaselineMetricCounts) -> dict[str, Any]:
    correct = counts.true_positives + counts.true_negatives
    predicted_positive = counts.true_positives + counts.false_positives
    target_positive = counts.true_positives + counts.false_negatives
    return {
        "observations": counts.observations,
        "accuracy": _ratio(correct, counts.observations),
        "true_positives": counts.true_positives,
        "false_positives": counts.false_positives,
        "true_negatives": counts.true_negatives,
        "false_negatives": counts.false_negatives,
        "positive_prediction_rate": _ratio(predicted_positive, counts.observations),
        "target_positive_rate": _ratio(target_positive, counts.observations),
    }


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 12)


def _baseline_parameters(
    *,
    baseline_name: str,
    user_parameters: Mapping[str, Any],
    split_definition: SplitDefinition,
) -> dict[str, Any]:
    return _json_copy(
        {
            "baseline": {
                "name": baseline_name,
                "prediction_feature": BASELINE_RETURN_FEATURE,
                "target_feature": BASELINE_RETURN_FEATURE,
                "positive_threshold": "0",
                "rule": (
                    "predict current positive return when previous eligible row return is positive"
                ),
            },
            "parameters": _json_copy(dict(user_parameters), field_name="parameters"),
            "split_definition": {
                "id": split_definition.id,
                "name": split_definition.name,
                "split_type": split_definition.split_type,
                "split_hash": split_definition.split_hash,
                "windows": [
                    _window_json(window)
                    for window in _normalized_windows_from_model(split_definition)
                ],
            },
        },
        field_name="baseline parameters",
    )


def _validate_window_shape(
    split_type: str,
    windows: Sequence[NormalizedSplitWindow],
) -> None:
    windows_by_index: dict[int, dict[str, NormalizedSplitWindow]] = {}
    for window in windows:
        windows_by_index.setdefault(window.window_index, {})[window.split_name] = window

    if split_type == "holdout" and set(windows_by_index) != {0}:
        raise SplitValidationError("holdout splits must use a single window_index")

    for window_index, named_windows in windows_by_index.items():
        if set(named_windows) != set(SPLIT_NAMES):
            raise SplitValidationError(
                f"window {window_index} must include train, validation, and test splits"
            )
        train = named_windows["train"]
        validation = named_windows["validation"]
        test = named_windows["test"]
        if train.end > validation.start:
            raise SplitValidationError("train window must end before validation starts")
        if validation.end > test.start:
            raise SplitValidationError("validation window must end before test starts")


def _normalized_windows_from_model(
    split_definition: SplitDefinition,
) -> tuple[NormalizedSplitWindow, ...]:
    return tuple(
        NormalizedSplitWindow(
            window_index=window.window_index,
            split_name=window.split_name,
            start=window.start_at,
            end=window.end_at,
            decision_time=window.decision_time,
        )
        for window in split_definition.windows
    )


def _split_record_from_model(split_definition: SplitDefinition) -> SplitDefinitionRecord:
    return SplitDefinitionRecord(
        id=split_definition.id,
        dataset_id=split_definition.dataset_id,
        feature_set_id=split_definition.feature_set_id,
        name=split_definition.name,
        split_type=split_definition.split_type,
        split_hash=split_definition.split_hash,
        config=dict(split_definition.config_json),
        created_at=split_definition.created_at,
        windows=tuple(
            SplitWindowRecord(
                id=window.id,
                window_index=window.window_index,
                split_name=window.split_name,
                start=window.start_at,
                end=window.end_at,
                decision_time=window.decision_time,
            )
            for window in split_definition.windows
        ),
    )


def _experiment_record_from_model(experiment: ModelExperiment) -> ModelExperimentRecord:
    return ModelExperimentRecord(
        id=experiment.id,
        dataset_id=experiment.dataset_id,
        feature_set_id=experiment.feature_set_id,
        split_definition_id=experiment.split_definition_id,
        name=experiment.name,
        model_name=experiment.model_name,
        parameter_hash=experiment.parameter_hash,
        experiment_hash=experiment.experiment_hash,
        code_version=experiment.code_version,
        parameters=dict(experiment.parameters_json),
        metrics=dict(experiment.metrics_json),
        status=experiment.status,
        started_at=experiment.started_at,
        completed_at=experiment.completed_at,
        created_at=experiment.created_at,
        updated_at=experiment.updated_at,
    )


def _label_record_from_model(label: Label) -> LabelRecord:
    return LabelRecord(
        id=label.id,
        dataset_id=label.dataset_id,
        feature_set_id=label.feature_set_id,
        feature_row_id=label.feature_row_id,
        pair_id=label.pair_id,
        timeframe=label.timeframe,
        timestamp=label.timestamp,
        feature_hash=label.feature_hash,
        label_name=label.label_name,
        label_value=dict(label.label_value_json),
        label_hash=label.label_hash,
        decision_time=label.decision_time,
        observed_at=label.observed_at,
        metadata=dict(label.metadata_json),
        created_at=label.created_at,
    )


def _prediction_record_from_model(prediction: ModelPrediction) -> ModelPredictionRecord:
    return ModelPredictionRecord(
        id=prediction.id,
        model_experiment_id=prediction.model_experiment_id,
        dataset_id=prediction.dataset_id,
        feature_set_id=prediction.feature_set_id,
        split_definition_id=prediction.split_definition_id,
        feature_row_id=prediction.feature_row_id,
        pair_id=prediction.pair_id,
        timeframe=prediction.timeframe,
        timestamp=prediction.timestamp,
        feature_hash=prediction.feature_hash,
        prediction_value=dict(prediction.prediction_value_json),
        confidence=prediction.confidence,
        decision_time=prediction.decision_time,
        feature_row_decision_time=prediction.feature_row_decision_time,
        prediction_hash=prediction.prediction_hash,
        lineage=dict(prediction.lineage_json),
        created_at=prediction.created_at,
    )


def _normalize_name(name: str, *, field_name: str, max_len: int = 128) -> str:
    normalized = name.strip()
    if not normalized:
        raise SplitValidationError(f"{field_name} must not be empty")
    if len(normalized) > max_len:
        raise SplitValidationError(f"{field_name} must be at most {max_len} characters")
    return normalized


def _normalize_hash(value: str, *, field_name: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise SplitValidationError(f"{field_name} must be a SHA-256 hex digest")
    return normalized


def _normalize_choice(value: str, allowed: Sequence[str], *, field_name: str) -> str:
    normalized = value.strip().lower()
    if normalized not in allowed:
        allowed_values = ", ".join(allowed)
        raise SplitValidationError(f"{field_name} must be one of: {allowed_values}")
    return normalized


def _normalize_window_index(value: int) -> int:
    if isinstance(value, bool) or value < 0:
        raise SplitValidationError("window_index must be nonnegative")
    return value


def _normalize_optional_utc(value: datetime | None, *, field_name: str) -> datetime | None:
    if value is None:
        return None
    return require_utc(value, field_name=field_name)


def _normalize_confidence(value: Decimal) -> Decimal:
    normalized = _normalize_decimal(value, field_name="confidence")
    if normalized < Decimal("0") or normalized > Decimal("1"):
        raise SplitValidationError("confidence must be between 0 and 1")
    return normalized


def _normalize_decimal(value: Any, *, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise SplitValidationError(f"{field_name} must be numeric")
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise SplitValidationError(f"{field_name} must be numeric") from exc
    if not normalized.is_finite():
        raise SplitValidationError(f"{field_name} must be finite")
    return normalized


def _normalize_metric_path(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise SplitValidationError("metric_path must not be empty")
    if any(not part.strip() for part in normalized.split(".")):
        raise SplitValidationError("metric_path must contain non-empty path segments")
    return normalized


def _metric_value_at_path(metrics: Mapping[str, Any], metric_path: str) -> Any:
    current: Any = metrics
    for part in metric_path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _validate_positive_limit(limit: int) -> None:
    if isinstance(limit, bool) or limit < 1:
        raise ValueError("limit must be positive")


def _validate_optional_positive_id(value: int | None, *, field_name: str) -> None:
    if value is not None and (isinstance(value, bool) or value < 1):
        raise ValueError(f"{field_name} must be positive")


def _window_json(window: NormalizedSplitWindow) -> dict[str, Any]:
    return {
        "window_index": window.window_index,
        "split_name": window.split_name,
        "start": window.start,
        "end": window.end,
        "decision_time": window.decision_time,
    }


def _json_copy(value: dict[str, Any], *, field_name: str) -> dict[str, Any]:
    try:
        copied = json.loads(json.dumps(value, sort_keys=True, default=_json_default))
        return cast(dict[str, Any], copied)
    except (TypeError, ValueError) as exc:
        raise SplitValidationError(f"{field_name} must be JSON serializable") from exc


def _sha256_json(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")
