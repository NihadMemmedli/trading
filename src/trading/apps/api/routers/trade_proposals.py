"""Trade proposal research artifact API."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status

from trading.agents.contracts import TradeProposalPayload
from trading.apps.api.dependencies import AgentSignalServiceDependency
from trading.apps.api.schemas.agent_signals import (
    TradeProposalListResponse,
    TradeProposalResponse,
)
from trading.services.agent_signals import SignalValidationError, TradeProposalNotFoundError

router = APIRouter(prefix="/trade-proposals", tags=["trade-proposals"])

TradeProposalStatusFilter = Literal["pending_risk", "flat", "approved", "rejected", "reduced"]


@router.post("", response_model=TradeProposalResponse, status_code=status.HTTP_201_CREATED)
def create_trade_proposal(
    payload: TradeProposalPayload,
    service: AgentSignalServiceDependency,
) -> TradeProposalResponse:
    try:
        proposal = service.create_trade_proposal(payload)
    except SignalValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return TradeProposalResponse.from_proposal(proposal)


@router.get("/{proposal_id}", response_model=TradeProposalResponse)
def get_trade_proposal(
    proposal_id: uuid.UUID,
    service: AgentSignalServiceDependency,
) -> TradeProposalResponse:
    try:
        proposal = service.get_trade_proposal(proposal_id)
    except TradeProposalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="trade proposal not found",
        ) from exc
    return TradeProposalResponse.from_proposal(proposal)


@router.get("", response_model=TradeProposalListResponse)
def list_trade_proposals(
    service: AgentSignalServiceDependency,
    status_filter: Annotated[TradeProposalStatusFilter | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> TradeProposalListResponse:
    proposals = [
        TradeProposalResponse.from_proposal(proposal)
        for proposal in service.list_trade_proposals(status=status_filter, limit=limit)
    ]
    return TradeProposalListResponse(proposals=proposals)
