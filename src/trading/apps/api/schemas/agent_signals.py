"""Pydantic schemas for agent report and trade proposal endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from trading.db.models import AgentReport, TradeProposal


class AnalystReportResponse(BaseModel):
    id: uuid.UUID
    pair_id: int
    timestamp: datetime
    agent_name: str
    report_type: str
    output: dict[str, Any]
    confidence: Decimal
    created_at: datetime

    @classmethod
    def from_report(cls, report: AgentReport) -> AnalystReportResponse:
        return cls(
            id=report.id,
            pair_id=report.pair_id,
            timestamp=report.timestamp,
            agent_name=report.agent_name,
            report_type=report.report_type,
            output=report.output_json,
            confidence=report.confidence,
            created_at=report.created_at,
        )


class AnalystReportListResponse(BaseModel):
    reports: list[AnalystReportResponse] = Field(default_factory=list)


class TradeProposalResponse(BaseModel):
    id: uuid.UUID
    pair_id: int
    timestamp: datetime
    source: str
    side: str
    entry_type: str | None
    entry_price: Decimal | None
    stop_loss: Decimal | None
    take_profit: list[dict[str, Any]]
    confidence: Decimal
    thesis: str
    invalidation: str | None
    raw: dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_proposal(cls, proposal: TradeProposal) -> TradeProposalResponse:
        return cls(
            id=proposal.id,
            pair_id=proposal.pair_id,
            timestamp=proposal.timestamp,
            source=proposal.source,
            side=proposal.side,
            entry_type=proposal.entry_type,
            entry_price=proposal.entry_price,
            stop_loss=proposal.stop_loss,
            take_profit=proposal.take_profit_json,
            confidence=proposal.confidence,
            thesis=proposal.thesis,
            invalidation=proposal.invalidation,
            raw=proposal.raw_json,
            status=proposal.status,
            created_at=proposal.created_at,
            updated_at=proposal.updated_at,
        )


class TradeProposalListResponse(BaseModel):
    proposals: list[TradeProposalResponse] = Field(default_factory=list)
