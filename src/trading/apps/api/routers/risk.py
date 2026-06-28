"""Risk decision API."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from trading.apps.api.dependencies import RiskDecisionServiceDependency
from trading.apps.api.schemas.risk import RiskDecisionListResponse, RiskDecisionResponse
from trading.risk.contracts import RiskDecisionPayload
from trading.services.agent_signals import SignalValidationError, TradeProposalNotFoundError
from trading.services.risk_decisions import (
    RiskDecisionConflictError,
    RiskDecisionNotFoundError,
    RiskDecisionProposalStatusError,
)

router = APIRouter(prefix="/risk", tags=["risk"])


@router.post(
    "/decisions",
    response_model=RiskDecisionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_risk_decision(
    payload: RiskDecisionPayload,
    service: RiskDecisionServiceDependency,
) -> RiskDecisionResponse:
    try:
        decision = service.create_risk_decision(payload)
    except SignalValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except TradeProposalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="trade proposal not found",
        ) from exc
    except RiskDecisionConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="risk decision already exists",
        ) from exc
    except RiskDecisionProposalStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return RiskDecisionResponse.from_decision(decision)


@router.get("/decisions/{proposal_id}", response_model=RiskDecisionResponse)
def get_risk_decision(
    proposal_id: uuid.UUID,
    service: RiskDecisionServiceDependency,
) -> RiskDecisionResponse:
    try:
        decision = service.get_risk_decision(proposal_id)
    except RiskDecisionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="risk decision not found",
        ) from exc
    return RiskDecisionResponse.from_decision(decision)


@router.get("/decisions", response_model=RiskDecisionListResponse)
def list_risk_decisions(
    service: RiskDecisionServiceDependency,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> RiskDecisionListResponse:
    decisions = [
        RiskDecisionResponse.from_decision(decision)
        for decision in service.list_risk_decisions(limit=limit)
    ]
    return RiskDecisionListResponse(decisions=decisions)
