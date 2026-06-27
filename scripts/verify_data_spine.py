# ruff: noqa: E402
"""Verify fixture raw data through archive, normalization, DB insert, and PIT read."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

src_path = Path(__file__).resolve().parents[1] / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from trading.core.settings import Settings
from trading.data.archive import write_raw_parquet
from trading.data.market import parse_timestamp
from trading.data.offline import OhlcvFixtureSpec, load_raw_ohlcv_jsonl
from trading.data.quality import deterministic_dataset_hash, normalize_ohlcv_batch
from trading.db.session import create_db_engine, create_session_factory
from trading.services.ingestion import DuplicateCandleError, IngestionService


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--timeframe", required=True)
    parser.add_argument("--decision-time", required=True)
    args = parser.parse_args()

    decision_time = parse_timestamp(args.decision_time, field_name="decision_time")
    batch = load_raw_ohlcv_jsonl(
        OhlcvFixtureSpec(
            path=args.dataset,
            symbol=args.symbol,
            timeframe=args.timeframe,
        ),
        fetched_at=args.decision_time,
    )

    with tempfile.TemporaryDirectory(prefix="trading-raw-") as directory:
        archive = write_raw_parquet(batch, Path(directory))
        candles = normalize_ohlcv_batch(batch, raw_checksum=archive.checksum, now=decision_time)

        service = IngestionService(create_session_factory(create_db_engine(Settings())))
        artifact = service.persist_raw_artifact(run_id=None, archive=archive)
        try:
            inserted = service.insert_candles(candles)
        except DuplicateCandleError:
            inserted = 0

        pit_candles = service.point_in_time_candles(
            exchange="binance",
            symbol=args.symbol,
            timeframe=args.timeframe,
            decision_time=decision_time,
        )
        replay_candles = [
            candle.model_copy()
            for candle in candles
            if any(stored.timestamp == candle.timestamp for stored in pit_candles)
        ]
        if not replay_candles:
            raise SystemExit("point-in-time read returned no replayable fixture candles")
        dataset_hash = deterministic_dataset_hash(replay_candles)
        service.persist_dataset(
            name=f"{args.symbol}:{args.timeframe}",
            dataset_hash=dataset_hash,
            decision_time=decision_time,
            artifact_id=artifact.id,
        )

    print(
        json.dumps(
            {
                "artifact_checksum": archive.checksum,
                "dataset_hash": dataset_hash,
                "inserted_rows": inserted,
                "point_in_time_rows": len(replay_candles),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
