"""Validated persistence for deterministic risk decisions."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from trading.db.models import RiskDecision, TradeProposal
from trading.db.session import session_scope
from trading.risk.contracts import RiskDecisionPayload, RiskDecisionValue
from trading.services.agent_signals import SignalValidationError, TradeProposalNotFoundError


class RiskDecisionNotFoundError(LookupError):
    """Raised when a persisted risk decision cannot be found."""


class RiskDecisionConflictError(ValueError):
    """Raised when a proposal already has a risk decision."""


class RiskDecisionProposalStatusError(ValueError):
    """Raised when a proposal is not awaiting a risk decision."""


class RiskDecisionService:
    """Stores deterministic risk decisions for validated trade proposals."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_risk_decision(
        self,
        payload: RiskDecisionPayload | Mapping[str, Any],
    ) -> RiskDecision:
        decision_payload = _validate_risk_decision(payload)

        with session_scope(self._session_factory) as session:
            proposal = session.get(TradeProposal, decision_payload.proposal_id)
            if proposal is None:
                raise TradeProposalNotFoundError(str(decision_payload.proposal_id))
            existing = session.get(RiskDecision, decision_payload.proposal_id)
            if existing is not None:
                raise RiskDecisionConflictError(str(decision_payload.proposal_id))
            if proposal.status != "pending_risk":
                raise RiskDecisionProposalStatusError(
                    "risk decision requires pending_risk trade proposal; "
                    f"proposal status is {proposal.status}"
                )

            decision = RiskDecision(
                proposal_id=decision_payload.proposal_id,
                decision=decision_payload.decision.value,
                reason=decision_payload.reason,
                max_position_size=decision_payload.max_position_size,
                max_loss_usd=decision_payload.max_loss_usd,
                violated_rules_json=decision_payload.violated_rules,
                warnings_json=decision_payload.warnings,
                raw_json=decision_payload.payload_json(),
                created_at=decision_payload.created_at,
            )
            proposal.status = _proposal_status(decision_payload.decision)
            session.add(decision)
            session.flush()
            session.refresh(decision)
            session.expunge(decision)
            return decision

    def get_risk_decision(self, proposal_id: uuid.UUID) -> RiskDecision:
        with session_scope(self._session_factory) as session:
            decision = session.get(RiskDecision, proposal_id)
            if decision is None:
                raise RiskDecisionNotFoundError(str(proposal_id))
            session.expunge(decision)
            return decision

    def list_risk_decisions(self, *, limit: int = 50) -> list[RiskDecision]:
        if limit < 1:
            raise ValueError("limit must be positive")

        with session_scope(self._session_factory) as session:
            rows = session.execute(
                select(RiskDecision)
                .order_by(RiskDecision.created_at.desc(), RiskDecision.proposal_id)
                .limit(limit)
            )
            decisions = list(rows.scalars().all())
            for decision in decisions:
                session.expunge(decision)
            return decisions


def _validate_risk_decision(
    payload: RiskDecisionPayload | Mapping[str, Any],
) -> RiskDecisionPayload:
    if isinstance(payload, RiskDecisionPayload):
        return payload
    try:
        return RiskDecisionPayload.model_validate(payload)
    except ValidationError as exc:
        raise SignalValidationError(str(exc)) from exc


def _proposal_status(decision: RiskDecisionValue) -> str:
    if decision == RiskDecisionValue.APPROVE:
        return "approved"
    if decision == RiskDecisionValue.REJECT:
        return "rejected"
    return "reduced"
