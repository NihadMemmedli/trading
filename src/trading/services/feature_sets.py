"""Feature-set registry and point-in-time materialization service."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from trading.data.market import (
    MarketDataError,
    NormalizedCandle,
    require_utc,
    validate_symbol,
    validate_timeframe,
)
from trading.db.models import Candle, Dataset, Exchange, FeatureRow, FeatureSet, TradingPair
from trading.db.session import session_scope
from trading.features import (
    DEFAULT_FEATURE_CODE_VERSION,
    FeatureMaterializationError,
    FeatureSetLeakageError,
    deterministic_feature_set_hash,
    deterministic_parameter_hash,
    feature_names_for_parameters,
    materialize_candle_features,
    normalize_feature_parameters,
)
from trading.services.backtests import deterministic_candle_dataset_hash


class FeatureSetNotFoundError(LookupError):
    """Raised when a feature set cannot be found."""


class FeatureSetDatasetNotFoundError(LookupError):
    """Raised when a feature-set request references an unknown dataset."""


class FeatureSetDatasetNotMaterializableError(ValueError):
    """Raised when a dataset cannot be used for candle feature materialization."""


@dataclass(frozen=True)
class FeatureSetCreateRequest:
    dataset_id: int
    name: str
    parameters: Mapping[str, Any]
    code_version: str = DEFAULT_FEATURE_CODE_VERSION
    output_location: str | None = None


@dataclass(frozen=True)
class FeatureDatasetSelector:
    exchange: str
    symbol: str
    timeframe: str
    start: datetime
    end: datetime
    decision_time: datetime


@dataclass(frozen=True)
class FeatureRowRecord:
    id: int
    timestamp: datetime
    decision_time: datetime
    available_at: datetime
    features: dict[str, Any]
    feature_hash: str


@dataclass(frozen=True)
class FeatureSetRecord:
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
    rows: tuple[FeatureRowRecord, ...] = ()


class FeatureSetService:
    """Creates and reads deterministic point-in-time candle feature sets."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_feature_set(self, request: FeatureSetCreateRequest) -> FeatureSetRecord:
        normalized_name = _normalize_name(request.name)
        normalized_parameters = normalize_feature_parameters(request.parameters)
        code_version = _normalize_code_version(request.code_version)
        dataset = self._get_dataset(request.dataset_id)
        selector = _parse_feature_dataset_name(dataset.name)
        if selector.decision_time != dataset.decision_time:
            raise FeatureSetDatasetNotMaterializableError(
                "dataset decision_time does not match selector"
            )

        candles = self._load_candles(selector)
        dataset_hash = deterministic_candle_dataset_hash(candles)
        if dataset_hash != dataset.dataset_hash:
            raise FeatureSetLeakageError(
                "registered dataset hash does not match point-in-time candles"
            )

        materialized_rows = materialize_candle_features(
            candles=candles,
            decision_time=selector.decision_time,
            dataset_id=dataset.id,
            dataset_hash=dataset.dataset_hash,
            code_version=code_version,
            parameters=normalized_parameters,
        )
        feature_set_hash = deterministic_feature_set_hash(
            dataset_id=dataset.id,
            dataset_hash=dataset.dataset_hash,
            name=normalized_name,
            code_version=code_version,
            parameters=normalized_parameters,
            rows=materialized_rows,
        )
        parameter_hash = deterministic_parameter_hash(normalized_parameters)
        feature_names = list(feature_names_for_parameters(normalized_parameters))
        selector_json = _selector_json(selector)

        with session_scope(self._session_factory) as session:
            existing = _find_existing_feature_set(
                session,
                dataset_id=dataset.id,
                name=normalized_name,
                parameter_hash=parameter_hash,
                code_version=code_version,
            )
            if existing is not None:
                return _record_from_model(existing)

            pair_id = _find_pair_id(session, selector.exchange, selector.symbol)
            if pair_id is None:
                raise FeatureSetDatasetNotMaterializableError("dataset trading pair is missing")
            feature_set = FeatureSet(
                dataset_id=dataset.id,
                name=normalized_name,
                dataset_hash=dataset.dataset_hash,
                feature_set_hash=feature_set_hash,
                parameter_hash=parameter_hash,
                code_version=code_version,
                parameters_json=normalized_parameters,
                feature_names_json=feature_names,
                selector_json=selector_json,
                output_location=request.output_location,
            )
            session.add(feature_set)
            session.flush()
            session.add_all(
                FeatureRow(
                    feature_set_id=feature_set.id,
                    pair_id=pair_id,
                    timeframe=selector.timeframe,
                    timestamp=row.timestamp,
                    decision_time=row.decision_time,
                    available_at=row.available_at,
                    features_json=row.features,
                    feature_hash=row.feature_hash,
                )
                for row in materialized_rows
            )
            session.flush()
            loaded = _load_feature_set(session, feature_set.id)
            return _record_from_model(loaded)

    def get_feature_set(self, feature_set_id: int) -> FeatureSetRecord:
        if isinstance(feature_set_id, bool) or feature_set_id < 1:
            raise FeatureSetNotFoundError(str(feature_set_id))

        with session_scope(self._session_factory) as session:
            feature_set = _load_feature_set(session, feature_set_id)
            return _record_from_model(feature_set)

    def list_feature_sets(
        self,
        *,
        limit: int = 50,
        dataset_id: int | None = None,
    ) -> list[FeatureSetRecord]:
        if limit < 1:
            raise ValueError("limit must be positive")
        if dataset_id is not None and (isinstance(dataset_id, bool) or dataset_id < 1):
            raise ValueError("dataset_id must be positive")

        with session_scope(self._session_factory) as session:
            query = _feature_set_summary_query()
            if dataset_id is not None:
                query = query.where(FeatureSet.dataset_id == dataset_id)
            rows = session.execute(
                query.order_by(FeatureSet.created_at.desc(), FeatureSet.id.desc()).limit(limit)
            ).all()
            return [_record_from_summary(feature_set, row_count) for feature_set, row_count in rows]

    def _get_dataset(self, dataset_id: int) -> Dataset:
        if isinstance(dataset_id, bool) or dataset_id < 1:
            raise FeatureSetDatasetNotFoundError(str(dataset_id))

        with session_scope(self._session_factory) as session:
            dataset = session.get(Dataset, dataset_id)
            if dataset is None:
                raise FeatureSetDatasetNotFoundError(str(dataset_id))
            session.expunge(dataset)
            return dataset

    def _load_candles(self, selector: FeatureDatasetSelector) -> tuple[NormalizedCandle, ...]:
        with session_scope(self._session_factory) as session:
            rows = session.execute(
                select(Candle)
                .join(TradingPair, Candle.pair_id == TradingPair.id)
                .join(Exchange, TradingPair.exchange_id == Exchange.id)
                .where(
                    Exchange.name == selector.exchange,
                    TradingPair.symbol == selector.symbol,
                    TradingPair.market_type == "spot",
                    Candle.source == selector.exchange,
                    Candle.timeframe == selector.timeframe,
                    Candle.timestamp >= selector.start,
                    Candle.timestamp <= selector.end,
                    Candle.available_at <= selector.decision_time,
                )
                .order_by(Candle.timestamp)
            ).scalars()
            candles = tuple(
                NormalizedCandle(
                    exchange=selector.exchange,
                    symbol=selector.symbol,
                    timeframe=candle.timeframe,
                    timestamp=candle.timestamp,
                    open=candle.open,
                    high=candle.high,
                    low=candle.low,
                    close=candle.close,
                    volume=candle.volume,
                    available_at=candle.available_at,
                    raw_checksum=candle.raw_checksum,
                    quality_flags=candle.quality_flags,
                )
                for candle in rows
            )
        if not candles:
            raise MarketDataError("feature materialization requires eligible candles")
        return candles


