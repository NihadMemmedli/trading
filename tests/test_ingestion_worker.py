from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from trading.data.market import IngestionStatus, OhlcvRequest, RawOhlcvBatch
from trading.services.ingestion import DuplicateCandleError
from trading.services.ingestion_worker import OhlcvIngestionWorker


class FakeAdapter:
    def __init__(self, batch: RawOhlcvBatch) -> None:
        self.batch = batch
        self.requests: list[OhlcvRequest] = []

    def fetch_ohlcv(self, request: OhlcvRequest) -> RawOhlcvBatch:
        self.requests.append(request)
        return self.batch


class FakeService:
    def __init__(self, *, insert_error: Exception | None = None) -> None:
        self.run = SimpleNamespace(
            id=uuid.UUID("00000000-0000-4000-8000-000000000010"),
            exchange="binance",
            symbol="BTC/USDT",
            timeframe="1m",
            requested_since=None,
            requested_until=None,
            requested_limit=2,
        )
        self.insert_error = insert_error
        self.succeeded: dict[str, int] | None = None
        self.failed: str | None = None
        self.datasets: list[str] = []

    def claim_next_pending_run(self) -> SimpleNamespace:
        return self.run

    def persist_raw_artifact(self, *, run_id: uuid.UUID, archive) -> SimpleNamespace:  # noqa: ANN001
        assert run_id == self.run.id
        return SimpleNamespace(id=1, row_count=archive.row_count)

    def insert_candles(self, candles) -> int:  # noqa: ANN001
        if self.insert_error is not None:
            raise self.insert_error
        return len(list(candles))

    def persist_dataset(
        self,
        *,
        name: str,
        dataset_hash: str,
        decision_time: datetime,
        artifact_id: int,
    ) -> SimpleNamespace:
        self.datasets.append(name)
        assert len(dataset_hash) == 64
        assert decision_time == datetime(2026, 6, 1, 0, 2, tzinfo=UTC)
        assert artifact_id == 1
        return SimpleNamespace(id=1)

    def mark_run_succeeded(
        self,
        run_id: uuid.UUID,
        *,
        rows_raw: int,
        rows_normalized: int,
    ) -> SimpleNamespace:
        assert run_id == self.run.id
        self.succeeded = {"rows_raw": rows_raw, "rows_normalized": rows_normalized}
        return self.run

    def mark_run_failed(self, run_id: uuid.UUID, *, error_message: str) -> SimpleNamespace:
        assert run_id == self.run.id
        self.failed = error_message
        return self.run


def raw_batch() -> RawOhlcvBatch:
    return RawOhlcvBatch(
        exchange="binance",
        symbol="BTC/USDT",
        timeframe="1m",
        fetched_at=datetime(2026, 6, 1, 0, 2, tzinfo=UTC),
        rows=[
            ["2026-06-01T00:00:00Z", "100", "110", "90", "105", "1"],
            ["2026-06-01T00:01:00Z", "105", "115", "95", "110", "2"],
        ],
    )


def test_worker_processes_claimed_run_with_public_adapter(tmp_path) -> None:  # noqa: ANN001
    service = FakeService()
    adapter = FakeAdapter(raw_batch())
    worker = OhlcvIngestionWorker(service=service, adapter=adapter, archive_root=tmp_path)

    result = worker.process_next_pending_run()

    assert result is not None
    assert result.status == IngestionStatus.SUCCEEDED
    assert result.rows_raw == 2
    assert result.rows_normalized == 2
    assert service.succeeded == {"rows_raw": 2, "rows_normalized": 2}
    assert service.datasets == ["binance:BTC/USDT:1m"]
    assert adapter.requests[0].limit == 2
    assert list(tmp_path.rglob("*.parquet"))


def test_worker_marks_run_failed_on_duplicate_candles(tmp_path) -> None:  # noqa: ANN001
    service = FakeService(insert_error=DuplicateCandleError("duplicate candle key"))
    worker = OhlcvIngestionWorker(
        service=service,
        adapter=FakeAdapter(raw_batch()),
        archive_root=tmp_path,
    )

    result = worker.process_next_pending_run()

    assert result is not None
    assert result.status == IngestionStatus.FAILED
    assert result.error_message is not None
    assert "DuplicateCandleError" in result.error_message
    assert service.failed == result.error_message
    assert service.succeeded is None
