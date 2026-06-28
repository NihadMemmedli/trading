"""Persisted synchronous backtest run service."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, selectinload, sessionmaker

from trading.backtesting import (
    BacktestConfig,
    BacktestRunStatus,
    build_backtest_report,
    export_backtest_report_json,
    run_candle_backtest,
)
from trading.backtesting import (
    BacktestTrade as EngineBacktestTrade,
)
from trading.backtesting import (
    EquityPoint as EngineEquityPoint,
)
from trading.data.market import (
    MarketDataError,
    NormalizedCandle,
    require_exact_utc,
    require_utc,
    utc_now,
    validate_symbol,
    validate_timeframe,
)
from trading.db.models import (
    BacktestEquityPoint,
    BacktestRun,
    BacktestTrade,
    Candle,
    Dataset,
    Exchange,
    TradingPair,
)
from trading.db.session import session_scope
from trading.strategies import CandleStrategy, MovingAverageCrossoverStrategy, StrategyParameters

ERROR_MESSAGE_MAX_LENGTH = 2000


class BacktestRunNotFoundError(LookupError):
    """Raised when a persisted backtest run cannot be found."""


@dataclass(frozen=True)
class BacktestRunRequest:
    exchange: str
    symbol: str
    timeframe: str
    start: datetime
    end: datetime
    decision_time: datetime
    generated_at: datetime
    initial_capital: Decimal
    fee_bps: Decimal
    slippage_bps: Decimal
    strategy_name: str
    strategy_parameters: Mapping[str, Any]


@dataclass(frozen=True)
class NormalizedBacktestRunRequest:
    exchange: str
    symbol: str
    timeframe: str
    start: datetime
    end: datetime
    decision_time: datetime
    generated_at: datetime
    initial_capital: Decimal
    fee_bps: Decimal
    slippage_bps: Decimal
    strategy_name: str
    strategy_parameters: StrategyParameters


class BacktestService:
    """Coordinates point-in-time candle replay and persisted run metadata."""

    def __init__(self, session_factory: sessionmaker[Session], reports_dir: str | Path) -> None:
        self._session_factory = session_factory
        self._reports_dir = Path(reports_dir)

    def run_backtest(self, request: BacktestRunRequest) -> BacktestRun:
        normalized = _normalize_request(request)
        started_at = utc_now()

        try:
            strategy = build_backtest_strategy(
                normalized.strategy_name,
                normalized.strategy_parameters,
            )
            candles = self._load_candles(normalized)
            dataset_hash = deterministic_candle_dataset_hash(candles)
            config = BacktestConfig(
                symbol=normalized.symbol,
                timeframe=normalized.timeframe,
                initial_capital=normalized.initial_capital,
                fee_bps=normalized.fee_bps,
                slippage_bps=normalized.slippage_bps,
                start=normalized.start,
                end=normalized.end,
                decision_time=normalized.decision_time,
                strategy_name=normalized.strategy_name,
                strategy_parameters=normalized.strategy_parameters,
            )
            result = run_candle_backtest(
                candles=candles,
                dataset_hash=dataset_hash,
                config=config,
                strategy=strategy,
            )
            report = build_backtest_report(result, config, normalized.generated_at)
            report_json_text = export_backtest_report_json(report)
            report_json = json.loads(report_json_text)
            artifact_path = self._write_report_json(report.report_hash, report_json_text)
            return self._persist_succeeded_run(
                normalized,
                started_at=started_at,
                completed_at=utc_now(),
                dataset_hash=result.dataset_hash,
                config_hash=result.config_hash,
                result_hash=result.result_hash,
                report_hash=report.report_hash,
                metrics_json=report_json["metrics"],
                report_json=report_json,
                artifact_path=artifact_path,
                trades=result.trades,
                equity_curve=result.equity_curve,
            )
        except Exception as exc:
            return self._persist_failed_run(
                normalized,
                started_at=started_at,
                completed_at=utc_now(),
                error_message=f"{type(exc).__name__}: {exc}"[:ERROR_MESSAGE_MAX_LENGTH],
            )

    def get_run(self, run_id: uuid.UUID) -> BacktestRun:
        with session_scope(self._session_factory) as session:
            run = session.execute(
                select(BacktestRun)
                .options(
                    selectinload(BacktestRun.trades),
                    selectinload(BacktestRun.equity_points),
                )
                .where(BacktestRun.id == run_id)
            ).scalar_one_or_none()
            if run is None:
                raise BacktestRunNotFoundError(str(run_id))
            session.expunge_all()
            return run

    def list_runs(self, *, limit: int = 50) -> list[BacktestRun]:
        if limit < 1:
            raise ValueError("limit must be positive")

        with session_scope(self._session_factory) as session:
            result = session.execute(
                select(BacktestRun).order_by(BacktestRun.created_at.desc()).limit(limit)
            )
            runs = list(result.scalars().all())
            for run in runs:
                session.expunge(run)
            return runs

    def _load_candles(
        self,
        request: NormalizedBacktestRunRequest,
    ) -> tuple[NormalizedCandle, ...]:
        with session_scope(self._session_factory) as session:
            rows = session.execute(
                select(Candle)
                .join(TradingPair, Candle.pair_id == TradingPair.id)
                .join(Exchange, TradingPair.exchange_id == Exchange.id)
                .where(
                    Exchange.name == request.exchange,
                    TradingPair.symbol == request.symbol,
                    TradingPair.market_type == "spot",
                    Candle.source == request.exchange,
                    Candle.timeframe == request.timeframe,
                    Candle.timestamp >= request.start,
                    Candle.timestamp <= request.end,
                    Candle.available_at <= request.decision_time,
                )
                .order_by(Candle.timestamp)
            ).scalars()
            candles = tuple(
                NormalizedCandle(
                    exchange=request.exchange,
                    symbol=request.symbol,
                    timeframe=candle.timeframe,
                    timestamp=candle.timestamp,
                    open=candle.open,
                    high=candle.high,
                    low=candle.low,
                    close=candle.close,
                    volume=candle.volume,
                    available_at=candle.available_at,
                    raw_checksum=candle.raw_checksum,
                    quality_flags=candle.quality_flags,
                )
                for candle in rows
            )

        if not candles:
            raise MarketDataError("backtest requires at least one eligible candle")
        return candles

    def _write_report_json(self, report_hash: str, report_json_text: str) -> str:
        self._reports_dir.mkdir(parents=True, exist_ok=True)
        path = self._reports_dir / f"{report_hash}.json"
        path.write_text(report_json_text, encoding="utf-8")
        return str(path)

    def _persist_succeeded_run(
        self,
        request: NormalizedBacktestRunRequest,
        *,
        started_at: datetime,
        completed_at: datetime,
        dataset_hash: str,
        config_hash: str,
        result_hash: str,
        report_hash: str,
        metrics_json: dict[str, Any],
        report_json: dict[str, Any],
        artifact_path: str,
        trades: tuple[EngineBacktestTrade, ...],
        equity_curve: tuple[EngineEquityPoint, ...],
    ) -> BacktestRun:
        return self._persist_run(
            request,
            status=BacktestRunStatus.SUCCEEDED,
            started_at=started_at,
            completed_at=completed_at,
            dataset_hash=dataset_hash,
            config_hash=config_hash,
            result_hash=result_hash,
            report_hash=report_hash,
            metrics_json=metrics_json,
            report_json=report_json,
            artifact_path=artifact_path,
            error_message=None,
            trades=trades,
            equity_curve=equity_curve,
        )

    def _persist_failed_run(
        self,
        request: NormalizedBacktestRunRequest,
        *,
        started_at: datetime,
        completed_at: datetime,
        error_message: str,
    ) -> BacktestRun:
        return self._persist_run(
            request,
            status=BacktestRunStatus.FAILED,
            started_at=started_at,
            completed_at=completed_at,
            dataset_hash=None,
            config_hash=None,
            result_hash=None,
            report_hash=None,
            metrics_json=None,
            report_json=None,
            artifact_path=None,
            error_message=error_message,
            trades=(),
            equity_curve=(),
        )

    def _persist_run(
        self,
        request: NormalizedBacktestRunRequest,
        *,
        status: BacktestRunStatus,
        started_at: datetime,
        completed_at: datetime,
        dataset_hash: str | None,
        config_hash: str | None,
        result_hash: str | None,
        report_hash: str | None,
        metrics_json: dict[str, Any] | None,
        report_json: dict[str, Any] | None,
        artifact_path: str | None,
        error_message: str | None,
        trades: tuple[EngineBacktestTrade, ...],
        equity_curve: tuple[EngineEquityPoint, ...],
    ) -> BacktestRun:
        with session_scope(self._session_factory) as session:
            dataset_id = None
            if dataset_hash is not None:
                dataset_id = _get_or_create_backtest_dataset(
                    session,
                    request=request,
                    dataset_hash=dataset_hash,
                ).id

            run = BacktestRun(
                status=status.value,
                exchange=request.exchange,
                symbol=request.symbol,
                timeframe=request.timeframe,
                start=request.start,
                end=request.end,
                decision_time=request.decision_time,
                generated_at=request.generated_at,
                initial_capital=request.initial_capital,
                fee_bps=request.fee_bps,
                slippage_bps=request.slippage_bps,
                strategy_name=request.strategy_name,
                strategy_parameters=dict(request.strategy_parameters),
                dataset_id=dataset_id,
                dataset_hash=dataset_hash,
                config_hash=config_hash,
                result_hash=result_hash,
                report_hash=report_hash,
                metrics_json=metrics_json,
                report_json=report_json,
                artifact_path=artifact_path,
                started_at=started_at,
                completed_at=completed_at,
                error_message=error_message,
            )
            session.add(run)
            session.flush()
            session.add_all(
                BacktestTrade(
                    run_id=run.id,
                    symbol=trade.symbol,
                    timestamp=trade.timestamp,
                    side=trade.side,
                    quantity=trade.quantity,
                    fill_price=trade.fill_price,
                    fee=trade.fee,
                    slippage=trade.slippage,
                )
                for trade in trades
            )
            session.add_all(
                BacktestEquityPoint(
                    run_id=run.id,
                    timestamp=point.timestamp,
                    equity=point.equity,
                )
                for point in equity_curve
            )
            session.flush()
            loaded_run = session.execute(
                select(BacktestRun)
                .options(
                    selectinload(BacktestRun.trades),
                    selectinload(BacktestRun.equity_points),
                )
                .where(BacktestRun.id == run.id)
            ).scalar_one()
            session.expunge_all()
            return loaded_run


def _get_or_create_backtest_dataset(
    session: Session,
    *,
    request: NormalizedBacktestRunRequest,
    dataset_hash: str,
) -> Dataset:
    name = deterministic_backtest_dataset_name(request)
    inserted_id = session.execute(
        pg_insert(Dataset)
        .values(
            name=name,
            dataset_hash=dataset_hash,
            decision_time=request.decision_time,
            artifact_id=None,
        )
        .on_conflict_do_nothing(index_elements=["name", "dataset_hash"])
        .returning(Dataset.id)
    ).scalar_one_or_none()
    dataset_id = inserted_id
    if dataset_id is None:
        dataset_id = session.execute(
            select(Dataset.id).where(Dataset.name == name, Dataset.dataset_hash == dataset_hash)
        ).scalar_one()
    return session.execute(select(Dataset).where(Dataset.id == dataset_id)).scalar_one()


def deterministic_backtest_dataset_name(request: NormalizedBacktestRunRequest) -> str:
    return (
        f"backtest:{request.exchange}:{request.symbol}:{request.timeframe}:"
        f"{_utc_iso(request.start)}:{_utc_iso(request.end)}:{_utc_iso(request.decision_time)}"
    )


def build_backtest_strategy(
    strategy_name: str,
    strategy_parameters: Mapping[str, Any],
) -> CandleStrategy:
    normalized_name = strategy_name.strip()
    if normalized_name != "moving_average_crossover":
        raise MarketDataError("unsupported strategy_name")

    expected_keys = {"short_window", "long_window"}
    provided_keys = set(strategy_parameters)
    if provided_keys != expected_keys:
        raise MarketDataError("strategy_parameters must include short_window and long_window only")

    return MovingAverageCrossoverStrategy(
        short_window=_strict_positive_int(strategy_parameters["short_window"], "short_window"),
        long_window=_strict_positive_int(strategy_parameters["long_window"], "long_window"),
    )


def deterministic_candle_dataset_hash(candles: tuple[NormalizedCandle, ...]) -> str:
    payload = {
        "candles": [
            {
                "exchange": candle.exchange,
                "symbol": candle.symbol,
                "timeframe": candle.timeframe,
                "timestamp": candle.timestamp,
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
                "available_at": candle.available_at,
                "raw_checksum": candle.raw_checksum,
            }
            for candle in sorted(candles, key=lambda item: item.timestamp)
        ]
    }
    return _sha256_json(payload)


def _normalize_request(request: BacktestRunRequest) -> NormalizedBacktestRunRequest:
    exchange = request.exchange.strip().lower()
    if exchange != "binance":
        raise MarketDataError("only binance public spot candles are supported for backtests")

    start = require_utc(request.start, field_name="start")
    end = require_utc(request.end, field_name="end")
    if start >= end:
        raise MarketDataError("start must be earlier than end")

    return NormalizedBacktestRunRequest(
        exchange=exchange,
        symbol=validate_symbol(request.symbol),
        timeframe=validate_timeframe(request.timeframe),
        start=start,
        end=end,
        decision_time=require_utc(request.decision_time, field_name="decision_time"),
        generated_at=require_exact_utc(request.generated_at, field_name="generated_at"),
        initial_capital=Decimal(request.initial_capital),
        fee_bps=Decimal(request.fee_bps),
        slippage_bps=Decimal(request.slippage_bps),
        strategy_name=request.strategy_name.strip(),
        strategy_parameters=dict(request.strategy_parameters),
    )


def _strict_positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MarketDataError(f"{field_name} must be an integer")
    if value <= 0:
        raise MarketDataError(f"{field_name} must be positive")
    return int(value)


def _sha256_json(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_default(value: object) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _utc_iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
