"""Deterministic candle-derived feature contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from trading.data.market import NormalizedCandle, require_utc

DEFAULT_FEATURE_CODE_VERSION = "candle_features_v1"


class FeatureMaterializationError(ValueError):
    """Raised when a feature set cannot be materialized deterministically."""


class FeatureSetLeakageError(FeatureMaterializationError):
    """Raised when input data is not available at the requested decision time."""


class InsufficientLookbackError(FeatureMaterializationError):
    """Raised when there are not enough historical candles for the configured features."""


@dataclass(frozen=True)
class MaterializedFeatureRow:
    timestamp: datetime
    decision_time: datetime
    available_at: datetime
    features: dict[str, str]
    feature_hash: str


def normalize_feature_parameters(parameters: Mapping[str, Any]) -> dict[str, int]:
    allowed = {"lookback"}
    extra = set(parameters) - allowed
    if extra:
        raise FeatureMaterializationError(f"unsupported feature parameters: {sorted(extra)}")

    lookback = parameters.get("lookback", 3)
    if isinstance(lookback, bool) or not isinstance(lookback, int):
        raise FeatureMaterializationError("lookback must be an integer")
    if lookback < 2:
        raise FeatureMaterializationError("lookback must be at least 2")
    if lookback > 200:
        raise FeatureMaterializationError("lookback must be at most 200")
    return {"lookback": lookback}


def feature_names_for_parameters(parameters: Mapping[str, Any]) -> tuple[str, ...]:
    normalized = normalize_feature_parameters(parameters)
    lookback = normalized["lookback"]
    return (
        "close_return_1",
        f"close_sma_{lookback}",
        f"volume_sma_{lookback}",
    )


def deterministic_parameter_hash(parameters: Mapping[str, Any]) -> str:
    return _sha256_json({"parameters": normalize_feature_parameters(parameters)})


def deterministic_feature_set_hash(
    *,
    dataset_id: int,
    dataset_hash: str,
    name: str,
    code_version: str,
    parameters: Mapping[str, Any],
    rows: Sequence[MaterializedFeatureRow],
) -> str:
    return _sha256_json(
        {
            "dataset_id": dataset_id,
            "dataset_hash": dataset_hash,
            "name": name,
            "code_version": code_version,
            "parameters": normalize_feature_parameters(parameters),
            "row_hashes": [row.feature_hash for row in rows],
        }
    )


def materialize_candle_features(
    *,
    candles: Sequence[NormalizedCandle],
    decision_time: datetime,
    dataset_id: int,
    dataset_hash: str,
    code_version: str,
    parameters: Mapping[str, Any],
) -> tuple[MaterializedFeatureRow, ...]:
    parsed_decision_time = require_utc(decision_time, field_name="decision_time")
    normalized_parameters = normalize_feature_parameters(parameters)
    lookback = normalized_parameters["lookback"]
    ordered = tuple(sorted(candles, key=lambda candle: candle.timestamp))
    if len(ordered) < lookback:
        raise InsufficientLookbackError("not enough candles for configured lookback")

    parameter_hash = deterministic_parameter_hash(normalized_parameters)
    rows: list[MaterializedFeatureRow] = []
    for index in range(lookback - 1, len(ordered)):
        current = ordered[index]
        previous = ordered[index - 1]
        window = ordered[index - lookback + 1 : index + 1]
        available_at = max(candle.available_at for candle in window)
        if available_at > parsed_decision_time:
            raise FeatureSetLeakageError("feature window includes data after decision_time")
        if previous.close == 0:
            raise FeatureMaterializationError("close_return_1 cannot divide by zero")

        features = {
            "close_return_1": str((current.close - previous.close) / previous.close),
            f"close_sma_{lookback}": str(_mean(candle.close for candle in window)),
            f"volume_sma_{lookback}": str(_mean(candle.volume for candle in window)),
        }
        feature_hash = _sha256_json(
            {
                "dataset_id": dataset_id,
                "dataset_hash": dataset_hash,
                "code_version": code_version,
                "parameter_hash": parameter_hash,
                "timestamp": current.timestamp,
                "decision_time": parsed_decision_time,
                "available_at": available_at,
                "features": features,
            }
        )
        rows.append(
            MaterializedFeatureRow(
                timestamp=current.timestamp,
                decision_time=parsed_decision_time,
                available_at=available_at,
                features=features,
                feature_hash=feature_hash,
            )
        )
    return tuple(rows)


def _mean(values: Iterable[Decimal]) -> Decimal:
    materialized = tuple(values)
    if not materialized:
        raise FeatureMaterializationError("cannot average an empty sequence")
    return sum(materialized, Decimal("0")) / Decimal(len(materialized))


def _sha256_json(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_default(value: object) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")