def _find_existing_feature_set(
    session: Session,
    *,
    dataset_id: int,
    name: str,
    parameter_hash: str,
    code_version: str,
) -> FeatureSet | None:
    return session.execute(
        select(FeatureSet)
        .options(selectinload(FeatureSet.rows))
        .where(
            FeatureSet.dataset_id == dataset_id,
            FeatureSet.name == name,
            FeatureSet.parameter_hash == parameter_hash,
            FeatureSet.code_version == code_version,
        )
    ).scalar_one_or_none()


def _load_feature_set(session: Session, feature_set_id: int) -> FeatureSet:
    feature_set = session.execute(
        select(FeatureSet)
        .options(selectinload(FeatureSet.rows))
        .where(FeatureSet.id == feature_set_id)
    ).scalar_one_or_none()
    if feature_set is None:
        raise FeatureSetNotFoundError(str(feature_set_id))
    return feature_set


def _feature_set_summary_query() -> Select[tuple[FeatureSet, int]]:
    return (
        select(FeatureSet, func.count(FeatureRow.id).label("feature_row_count"))
        .outerjoin(FeatureRow, FeatureRow.feature_set_id == FeatureSet.id)
        .group_by(FeatureSet.id)
    )


def _find_pair_id(session: Session, exchange_name: str, symbol: str) -> int | None:
    return session.execute(
        select(TradingPair.id)
        .join(Exchange, TradingPair.exchange_id == Exchange.id)
        .where(
            Exchange.name == exchange_name,
            TradingPair.symbol == symbol,
            TradingPair.market_type == "spot",
        )
    ).scalar_one_or_none()


