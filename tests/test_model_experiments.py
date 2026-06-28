from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trading.services.model_experiments import (
    SplitValidationError,
    SplitWindowCreateRequest,
    _normalize_windows,
    _validate_window_shape,
    deterministic_experiment_hash,
    deterministic_model_parameter_hash,
    deterministic_split_hash,
)


def window(
    index: int,
    split_name: str,
    start_minute: int,
    end_minute: int,
    *,
    decision_hour: int = 1,
) -> SplitWindowCreateRequest:
    return SplitWindowCreateRequest(
        window_index=index,
        split_name=split_name,
        start=datetime(2026, 1, 1, 0, start_minute, tzinfo=UTC),
        end=datetime(2026, 1, 1, 0, end_minute, tzinfo=UTC),
        decision_time=datetime(2026, 1, 1, decision_hour, tzinfo=UTC),
    )


def holdout_windows() -> tuple[SplitWindowCreateRequest, ...]:
    return (
        window(0, "train", 1, 2),
        window(0, "validation", 2, 3),
        window(0, "test", 3, 4),
    )


def test_split_hash_and_model_parameter_hash_are_deterministic() -> None:
    normalized = _normalize_windows(holdout_windows())

    split_hash = deterministic_split_hash(
        dataset_id=1,
        feature_set_id=2,
        name="holdout-v1",
        split_type="holdout",
        config={"seed": 7},
        windows=normalized,
    )
    repeated = deterministic_split_hash(
        dataset_id=1,
        feature_set_id=2,
        name="holdout-v1",
        split_type="holdout",
        config={"seed": 7},
        windows=normalized,
    )

    assert split_hash == repeated
    assert len(split_hash) == 64
    assert deterministic_model_parameter_hash({"alpha": 1, "layers": [8, 4]}) == (
        deterministic_model_parameter_hash({"layers": [8, 4], "alpha": 1})
    )


def test_experiment_hash_includes_lineage_and_metrics() -> None:
    first = deterministic_experiment_hash(
        dataset_id=1,
        feature_set_id=2,
        split_definition_id=3,
        split_hash="s" * 64,
        name="baseline",
        model_name="logistic_regression",
        code_version="model_v1",
        parameters={"alpha": 1},
        metrics={"auc": "0.71"},
        status="succeeded",
    )
    second = deterministic_experiment_hash(
        dataset_id=1,
        feature_set_id=2,
        split_definition_id=3,
        split_hash="s" * 64,
        name="baseline",
        model_name="logistic_regression",
        code_version="model_v1",
        parameters={"alpha": 1},
        metrics={"auc": "0.72"},
        status="succeeded",
    )

    assert len(first) == 64
    assert first != second


def test_split_validation_accepts_holdout_and_walk_forward_shapes() -> None:
    holdout = _normalize_windows(holdout_windows())
    walk_forward = _normalize_windows(
        (
            *holdout_windows(),
            window(1, "train", 4, 5),
            window(1, "validation", 5, 6),
            window(1, "test", 6, 7),
        )
    )

    _validate_window_shape("holdout", holdout)
    _validate_window_shape("walk_forward", walk_forward)


def test_split_validation_rejects_missing_or_leaking_windows() -> None:
    with pytest.raises(SplitValidationError, match="single window_index"):
        _validate_window_shape(
            "holdout",
            _normalize_windows((*holdout_windows(), window(1, "train", 4, 5))),
        )
    with pytest.raises(SplitValidationError, match="must include"):
        _validate_window_shape(
            "walk_forward",
            _normalize_windows((window(0, "train", 1, 2), window(0, "test", 3, 4))),
        )
    with pytest.raises(SplitValidationError, match="decision_time"):
        _normalize_windows((window(0, "train", 1, 2, decision_hour=0),))
    with pytest.raises(SplitValidationError, match="duplicate"):
        _normalize_windows((window(0, "train", 1, 2), window(0, "train", 2, 3)))
