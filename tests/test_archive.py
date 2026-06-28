from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq

from trading.data.archive import (
    ARCHIVE_SCHEMA_VERSION,
    ORDER_BOOK_ARCHIVE_SCHEMA_VERSION,
    TRADE_ARCHIVE_SCHEMA_VERSION,
    read_raw_order_book_parquet,
    read_raw_parquet,
    read_raw_trade_parquet,
    write_raw_order_book_parquet,
    write_raw_parquet,
    write_raw_trade_parquet,
)
from trading.data.market import RawOhlcvBatch, RawOrderBookBatch, RawTradeBatch


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


def test_raw_trade_parquet_archive_schema_checksum_and_replay(tmp_path: Path) -> None:
    batch = RawTradeBatch(
        exchange="binance",
        symbol="BTC/USDT",
        fetched_at=datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
        rows=[
            {
                "id": "trade-1",
                "datetime": "2026-01-01T00:00:05.000Z",
                "fee": {"currency": "USDT", "cost": "0.01"},
                "info": {"buyerOrderId": "abc"},
                "timestamp": "2026-01-01T00:00:05Z",
                "side": "buy",
                "price": "42001.10",
                "amount": "0.125",
            },
            {
                "id": "trade-2",
                "timestamp": "2026-01-01T00:00:21Z",
                "side": "sell",
                "price": "42003.20",
                "amount": "0.080",
            },
        ],
    )

    result = write_raw_trade_parquet(batch, tmp_path)

    path = Path(result.uri)
    assert path.exists()
    assert "exchange=binance" in result.uri
    assert "symbol=BTC_USDT" in result.uri
    assert "type=trades" in result.uri
    assert result.schema_version == TRADE_ARCHIVE_SCHEMA_VERSION
    assert len(result.checksum) == 64
    assert result.byte_size == path.stat().st_size

    table = pq.ParquetFile(path).read()
    assert table.schema.names == [
        "exchange",
        "symbol",
        "trade_id",
        "timestamp",
        "side",
        "price",
        "amount",
        "fetched_at",
        "raw_json",
    ]

    replayed = read_raw_trade_parquet(path)
    assert replayed.symbol == batch.symbol
    assert replayed.rows[0]["id"] == batch.rows[0]["id"]
    assert replayed.rows[0]["side"] == batch.rows[0]["side"]
    assert replayed.rows[0]["fee"] == batch.rows[0]["fee"]
    assert replayed.rows[0]["info"] == batch.rows[0]["info"]


def test_raw_order_book_parquet_archive_schema_checksum_and_replay(tmp_path: Path) -> None:
    batch = RawOrderBookBatch(
        exchange="binance",
        symbol="BTC/USDT",
        fetched_at=datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
        rows=[
            {
                "timestamp": "2026-01-01T00:00:10Z",
                "datetime": "2026-01-01T00:00:10.000Z",
                "nonce": 123,
                "bids": [["42000.00", "0.10"], ["41999.00", "0.20"]],
                "asks": [["42001.00", "0.15"], ["42002.00", "0.25"]],
                "info": {"lastUpdateId": 123},
            }
        ],
    )

    result = write_raw_order_book_parquet(batch, tmp_path)

    path = Path(result.uri)
    assert path.exists()
    assert "exchange=binance" in result.uri
    assert "symbol=BTC_USDT" in result.uri
    assert "type=order_books" in result.uri
    assert result.schema_version == ORDER_BOOK_ARCHIVE_SCHEMA_VERSION
    assert len(result.checksum) == 64
    assert result.byte_size == path.stat().st_size

    table = pq.ParquetFile(path).read()
    assert table.schema.names == [
        "exchange",
        "symbol",
        "timestamp",
        "nonce",
        "fetched_at",
        "raw_json",
    ]

    replayed = read_raw_order_book_parquet(path)
    assert replayed.symbol == batch.symbol
    assert replayed.rows[0]["nonce"] == batch.rows[0]["nonce"]
    assert replayed.rows[0]["bids"] == batch.rows[0]["bids"]
    assert replayed.rows[0]["asks"] == batch.rows[0]["asks"]
    assert replayed.rows[0]["info"] == batch.rows[0]["info"]
