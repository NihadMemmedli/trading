from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq

from trading.data.archive import ARCHIVE_SCHEMA_VERSION, read_raw_parquet, write_raw_parquet
from trading.data.market import RawOhlcvBatch


def test_raw_parquet_archive_schema_checksum_and_replay(tmp_path: Path) -> None:
    batch = RawOhlcvBatch(
        exchange="binance",
        symbol="BTC/USDT",
        timeframe="1m",
        fetched_at=datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
        rows=[
            ["2026-01-01T00:00:00Z", "42000", "42010", "41990", "42005", "12.5"],
            ["2026-01-01T00:01:00Z", "42005", "42020", "42000", "42015", "8.75"],
        ],
    )

    result = write_raw_parquet(batch, tmp_path)

    path = Path(result.uri)
    assert path.exists()
    assert "exchange=binance" in result.uri
    assert "symbol=BTC_USDT" in result.uri
    assert result.schema_version == ARCHIVE_SCHEMA_VERSION
    assert len(result.checksum) == 64
    assert result.byte_size == path.stat().st_size

    table = pq.ParquetFile(path).read()
    assert table.schema.names == [
        "exchange",
        "symbol",
        "timeframe",
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "fetched_at",
    ]

    replayed = read_raw_parquet(path)
    assert replayed.symbol == batch.symbol
    assert replayed.timeframe == batch.timeframe
    assert replayed.rows[0][1:] == batch.rows[0][1:]
