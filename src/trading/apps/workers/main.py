# ruff: noqa: E402
"""Worker entrypoint for background ingestion jobs."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

src_path = Path(__file__).resolve().parents[3]
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from trading.core.settings import Settings, load_settings
from trading.data.adapters import PublicMarketDataAdapter
from trading.data.market import IngestionStatus
from trading.db.session import create_db_engine, create_session_factory
from trading.services.ingestion import IngestionService
from trading.services.ingestion_worker import OhlcvIngestionWorker


def build_worker(settings: Settings, *, archive_root: Path | None = None) -> OhlcvIngestionWorker:
    engine = create_db_engine(settings)
    service = IngestionService(create_session_factory(engine))
    adapter = PublicMarketDataAdapter("binance")
    return OhlcvIngestionWorker(
        service=service,
        adapter=adapter,
        archive_root=archive_root or Path(settings.RAW_DATA_DIR),
    )


def run_once(worker: OhlcvIngestionWorker) -> int:
    result = worker.process_next_pending_run()
    if result is None:
        print(json.dumps({"processed": False}, sort_keys=True))
        return 0

    print(
        json.dumps(
            {
                "processed": True,
                "run_id": str(result.run_id),
                "status": result.status.value,
                "rows_raw": result.rows_raw,
                "rows_normalized": result.rows_normalized,
                "error_message": result.error_message,
            },
            sort_keys=True,
        )
    )
    return 1 if result.status == IngestionStatus.FAILED else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Process public OHLCV ingestion runs.")
    parser.add_argument("--once", action="store_true", help="Process at most one pending run.")
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--archive-root", type=Path, default=None)
    args = parser.parse_args()

    worker = build_worker(load_settings(), archive_root=args.archive_root)

    if args.once:
        raise SystemExit(run_once(worker))

    while True:
        run_once(worker)
        time.sleep(args.poll_interval)


if __name__ == "__main__":
    main()
