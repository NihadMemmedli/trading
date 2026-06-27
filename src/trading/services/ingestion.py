"""OHLCV ingestion service and persistence operations."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from trading.data.archive import RawArchiveResult
from trading.data.market import IngestionStatus, NormalizedCandle, OhlcvRequest, utc_now
from trading.db.models import (
    Asset,
    Candle,
    Dataset,
    Exchange,
    IngestionRun,
    RawArtifact,
    TradingPair,
)
from trading.db.session import session_scope


class IngestionNotFoundError(LookupError):
    """Raised when an ingestion run cannot be found."""


class DuplicateCandleError(ValueError):
    """Raised when duplicate candle keys are inserted."""


@dataclass(frozen=True)
class PersistedDataset:
    dataset_hash: str
    row_count: int


class IngestionService:
    """Coordinates run metadata and public OHLCV persistence."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_ohlcv_run(self, request: OhlcvRequest) -> IngestionRun:
        with session_scope(self._session_factory) as session:
            run = IngestionRun(
                exchange=request.exchange,
                symbol=request.symbol,
                timeframe=request.timeframe,
                status=IngestionStatus.PENDING.value,
                requested_since=request.since,
                requested_until=request.until,
                requested_limit=request.limit,
                rows_raw=0,
                rows_normalized=0,
            )
            session.add(run)
            session.flush()
            session.refresh(run)
            return run

    def get_run(self, run_id: uuid.UUID) -> IngestionRun:
        with session_scope(self._session_factory) as session:
            run = session.get(IngestionRun, run_id)
            if run is None:
                raise IngestionNotFoundError(str(run_id))
            session.expunge(run)
            return run

    def list_runs(self, *, limit: int = 50) -> list[IngestionRun]:
        with session_scope(self._session_factory) as session:
            result = session.execute(
                select(IngestionRun).order_by(IngestionRun.created_at.desc()).limit(limit)
            )
            runs = list(result.scalars().all())
            for run in runs:
                session.expunge(run)
            return runs

    def claim_next_pending_run(self) -> IngestionRun | None:
        """Atomically claim the oldest pending run for a worker."""

        with session_scope(self._session_factory) as session:
            run = session.execute(
                select(IngestionRun)
                .where(IngestionRun.status == IngestionStatus.PENDING.value)
                .order_by(IngestionRun.created_at, IngestionRun.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            ).scalar_one_or_none()
            if run is None:
                return None

            run.status = IngestionStatus.RUNNING.value
            run.started_at = utc_now()
            run.completed_at = None
            run.error_message = None
            session.flush()
            session.refresh(run)
            session.expunge(run)
            return run

    def mark_run_succeeded(
        self,
        run_id: uuid.UUID,
        *,
        rows_raw: int,
        rows_normalized: int,
    ) -> IngestionRun:
        with session_scope(self._session_factory) as session:
            run = session.get(IngestionRun, run_id)
            if run is None:
                raise IngestionNotFoundError(str(run_id))

            now = utc_now()
            run.status = IngestionStatus.SUCCEEDED.value
            run.completed_at = now
            run.error_message = None
            run.rows_raw = rows_raw
            run.rows_normalized = rows_normalized
            session.flush()
            session.refresh(run)
            session.expunge(run)
            return run

    def mark_run_failed(self, run_id: uuid.UUID, *, error_message: str) -> IngestionRun:
        with session_scope(self._session_factory) as session:
            run = session.get(IngestionRun, run_id)
            if run is None:
                raise IngestionNotFoundError(str(run_id))

            run.status = IngestionStatus.FAILED.value
            run.completed_at = utc_now()
            run.error_message = error_message[:2000]
            session.flush()
            session.refresh(run)
            session.expunge(run)
            return run

    def persist_raw_artifact(
        self, *, run_id: uuid.UUID | None, archive: RawArchiveResult
    ) -> RawArtifact:
        with session_scope(self._session_factory) as session:
            artifact = RawArtifact(
                run_id=run_id,
                uri=archive.uri,
                checksum=archive.checksum,
                byte_size=archive.byte_size,
                row_count=archive.row_count,
                schema_version=archive.schema_version,
            )
            session.add(artifact)
            session.flush()
            session.refresh(artifact)
            session.expunge(artifact)
            return artifact

    def insert_candles(self, candles: Iterable[NormalizedCandle]) -> int:
        materialized = list(candles)
        if not materialized:
            return 0

        with session_scope(self._session_factory) as session:
            try:
                for candle in materialized:
                    pair = self._get_or_create_pair(session, candle.exchange, candle.symbol)
                    session.add(
                        Candle(
                            pair_id=pair.id,
                            timeframe=candle.timeframe,
                            timestamp=candle.timestamp,
                            source=candle.exchange,
                            open=candle.open,
                            high=candle.high,
                            low=candle.low,
                            close=candle.close,
                            volume=candle.volume,
                            available_at=candle.available_at,
                            raw_checksum=candle.raw_checksum,
                            quality_flags=candle.quality_flags,
                        )
                    )
                session.flush()
            except IntegrityError as exc:
                raise DuplicateCandleError("duplicate candle key") from exc
        return len(materialized)

    def point_in_time_candles(
        self,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        decision_time: datetime,
    ) -> list[Candle]:
        with session_scope(self._session_factory) as session:
            pair = self._get_or_create_pair(session, exchange, symbol)
            query: Select[tuple[Candle]] = (
                select(Candle)
                .where(
                    Candle.pair_id == pair.id,
                    Candle.timeframe == timeframe,
                    Candle.available_at <= decision_time,
                )
                .order_by(Candle.timestamp)
            )
            candles = list(session.execute(query).scalars().all())
            for candle in candles:
                session.expunge(candle)
            return candles

    def persist_dataset(
        self,
        *,
        name: str,
        dataset_hash: str,
        decision_time: datetime,
        artifact_id: int | None,
    ) -> Dataset:
        with session_scope(self._session_factory) as session:
            existing = session.execute(
                select(Dataset).where(Dataset.name == name, Dataset.dataset_hash == dataset_hash)
            ).scalar_one_or_none()
            if existing is not None:
                session.expunge(existing)
                return existing
            dataset = Dataset(
                name=name,
                dataset_hash=dataset_hash,
                decision_time=decision_time,
                artifact_id=artifact_id,
            )
            session.add(dataset)
            session.flush()
            session.refresh(dataset)
            session.expunge(dataset)
            return dataset

    def _get_or_create_pair(self, session: Session, exchange_name: str, symbol: str) -> TradingPair:
        exchange = self._get_or_create_exchange(session, exchange_name)
        base_symbol, quote_symbol = symbol.split("/", maxsplit=1)
        base = self._get_or_create_asset(session, base_symbol)
        quote = self._get_or_create_asset(session, quote_symbol)
        pair = session.execute(
            select(TradingPair).where(
                TradingPair.exchange_id == exchange.id,
                TradingPair.symbol == symbol,
                TradingPair.market_type == "spot",
            )
        ).scalar_one_or_none()
        if pair is not None:
            return pair

        pair = TradingPair(
            exchange_id=exchange.id,
            base_asset_id=base.id,
            quote_asset_id=quote.id,
            symbol=symbol,
            market_type="spot",
            active=True,
        )
        session.add(pair)
        session.flush()
        return pair

    def _get_or_create_exchange(self, session: Session, name: str) -> Exchange:
        exchange = session.execute(
            select(Exchange).where(Exchange.name == name)
        ).scalar_one_or_none()
        if exchange is not None:
            return exchange
        exchange = Exchange(name=name, market_type="spot")
        session.add(exchange)
        session.flush()
        return exchange

    def _get_or_create_asset(self, session: Session, symbol: str) -> Asset:
        asset = session.execute(select(Asset).where(Asset.symbol == symbol)).scalar_one_or_none()
        if asset is not None:
            return asset
        asset = Asset(symbol=symbol)
        session.add(asset)
        session.flush()
        return asset
