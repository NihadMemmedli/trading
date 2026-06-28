"""Read-only registered dataset service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, sessionmaker

from trading.db.models import BacktestRun, Dataset
from trading.db.session import session_scope


class DatasetNotFoundError(LookupError):
    """Raised when a registered dataset cannot be found."""


@dataclass(frozen=True)
class DatasetRecord:
    id: int
    name: str
    dataset_hash: str
    decision_time: datetime
    artifact_id: int | None
    created_at: datetime
    backtest_run_count: int


class DatasetService:
    """Provides read-only access to registered dataset metadata."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get_dataset(self, dataset_id: int) -> DatasetRecord:
        if dataset_id < 1:
            raise DatasetNotFoundError(str(dataset_id))

        with session_scope(self._session_factory) as session:
            row = session.execute(
                _dataset_record_query().where(Dataset.id == dataset_id)
            ).one_or_none()
            if row is None:
                raise DatasetNotFoundError(str(dataset_id))
            return _record_from_row(*row)

    def list_datasets(self, *, limit: int = 50) -> list[DatasetRecord]:
        if limit < 1:
            raise ValueError("limit must be positive")

        with session_scope(self._session_factory) as session:
            rows = session.execute(
                _dataset_record_query()
                .order_by(Dataset.created_at.desc(), Dataset.id.desc())
                .limit(limit)
            ).all()
            return [_record_from_row(*row) for row in rows]


def _dataset_record_query() -> Select[tuple[Dataset, int]]:
    return (
        select(Dataset, func.count(BacktestRun.id).label("backtest_run_count"))
        .outerjoin(BacktestRun, BacktestRun.dataset_id == Dataset.id)
        .group_by(Dataset.id)
    )


def _record_from_row(dataset: Dataset, backtest_run_count: int) -> DatasetRecord:
    return DatasetRecord(
        id=dataset.id,
        name=dataset.name,
        dataset_hash=dataset.dataset_hash,
        decision_time=dataset.decision_time,
        artifact_id=dataset.artifact_id,
        created_at=dataset.created_at,
        backtest_run_count=int(backtest_run_count),
    )
