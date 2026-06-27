from __future__ import annotations

import sys
from datetime import UTC, datetime
from types import ModuleType

import pytest

from trading.data.adapters import PublicMarketDataAdapter
from trading.data.market import MarketDataError, OhlcvRequest


class FakeExchange:
    def __init__(self, config: dict[str, object]) -> None:
        self.config = config

    def load_markets(self) -> dict[str, dict[str, bool]]:
        return {"BTC/USDT": {"spot": True}, "BTC/USDT:USDT": {"spot": False}}

    def fetch_ohlcv(
        self,
        symbol: str,
        *,
        timeframe: str,
        since: int | None,
        limit: int,
    ) -> list[list[object]]:
        assert symbol == "BTC/USDT"
        assert timeframe == "1m"
        assert since is None
        assert limit == 5
        return [["2026-01-01T00:00:00Z", "1", "2", "1", "2", "10"]]


def test_public_adapter_lazily_uses_only_fetch_ohlcv(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_ccxt = ModuleType("ccxt")
    fake_ccxt.binance = FakeExchange  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ccxt", fake_ccxt)

    adapter = PublicMarketDataAdapter("binance")
    batch = adapter.fetch_ohlcv(OhlcvRequest(symbol="BTC/USDT", timeframe="1m", limit=5))

    assert batch.exchange == "binance"
    assert batch.rows == [["2026-01-01T00:00:00Z", "1", "2", "1", "2", "10"]]
    assert adapter._load_client().config == {"enableRateLimit": True}  # type: ignore[attr-defined]


def test_public_adapter_requires_spot_market(monkeypatch: pytest.MonkeyPatch) -> None:
    class NonSpotExchange(FakeExchange):
        def load_markets(self) -> dict[str, dict[str, bool]]:
            return {"BTC/USDT": {"spot": False}}

    fake_ccxt = ModuleType("ccxt")
    fake_ccxt.binance = NonSpotExchange  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ccxt", fake_ccxt)

    adapter = PublicMarketDataAdapter("binance")
    with pytest.raises(MarketDataError, match="public spot"):
        adapter.fetch_ohlcv(OhlcvRequest(symbol="BTC/USDT", timeframe="1m", limit=5))


def test_public_adapter_rejects_unsupported_exchange() -> None:
    with pytest.raises(MarketDataError, match="unsupported public exchange"):
        PublicMarketDataAdapter("kraken")


def test_public_adapter_applies_until_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    class BoundedExchange(FakeExchange):
        def fetch_ohlcv(
            self,
            symbol: str,
            *,
            timeframe: str,
            since: int | None,
            limit: int,
        ) -> list[list[object]]:
            return [
                [1767225600000, "1", "2", "1", "2", "10"],
                [1767225660000, "2", "3", "2", "3", "10"],
                [1767225720000, "3", "4", "3", "4", "10"],
            ]

    fake_ccxt = ModuleType("ccxt")
    fake_ccxt.binance = BoundedExchange  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ccxt", fake_ccxt)

    adapter = PublicMarketDataAdapter("binance")
    batch = adapter.fetch_ohlcv(
        OhlcvRequest(
            symbol="BTC/USDT",
            timeframe="1m",
            limit=5,
            until=datetime(2026, 1, 1, 0, 2, tzinfo=UTC),
        )
    )

    assert len(batch.rows) == 2
