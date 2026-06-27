from __future__ import annotations

from pathlib import Path

from trading.data.offline import OhlcvFixtureSpec, build_offline_ohlcv_dataset

FIXTURE_ROOT = Path("tests/fixtures/market_data")


def mvp_fixtures() -> list[OhlcvFixtureSpec]:
    return [
        OhlcvFixtureSpec(FIXTURE_ROOT / "binance_spot_btc_usdt_1m.jsonl", "BTC/USDT", "1m"),
        OhlcvFixtureSpec(FIXTURE_ROOT / "binance_spot_eth_usdt_1m.jsonl", "ETH/USDT", "1m"),
        OhlcvFixtureSpec(FIXTURE_ROOT / "binance_spot_sol_usdt_1m.jsonl", "SOL/USDT", "1m"),
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