def _record_from_model(feature_set: FeatureSet) -> FeatureSetRecord:
    rows = tuple(
        FeatureRowRecord(
            id=row.id,
            timestamp=row.timestamp,
            decision_time=row.decision_time,
            available_at=row.available_at,
            features=dict(row.features_json),
            feature_hash=row.feature_hash,
        )
        for row in feature_set.rows
    )
    return FeatureSetRecord(
        id=feature_set.id,
        dataset_id=feature_set.dataset_id,
        name=feature_set.name,
        dataset_hash=feature_set.dataset_hash,
        feature_set_hash=feature_set.feature_set_hash,
        parameter_hash=feature_set.parameter_hash,
        code_version=feature_set.code_version,
        parameters=dict(feature_set.parameters_json),
        feature_names=list(feature_set.feature_names_json),
        selector=dict(feature_set.selector_json),
        output_location=feature_set.output_location,
        created_at=feature_set.created_at,
        feature_row_count=len(rows),
        rows=rows,
    )


def _record_from_summary(feature_set: FeatureSet, row_count: int) -> FeatureSetRecord:
    return FeatureSetRecord(
        id=feature_set.id,
        dataset_id=feature_set.dataset_id,
        name=feature_set.name,
        dataset_hash=feature_set.dataset_hash,
        feature_set_hash=feature_set.feature_set_hash,
        parameter_hash=feature_set.parameter_hash,
        code_version=feature_set.code_version,
        parameters=dict(feature_set.parameters_json),
        feature_names=list(feature_set.feature_names_json),
        selector=dict(feature_set.selector_json),
        output_location=feature_set.output_location,
        created_at=feature_set.created_at,
        feature_row_count=int(row_count),
        rows=(),
    )


def _normalize_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise FeatureMaterializationError("feature set name must not be empty")
    if len(normalized) > 128:
        raise FeatureMaterializationError("feature set name must be at most 128 characters")
    return normalized


def _normalize_code_version(code_version: str) -> str:
    normalized = code_version.strip()
    if not normalized:
        raise FeatureMaterializationError("code_version must not be empty")
    if len(normalized) > 64:
        raise FeatureMaterializationError("code_version must be at most 64 characters")
    return normalized


def _parse_feature_dataset_name(name: str) -> FeatureDatasetSelector:
    prefix_parts = name.split(":", 4)
    if len(prefix_parts) != 5 or prefix_parts[0] != "backtest":
        raise FeatureSetDatasetNotMaterializableError(
            "only backtest-created datasets can materialize candle features"
        )

    _, exchange, symbol, timeframe, timestamp_tail = prefix_parts
    timestamp_parts = timestamp_tail.split("Z:")
    if len(timestamp_parts) != 3 or not timestamp_parts[2].endswith("Z"):
        raise FeatureSetDatasetNotMaterializableError("dataset name is malformed")

    try:
        start = _parse_utc_iso(f"{timestamp_parts[0]}Z", "dataset start")
        end = _parse_utc_iso(f"{timestamp_parts[1]}Z", "dataset end")
        decision_time = _parse_utc_iso(timestamp_parts[2], "dataset decision_time")
    except ValueError as exc:
        raise FeatureSetDatasetNotMaterializableError("dataset name is malformed") from exc

    exchange = exchange.strip().lower()
    if exchange != "binance":
        raise FeatureSetDatasetNotMaterializableError("only binance candle datasets are supported")
    if start >= end:
        raise FeatureSetDatasetNotMaterializableError("dataset start must be earlier than end")

    return FeatureDatasetSelector(
        exchange=exchange,
        symbol=validate_symbol(symbol),
        timeframe=validate_timeframe(timeframe),
        start=start,
        end=end,
        decision_time=decision_time,
    )


def _selector_json(selector: FeatureDatasetSelector) -> dict[str, Any]:
    return {
        "exchange": selector.exchange,
        "symbol": selector.symbol,
        "timeframe": selector.timeframe,
        "start": _utc_iso(selector.start),
        "end": _utc_iso(selector.end),
        "decision_time": _utc_iso(selector.decision_time),
    }


def _parse_utc_iso(value: str, field_name: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return require_utc(parsed, field_name=field_name)


def _utc_iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
