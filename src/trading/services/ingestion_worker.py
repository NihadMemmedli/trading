"""Background OHLCV ingestion worker orchestration."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from trading.data.adapters import PublicOhlcvAdapter
from trading.data.archive import write_raw_parquet
from trading.data.market import IngestionStatus, OhlcvRequest
from trading.data.quality import deterministic_dataset_hash, normalize_ohlcv_batch
from trading.db.models import IngestionRun
from trading.services.ingestion import IngestionService


@dataclass(frozen=True)
class WorkerRunResult:
    run_id: uuid.UUID
    status: IngestionStatus
    rows_raw: int = 0
    rows_normalized: int = 0
    error_message: str | None = None


class OhlcvIngestionWorker:
    """Processes pending public OHLCV ingestion runs."""

    def __init__(
        self,
        *,
        service: IngestionService,
        adapter: PublicOhlcvAdapter,
        archive_root: Path,
    ) -> None:
        self._service = service
        self._adapter = adapter
        self._archive_root = archive_root

    def process_next_pending_run(self) -> WorkerRunResult | None:
        run = self._service.claim_next_pending_run()
        if run is None:
            return None
        return self.process_claimed_run(run)

    def process_claimed_run(self, run: IngestionRun) -> WorkerRunResult:
        try:
            request = OhlcvRequest(
                exchange=run.exchange,
                symbol=run.symbol,
                timeframe=run.timeframe,
                since=run.requested_since,
                until=run.requested_until,
                limit=run.requested_limit,
            )
            batch = self._adapter.fetch_ohlcv(request)
            archive = write_raw_parquet(batch, self._archive_root)
            candles = normalize_ohlcv_batch(
                batch,
                raw_checksum=archive.checksum,
                now=batch.fetched_at,
            )
            artifact = self._service.persist_raw_artifact(run_id=run.id, archive=archive)
            inserted_rows = self._service.insert_candles(candles)
            dataset_hash = deterministic_dataset_hash(candles)
            self._service.persist_dataset(
                name=f"{run.exchange}:{run.symbol}:{run.timeframe}",
                dataset_hash=dataset_hash,
                decision_time=batch.fetched_at,
                artifact_id=artifact.id,
            )
            self._service.mark_run_succeeded(
                run.id,
                rows_raw=archive.row_count,
                rows_normalized=inserted_rows,
            )
            return WorkerRunResult(
                run_id=run.id,
                status=IngestionStatus.SUCCEEDED,
                rows_raw=archive.row_count,
                rows_normalized=inserted_rows,
            )
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            self._service.mark_run_failed(run.id, error_message=message)
            return WorkerRunResult(
                run_id=run.id,
                status=IngestionStatus.FAILED,
                error_message=message,
            )
