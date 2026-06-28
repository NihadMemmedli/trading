"""Validated persistence for agent reports and trade proposals."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from trading.agents.contracts import (
    AnalystReportPayload,
    ProposalSide,
    TradeProposalPayload,
    validated_payload_json,
)
from trading.db.models import AgentReport, Asset, Exchange, TradeProposal, TradingPair
from trading.db.session import session_scope

DEFAULT_SIGNAL_EXCHANGE = "binance"


class SignalValidationError(ValueError):
    """Raised when an agent payload fails the strict output contract."""


class AgentReportNotFoundError(LookupError):
    """Raised when a persisted agent report cannot be found."""


class TradeProposalNotFoundError(LookupError):
    """Raised when a persisted trade proposal cannot be found."""


class AgentSignalService:
    """Stores validated agent reports and trader proposals as research artifacts."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_analyst_report(
        self,
        payload: AnalystReportPayload | Mapping[str, Any],
    ) -> AgentReport:
        report_payload = _validate_analyst_report(payload)
        output_json = validated_payload_json(report_payload)

        with session_scope(self._session_factory) as session:
            pair = _get_or_create_pair(session, DEFAULT_SIGNAL_EXCHANGE, report_payload.symbol)
            report = AgentReport(
                pair_id=pair.id,
                timestamp=report_payload.timestamp,
                agent_name=report_payload.agent_name.value,
                report_type="analyst_report",
                output_json=output_json,
                confidence=report_payload.confidence,
            )
            session.add(report)
            session.flush()
            session.refresh(report)
            session.expunge(report)
            return report

    def get_analyst_report(self, report_id: uuid.UUID) -> AgentReport:
        with session_scope(self._session_factory) as session:
            report = session.get(AgentReport, report_id)
            if report is None:
                raise AgentReportNotFoundError(str(report_id))
            session.expunge(report)
            return report

    def list_analyst_reports(
        self,
        *,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[AgentReport]:
        if limit < 1:
            raise ValueError("limit must be positive")

        with session_scope(self._session_factory) as session:
            query = select(AgentReport)
            if symbol is not None:
                query = query.join(TradingPair, AgentReport.pair_id == TradingPair.id).where(
                    TradingPair.symbol == symbol
                )
            rows = session.execute(
                query.order_by(AgentReport.created_at.desc(), AgentReport.id.desc()).limit(limit)
            )
            reports = list(rows.scalars().all())
            for report in reports:
                session.expunge(report)
            return reports

    def create_trade_proposal(
        self,
        payload: TradeProposalPayload | Mapping[str, Any],
    ) -> TradeProposal:
        proposal_payload = _validate_trade_proposal(payload)
        raw_json = validated_payload_json(proposal_payload)
        entry_type = (
            proposal_payload.entry.type.value if proposal_payload.entry is not None else None
        )
        entry_price = proposal_payload.entry.price if proposal_payload.entry is not None else None
        status = "pending_risk"
        if proposal_payload.side == ProposalSide.FLAT:
            status = ProposalSide.FLAT.value

        with session_scope(self._session_factory) as session:
            pair = _get_or_create_pair(session, DEFAULT_SIGNAL_EXCHANGE, proposal_payload.symbol)
            proposal = TradeProposal(
                pair_id=pair.id,
                timestamp=proposal_payload.timestamp,
                source=proposal_payload.source,
                side=proposal_payload.side.value,
                entry_type=entry_type,
                entry_price=entry_price,
                stop_loss=proposal_payload.stop_loss,
                take_profit_json=[
                    target.model_dump(mode="json") for target in proposal_payload.take_profit
                ],
                confidence=proposal_payload.confidence,
                thesis=proposal_payload.thesis,
                invalidation=proposal_payload.invalidation,
                raw_json=raw_json,
                status=status,
            )
            session.add(proposal)
            session.flush()
            session.refresh(proposal)
            session.expunge(proposal)
            return proposal

    def get_trade_proposal(self, proposal_id: uuid.UUID) -> TradeProposal:
        with session_scope(self._session_factory) as session:
            proposal = session.get(TradeProposal, proposal_id)
            if proposal is None:
                raise TradeProposalNotFoundError(str(proposal_id))
            session.expunge(proposal)
            return proposal

    def list_trade_proposals(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> list[TradeProposal]:
        if limit < 1:
            raise ValueError("limit must be positive")

        with session_scope(self._session_factory) as session:
            query = select(TradeProposal)
            if status is not None:
                query = query.where(TradeProposal.status == status)
            rows = session.execute(
                query.order_by(TradeProposal.created_at.desc(), TradeProposal.id.desc()).limit(
                    limit
                )
            )
            proposals = list(rows.scalars().all())
            for proposal in proposals:
                session.expunge(proposal)
            return proposals


def _validate_analyst_report(
    payload: AnalystReportPayload | Mapping[str, Any],
) -> AnalystReportPayload:
    if isinstance(payload, AnalystReportPayload):
        return payload
    try:
        return AnalystReportPayload.model_validate(payload)
    except ValidationError as exc:
        raise SignalValidationError(str(exc)) from exc


def _validate_trade_proposal(
    payload: TradeProposalPayload | Mapping[str, Any],
) -> TradeProposalPayload:
    if isinstance(payload, TradeProposalPayload):
        return payload
    try:
        return TradeProposalPayload.model_validate(payload)
    except ValidationError as exc:
        raise SignalValidationError(str(exc)) from exc


def _get_or_create_pair(session: Session, exchange_name: str, symbol: str) -> TradingPair:
    exchange = _get_or_create_exchange(session, exchange_name)
    base_symbol, quote_symbol = symbol.split("/", maxsplit=1)
    base = _get_or_create_asset(session, base_symbol)
    quote = _get_or_create_asset(session, quote_symbol)
    pair = session.execute(
        select(TradingPair).where(
            TradingPair.exchange_id == exchange.id,
            TradingPair.symbol == symbol,
            TradingPair.market_type == "spot",
        )
    ).scalar_one_or_none()
    if pair is not None:
        return pair

    pair = TradingPair(
        exchange_id=exchange.id,
        base_asset_id=base.id,
        quote_asset_id=quote.id,
        symbol=symbol,
        market_type="spot",
        active=True,
    )
    session.add(pair)
    session.flush()
    return pair


def _get_or_create_exchange(session: Session, name: str) -> Exchange:
    exchange = session.execute(select(Exchange).where(Exchange.name == name)).scalar_one_or_none()
    if exchange is not None:
        return exchange
    exchange = Exchange(name=name, market_type="spot")
    session.add(exchange)
    session.flush()
    return exchange


def _get_or_create_asset(session: Session, symbol: str) -> Asset:
    asset = session.execute(select(Asset).where(Asset.symbol == symbol)).scalar_one_or_none()
    if asset is not None:
        return asset
    asset = Asset(symbol=symbol)
    session.add(asset)
    session.flush()
    return asset
