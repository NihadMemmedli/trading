"""Pydantic schemas for risk decision endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from trading.db.models import RiskDecision


class RiskDecisionResponse(BaseModel):
    proposal_id: uuid.UUID
    decision: str
    reason: str
    max_position_size: Decimal | None
    max_loss_usd: Decimal | None
    violated_rules: list[str]
    warnings: list[str]
    raw: dict[str, Any]
    created_at: datetime
    inserted_at: datetime

    @classmethod
    def from_decision(cls, decision: RiskDecision) -> RiskDecisionResponse:
        return cls(
            proposal_id=decision.proposal_id,
            decision=decision.decision,
            reason=decision.reason,
            max_position_size=decision.max_position_size,
            max_loss_usd=decision.max_loss_usd,
            violated_rules=decision.violated_rules_json,
            warnings=decision.warnings_json,
            raw=decision.raw_json,
            created_at=decision.created_at,
            inserted_at=decision.inserted_at,
        )


class RiskDecisionListResponse(BaseModel):
    decisions: list[RiskDecisionResponse] = Field(default_factory=list)
