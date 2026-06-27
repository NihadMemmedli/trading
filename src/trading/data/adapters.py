"""Public market-data adapters."""

from __future__ import annotations

from typing import Protocol

from trading.data.market import MarketDataError, OhlcvRequest, RawOhlcvBatch

PUBLIC_EXCHANGES = frozenset({"binance"})


class PublicOhlcvAdapter(Protocol):
    """Public spot OHLCV-only adapter contract."""

    def fetch_ohlcv(self, request: OhlcvRequest) -> RawOhlcvBatch:
        """Fetch public OHLCV rows without credentials or private endpoints."""


class PublicMarketDataAdapter:
    """Neutral CCXT-backed public spot OHLCV adapter.

    The import is intentionally lazy so application startup and API route imports do not
    initialize provider clients.
    """

    def __init__(self, exchange_name: str = "binance") -> None:
        self.exchange_name = exchange_name.lower()
        if self.exchange_name not in PUBLIC_EXCHANGES:
            raise MarketDataError(f"unsupported public exchange: {self.exchange_name}")
        self._client: object | None = None

    def _load_client(self) -> object:
        if self._client is not None:
            return self._client
        import ccxt

        exchange_cls = getattr(ccxt, self.exchange_name)
        self._client = exchange_cls({"enableRateLimit": True})
        return self._client

    def fetch_ohlcv(self, request: OhlcvRequest) -> RawOhlcvBatch:
        if request.exchange != self.exchange_name:
            raise MarketDataError(f"adapter configured for {self.exchange_name}")

        client = self._load_client()
        markets = client.load_markets()  # type: ignore[attr-defined]
        market = markets.get(request.symbol)
        if market is None or not bool(market.get("spot")):
            raise MarketDataError(f"{request.symbol} is not a public spot market")

        since_ms = int(request.since.timestamp() * 1000) if request.since is not None else None
        rows = client.fetch_ohlcv(  # type: ignore[attr-defined]
            request.symbol,
            timeframe=request.timeframe,
            since=since_ms,
            limit=request.limit,
        )
        if request.until is not None:
            until_ms = int(request.until.timestamp() * 1000)
            rows = [row for row in rows if int(row[0]) < until_ms]
        return RawOhlcvBatch(
            exchange=request.exchange,
            symbol=request.symbol,
            timeframe=request.timeframe,
            rows=rows,
        )
