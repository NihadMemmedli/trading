from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trading.services.model_experiments import (
    BaselineEvaluationWindow,
    BaselineFeatureRow,
    SplitValidationError,
    SplitWindowCreateRequest,
    _normalize_windows,
    _validate_window_shape,
    deterministic_experiment_hash,
    deterministic_model_parameter_hash,
    deterministic_split_hash,
    evaluate_previous_return_direction_baseline,
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


def baseline_row(row_id: int, minute: int, close_return_1: str) -> BaselineFeatureRow:
    return BaselineFeatureRow(
        id=row_id,
        pair_id=1,
        timeframe="1m",
        timestamp=datetime(2026, 1, 1, 0, minute, tzinfo=UTC),
        features={"close_return_1": close_return_1},
    )


def baseline_window(
    split_name: str,
    rows: tuple[BaselineFeatureRow, ...],
) -> BaselineEvaluationWindow:
    return BaselineEvaluationWindow(
        window_index=0,
        split_name=split_name,
        start=datetime(2026, 1, 1, tzinfo=UTC),
        end=datetime(2026, 1, 1, 0, 10, tzinfo=UTC),
        decision_time=datetime(2026, 1, 1, 1, tzinfo=UTC),
        rows=rows,
    )


def baseline_windows(
    rows: tuple[BaselineFeatureRow, ...],
) -> tuple[BaselineEvaluationWindow, ...]:
    return tuple(
        baseline_window(split_name, rows) for split_name in ("train", "validation", "test")
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


def test_previous_return_direction_baseline_metrics_are_deterministic() -> None:
    metrics = evaluate_previous_return_direction_baseline(
        baseline_windows(
            (
                baseline_row(1, 1, "0.10"),
                baseline_row(2, 2, "-0.05"),
                baseline_row(3, 3, "-0.02"),
                baseline_row(4, 4, "0.03"),
            )
        )
    )

    assert metrics["by_split"]["train"] == {
        "observations": 3,
        "accuracy": 0.333333333333,
        "true_positives": 0,
        "false_positives": 1,
        "true_negatives": 1,
        "false_negatives": 1,
        "positive_prediction_rate": 0.333333333333,
        "target_positive_rate": 0.333333333333,
    }
    assert metrics["overall"]["observations"] == 9
    assert metrics["overall"]["false_positives"] == 3
    assert len(metrics["windows"]) == 3


def test_previous_return_direction_baseline_skips_first_row_per_window() -> None:
    metrics = evaluate_previous_return_direction_baseline(
        baseline_windows((baseline_row(1, 1, "0.10"), baseline_row(2, 2, "0.20")))
    )

    assert metrics["overall"]["observations"] == 3
    assert metrics["overall"]["true_positives"] == 3


def test_previous_return_direction_baseline_rejects_zero_observation_split() -> None:
    with pytest.raises(SplitValidationError, match="train window 0 has no baseline observations"):
        evaluate_previous_return_direction_baseline(
            (
                baseline_window("train", (baseline_row(1, 1, "0.10"),)),
                baseline_window(
                    "validation",
                    (baseline_row(2, 2, "0.10"), baseline_row(3, 3, "0.20")),
                ),
                baseline_window("test", (baseline_row(4, 4, "0.10"), baseline_row(5, 5, "0.20"))),
            )
        )


def test_previous_return_direction_baseline_rejects_missing_close_return() -> None:
    bad_row = BaselineFeatureRow(
        id=2,
        pair_id=1,
        timeframe="1m",
        timestamp=datetime(2026, 1, 1, 0, 2, tzinfo=UTC),
        features={},
    )

    with pytest.raises(SplitValidationError, match="missing close_return_1"):
        evaluate_previous_return_direction_baseline(
            baseline_windows((baseline_row(1, 1, "0.10"), bad_row))
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
