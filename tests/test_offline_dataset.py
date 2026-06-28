from __future__ import annotations

import json
from pathlib import Path

from trading.data.offline import (
    OhlcvFixtureSpec,
    OrderBookFixtureSpec,
    TradeFixtureSpec,
    build_offline_ohlcv_dataset,
    build_offline_order_book_dataset,
    build_offline_trade_dataset,
    load_raw_order_book_jsonl,
    load_raw_trade_jsonl,
)

FIXTURE_ROOT = Path("tests/fixtures/market_data")


def mvp_fixtures() -> list[OhlcvFixtureSpec]:
    return [
        OhlcvFixtureSpec(FIXTURE_ROOT / "binance_spot_btc_usdt_1m.jsonl", "BTC/USDT", "1m"),
        OhlcvFixtureSpec(FIXTURE_ROOT / "binance_spot_eth_usdt_1m.jsonl", "ETH/USDT", "1m"),
        OhlcvFixtureSpec(FIXTURE_ROOT / "binance_spot_sol_usdt_1m.jsonl", "SOL/USDT", "1m"),
    ]


def trade_fixtures() -> list[TradeFixtureSpec]:
    return [
        TradeFixtureSpec(FIXTURE_ROOT / "binance_spot_btc_usdt_trades.jsonl", "BTC/USDT"),
        TradeFixtureSpec(FIXTURE_ROOT / "binance_spot_eth_usdt_trades.jsonl", "ETH/USDT"),
        TradeFixtureSpec(FIXTURE_ROOT / "binance_spot_sol_usdt_trades.jsonl", "SOL/USDT"),
    ]


def order_book_fixtures() -> list[OrderBookFixtureSpec]:
    return [
        OrderBookFixtureSpec(FIXTURE_ROOT / "binance_spot_btc_usdt_order_books.jsonl", "BTC/USDT"),
        OrderBookFixtureSpec(FIXTURE_ROOT / "binance_spot_eth_usdt_order_books.jsonl", "ETH/USDT"),
        OrderBookFixtureSpec(FIXTURE_ROOT / "binance_spot_sol_usdt_order_books.jsonl", "SOL/USDT"),
    ]


def test_offline_ohlcv_dataset_loads_mvp_universe_without_network() -> None:
    dataset = build_offline_ohlcv_dataset(
        name="mvp-spot-1m",
        fixtures=mvp_fixtures(),
        decision_time="2026-01-01T00:05:00Z",
    )

    assert dataset.name == "mvp-spot-1m"
    assert dataset.symbols == ("BTC/USDT", "ETH/USDT", "SOL/USDT")
    assert len(dataset.candles) == 9
    assert len(dataset.dataset_hash) == 64
    assert {candle.available_at for candle in dataset.candles} == {dataset.decision_time}
    assert all(candle.raw_checksum for candle in dataset.candles)


def test_offline_ohlcv_dataset_hash_is_deterministic() -> None:
    first = build_offline_ohlcv_dataset(
        name="mvp-spot-1m",
        fixtures=mvp_fixtures(),
        decision_time="2026-01-01T00:05:00Z",
    )
    second = build_offline_ohlcv_dataset(
        name="mvp-spot-1m",
        fixtures=list(reversed(mvp_fixtures())),
        decision_time="2026-01-01T00:05:00Z",
    )

    assert first.dataset_hash == second.dataset_hash
    assert [candle.symbol for candle in first.candles] == [
        "BTC/USDT",
        "BTC/USDT",
        "BTC/USDT",
        "ETH/USDT",
        "ETH/USDT",
        "ETH/USDT",
        "SOL/USDT",
        "SOL/USDT",
        "SOL/USDT",
    ]


def test_offline_trade_dataset_loads_mvp_universe_without_network() -> None:
    dataset = build_offline_trade_dataset(
        name="mvp-spot-trades",
        fixtures=trade_fixtures(),
        decision_time="2026-01-01T00:05:00Z",
    )

    assert dataset.name == "mvp-spot-trades"
    assert dataset.symbols == ("BTC/USDT", "ETH/USDT", "SOL/USDT")
    assert len(dataset.trades) == 9
    assert len(dataset.dataset_hash) == 64
    assert {trade.available_at for trade in dataset.trades} == {dataset.decision_time}
    assert all(trade.raw_checksum for trade in dataset.trades)


