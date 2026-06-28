"""Strict contracts for deterministic risk research decisions."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from trading.data.market import require_exact_utc

RISK_DECISION_SCHEMA_VERSION: Final[Literal["risk_decision.v1"]] = "risk_decision.v1"

JsonScalar = str | int | float | bool | None


class RiskDecisionValue(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    REDUCE = "reduce"


class RiskDecisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["risk_decision.v1"] = RISK_DECISION_SCHEMA_VERSION
    proposal_id: uuid.UUID
    decision: RiskDecisionValue
    reason: str = Field(min_length=1, max_length=2000)
    max_position_size: Decimal | None = Field(default=None, ge=Decimal("0"))
    max_loss_usd: Decimal | None = Field(default=None, ge=Decimal("0"))
    violated_rules: list[str] = Field(default_factory=list, max_length=50)
    warnings: list[str] = Field(default_factory=list, max_length=50)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return require_exact_utc(value, field_name="created_at")

    @field_validator("max_position_size", "max_loss_usd")
    @classmethod
    def validate_optional_decimal(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        if not value.is_finite():
            raise ValueError("risk decision numeric fields must be finite")
        return value

    @field_validator("violated_rules", "warnings")
    @classmethod
    def validate_string_list(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for entry in value:
            stripped = entry.strip()
            if not stripped:
                raise ValueError("list entries must be non-empty")
            normalized.append(stripped)
        return normalized

    def payload_json(self) -> dict[str, Any]:
        dumped = self.model_dump(mode="json")
        if not isinstance(dumped, dict):
            raise TypeError("risk decision payload must dump to an object")
        return dumped
