"""Public market-data adapters."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from trading.data.market import (
    MarketDataError,
    OhlcvRequest,
    RawOhlcvBatch,
    RawTradeBatch,
    TradeRequest,
    parse_timestamp,
)

PUBLIC_EXCHANGES = frozenset({"binance"})


def _trade_timestamp_ms(row: dict[str, object]) -> int:
    timestamp = row.get("timestamp")
    if isinstance(timestamp, int | float | str):
        return int(timestamp)
    datetime_value = row.get("datetime")
    if isinstance(datetime_value, datetime | str | int | float):
        return int(parse_timestamp(datetime_value, field_name="datetime").timestamp() * 1000)
    raise MarketDataError("trade row must contain timestamp or datetime")


class PublicOhlcvAdapter(Protocol):
    """Public spot OHLCV-only adapter contract."""

    def fetch_ohlcv(self, request: OhlcvRequest) -> RawOhlcvBatch:
        """Fetch public OHLCV rows without credentials or private endpoints."""


class PublicTradeAdapter(Protocol):
    """Public spot trade adapter contract."""

    def fetch_trades(self, request: TradeRequest) -> RawTradeBatch:
        """Fetch public trade rows without credentials or private endpoints."""


class PublicMarketDataAdapter:
    """Neutral CCXT-backed public spot market-data adapter.

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

    def fetch_trades(self, request: TradeRequest) -> RawTradeBatch:
        if request.exchange != self.exchange_name:
            raise MarketDataError(f"adapter configured for {self.exchange_name}")

        client = self._load_client()
        markets = client.load_markets()  # type: ignore[attr-defined]
        market = markets.get(request.symbol)
        if market is None or not bool(market.get("spot")):
            raise MarketDataError(f"{request.symbol} is not a public spot market")

        since_ms = int(request.since.timestamp() * 1000) if request.since is not None else None
        rows = client.fetch_trades(  # type: ignore[attr-defined]
            request.symbol,
            since=since_ms,
            limit=request.limit,
        )
        if request.until is not None:
            until_ms = int(request.until.timestamp() * 1000)
            rows = [row for row in rows if _trade_timestamp_ms(row) < until_ms]
        return RawTradeBatch(
            exchange=request.exchange,
            symbol=request.symbol,
            rows=rows,
        )