def test_offline_trade_dataset_hash_is_deterministic() -> None:
    first = build_offline_trade_dataset(
        name="mvp-spot-trades",
        fixtures=trade_fixtures(),
        decision_time="2026-01-01T00:05:00Z",
    )
    second = build_offline_trade_dataset(
        name="mvp-spot-trades",
        fixtures=list(reversed(trade_fixtures())),
        decision_time="2026-01-01T00:05:00Z",
    )

    assert first.dataset_hash == second.dataset_hash
    assert [trade.symbol for trade in first.trades] == [
        "BTC/USDT",
        "BTC/USDT",
        "BTC/USDT",
        "ETH/USDT",
        "ETH/USDT",
        "ETH/USDT",
        "SOL/USDT",
        "SOL/USDT",
        "SOL/USDT",
    ]


def test_offline_trade_loader_preserves_raw_trade_payload(tmp_path: Path) -> None:
    fixture = tmp_path / "trades.jsonl"
    raw_trade = {
        "id": "trade-1",
        "timestamp": "2026-01-01T00:00:05Z",
        "side": "buy",
        "price": "42001.10",
        "amount": "0.125",
        "fee": {"currency": "USDT", "cost": "0.01"},
        "info": {"buyerOrderId": "abc"},
    }
    fixture.write_text(json.dumps(raw_trade) + "\n", encoding="utf-8")

    batch = load_raw_trade_jsonl(
        TradeFixtureSpec(fixture, "BTC/USDT"),
        fetched_at="2026-01-01T00:05:00Z",
    )

    assert batch.rows == [raw_trade]


def test_offline_order_book_dataset_loads_mvp_universe_without_network() -> None:
    dataset = build_offline_order_book_dataset(
        name="mvp-spot-order-books",
        fixtures=order_book_fixtures(),
        decision_time="2026-01-01T00:05:00Z",
    )

    assert dataset.name == "mvp-spot-order-books"
    assert dataset.symbols == ("BTC/USDT", "ETH/USDT", "SOL/USDT")
    assert len(dataset.snapshots) == 3
    assert len(dataset.dataset_hash) == 64
    assert {snapshot.available_at for snapshot in dataset.snapshots} == {dataset.decision_time}
    assert all(len(snapshot.bids) == 20 for snapshot in dataset.snapshots)
    assert all(len(snapshot.asks) == 20 for snapshot in dataset.snapshots)
    assert all(snapshot.raw_checksum for snapshot in dataset.snapshots)


def test_offline_order_book_dataset_hash_is_deterministic() -> None:
    first = build_offline_order_book_dataset(
        name="mvp-spot-order-books",
        fixtures=order_book_fixtures(),
        decision_time="2026-01-01T00:05:00Z",
    )
    second = build_offline_order_book_dataset(
        name="mvp-spot-order-books",
        fixtures=list(reversed(order_book_fixtures())),
        decision_time="2026-01-01T00:05:00Z",
    )

    assert first.dataset_hash == second.dataset_hash
    assert [snapshot.symbol for snapshot in first.snapshots] == [
        "BTC/USDT",
        "ETH/USDT",
        "SOL/USDT",
    ]


def test_offline_order_book_loader_preserves_raw_payload(tmp_path: Path) -> None:
    fixture = tmp_path / "order_books.jsonl"
    raw_order_book = {
        "timestamp": "2026-01-01T00:00:10Z",
        "nonce": 1,
        "bids": [["42000.00", "0.10"]],
        "asks": [["42001.00", "0.12"]],
        "info": {"lastUpdateId": 1},
    }
    fixture.write_text(json.dumps(raw_order_book) + "\n", encoding="utf-8")

    batch = load_raw_order_book_jsonl(
        OrderBookFixtureSpec(fixture, "BTC/USDT"),
        fetched_at="2026-01-01T00:05:00Z",
    )

    assert batch.rows == [raw_order_book]
