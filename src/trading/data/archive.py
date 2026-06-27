"""Raw public market-data Parquet archive."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from trading.data.market import RawOhlcvBatch, parse_timestamp

ARCHIVE_SCHEMA_VERSION = "ohlcv-raw-v1"


@dataclass(frozen=True)
class RawArchiveResult:
    uri: str
    checksum: str
    byte_size: int
    row_count: int
    schema_version: str


def partition_path(root: Path, batch: RawOhlcvBatch) -> Path:
    first_timestamp = parse_timestamp(batch.rows[0][0], field_name="timestamp")
    safe_symbol = batch.symbol.replace("/", "_")
    return (
        root
        / f"exchange={batch.exchange}"
        / f"symbol={safe_symbol}"
        / f"timeframe={batch.timeframe}"
        / f"year={first_timestamp.year:04d}"
        / f"month={first_timestamp.month:02d}"
    )


def build_raw_table(batch: RawOhlcvBatch) -> pa.Table:
    timestamps = [parse_timestamp(row[0], field_name="timestamp") for row in batch.rows]
    return pa.table(
        {
            "exchange": pa.array([batch.exchange] * len(batch.rows), pa.string()),
            "symbol": pa.array([batch.symbol] * len(batch.rows), pa.string()),
            "timeframe": pa.array([batch.timeframe] * len(batch.rows), pa.string()),
            "timestamp": pa.array(timestamps, pa.timestamp("ms", tz="UTC")),
            "open": pa.array([str(row[1]) for row in batch.rows], pa.string()),
            "high": pa.array([str(row[2]) for row in batch.rows], pa.string()),
            "low": pa.array([str(row[3]) for row in batch.rows], pa.string()),
            "close": pa.array([str(row[4]) for row in batch.rows], pa.string()),
            "volume": pa.array([str(row[5]) for row in batch.rows], pa.string()),
            "fetched_at": pa.array(
                [batch.fetched_at] * len(batch.rows),
                pa.timestamp("ms", tz="UTC"),
            ),
        }
    )


def write_raw_parquet(batch: RawOhlcvBatch, root: Path) -> RawArchiveResult:
    if not batch.rows:
        raise ValueError("cannot archive an empty raw OHLCV batch")

    destination_dir = partition_path(root, batch)
    destination_dir.mkdir(parents=True, exist_ok=True)
    first_timestamp = parse_timestamp(batch.rows[0][0], field_name="timestamp")
    filename = f"ohlcv_{first_timestamp.strftime('%Y%m%dT%H%M%SZ')}_{len(batch.rows)}.parquet"
    destination = destination_dir / filename

    table = build_raw_table(batch)
    pq.write_table(table, destination, compression="zstd")
    data = destination.read_bytes()
    return RawArchiveResult(
        uri=str(destination),
        checksum=hashlib.sha256(data).hexdigest(),
        byte_size=len(data),
        row_count=len(batch.rows),
        schema_version=ARCHIVE_SCHEMA_VERSION,
    )


def read_raw_parquet(path: Path) -> RawOhlcvBatch:
    table = pq.ParquetFile(path).read()
    data = table.to_pydict()
    rows = [
        [
            timestamp,
            data["open"][index],
            data["high"][index],
            data["low"][index],
            data["close"][index],
            data["volume"][index],
        ]
        for index, timestamp in enumerate(data["timestamp"])
    ]
    return RawOhlcvBatch(
        exchange=data["exchange"][0],
        symbol=data["symbol"][0],
        timeframe=data["timeframe"][0],
        rows=rows,
        fetched_at=data["fetched_at"][0],
    )
