from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from trading.services.model_experiments import (
    BaselineEvaluationWindow,
    BaselineFeatureRow,
    SplitValidationError,
    SplitWindowCreateRequest,
    _baseline_label_value,
    _baseline_prediction_value,
    _normalize_windows,
    _validate_window_shape,
    deterministic_experiment_hash,
    deterministic_label_hash,
    deterministic_model_parameter_hash,
    deterministic_prediction_hash,
    deterministic_split_hash,
    evaluate_previous_return_direction_baseline,
    previous_return_direction_baseline_observations,
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


def test_label_and_prediction_hashes_are_deterministic() -> None:
    experiment_id = "11111111-1111-1111-1111-111111111111"
    decision_time = datetime(2026, 1, 1, 1, tzinfo=UTC)
    observed_at = datetime(2026, 1, 1, 1, 1, tzinfo=UTC)
    first_label_hash = deterministic_label_hash(
        dataset_id=1,
        feature_set_id=2,
        feature_row_id=3,
        feature_hash="a" * 64,
        label_name="forward_return_1",
        label_value={"return": "0.1", "direction": "up"},
        decision_time=decision_time,
        observed_at=observed_at,
        metadata={"horizon": "1m", "source": "test"},
    )
    second_label_hash = deterministic_label_hash(
        dataset_id=1,
        feature_set_id=2,
        feature_row_id=3,
        feature_hash="a" * 64,
        label_name="forward_return_1",
        label_value={"direction": "up", "return": "0.1"},
        decision_time=decision_time,
        observed_at=observed_at,
        metadata={"source": "test", "horizon": "1m"},
    )
    first_prediction_hash = deterministic_prediction_hash(
        model_experiment_id=experiment_id,
        dataset_id=1,
        feature_set_id=2,
        split_definition_id=4,
        feature_row_id=3,
        feature_hash="a" * 64,
        prediction_value={"score": "0.7", "direction": "up"},
        confidence="0.8",
        decision_time=decision_time,
        lineage={"code_version": "model_v1", "feature_set_hash": "f" * 64},
    )
    second_prediction_hash = deterministic_prediction_hash(
        model_experiment_id=experiment_id,
        dataset_id=1,
        feature_set_id=2,
        split_definition_id=4,
        feature_row_id=3,
        feature_hash="a" * 64,
        prediction_value={"direction": "up", "score": "0.7"},
        confidence="0.8",
        decision_time=decision_time,
        lineage={"feature_set_hash": "f" * 64, "code_version": "model_v1"},
    )

    assert first_label_hash == second_label_hash
    assert first_prediction_hash == second_prediction_hash
    assert len(first_label_hash) == 64
    assert len(first_prediction_hash) == 64


def test_feature_rows_do_not_embed_labels() -> None:
    row = baseline_row(1, 1, "0.10")

    assert "label" not in row.features
    assert "labels" not in row.features
    assert "target" not in row.features


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


def test_previous_return_direction_observations_skip_first_row_per_window() -> None:
    observation_windows = previous_return_direction_baseline_observations(
        baseline_windows(
            (
                baseline_row(1, 1, "0.10"),
                baseline_row(2, 2, "-0.05"),
                baseline_row(3, 3, "-0.02"),
            )
        )
    )

    assert [window.skipped_first_row_count for window in observation_windows] == [1, 1, 1]
    assert [len(window.observations) for window in observation_windows] == [2, 2, 2]
    first_observation = observation_windows[0].observations[0]
    assert first_observation.row.id == 2
    assert first_observation.previous_return == Decimal("0.10")
    assert first_observation.current_return == Decimal("-0.05")


def test_baseline_label_and_prediction_values_are_deterministic() -> None:
    label_value = _baseline_label_value(Decimal("-0.05"))
    prediction_value = _baseline_prediction_value(Decimal("0.10"))

    assert label_value == {
        "direction": "down",
        "positive": False,
        "return": "-0.05",
        "source_feature": "close_return_1",
    }
    assert prediction_value == {
        "direction": "up",
        "positive": True,
        "source_feature": "close_return_1",
        "source_return": "0.10",
    }
    assert _baseline_prediction_value(Decimal("0.10")) == prediction_value


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
