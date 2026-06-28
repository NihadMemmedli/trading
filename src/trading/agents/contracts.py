"""Strict contracts for persisted agent research outputs."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading.data.market import require_exact_utc, validate_symbol, validate_timeframe

AGENT_REPORT_SCHEMA_VERSION: Final[Literal["agent_report.v1"]] = "agent_report.v1"
TRADE_PROPOSAL_SCHEMA_VERSION: Final[Literal["trade_proposal.v1"]] = "trade_proposal.v1"


class AgentRole(StrEnum):
    TECHNICAL_ANALYST = "technical_analyst"
    PRICE_ACTION_ANALYST = "price_action_analyst"
    FUNDAMENTAL_ANALYST = "fundamental_analyst"
    NEWS_ANALYST = "news_analyst"
    SENTIMENT_ANALYST = "sentiment_analyst"
    QUANT_MODEL_ANALYST = "quant_model_analyst"
    TRADER = "trader"
    RISK_MANAGER = "risk_manager"
    PORTFOLIO_MANAGER = "portfolio_manager"


class SignalDirection(StrEnum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


class RecommendedAction(StrEnum):
    CONSIDER_LONG = "consider_long"
    HOLD = "hold"
    AVOID = "avoid"
    CONSIDER_SHORT = "consider_short"


class ProposalSide(StrEnum):
    LONG = "long"
    FLAT = "flat"


class EntryType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=1000)
    weight: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("1"))

    @field_validator("weight")
    @classmethod
    def validate_weight(cls, value: Decimal | None) -> Decimal | None:
        return _validate_optional_finite_decimal(value, field_name="weight")


class KeyLevels(BaseModel):
    model_config = ConfigDict(extra="forbid")

    support: list[Decimal] = Field(default_factory=list, max_length=20)
    resistance: list[Decimal] = Field(default_factory=list, max_length=20)
    invalidation: Decimal | None = Field(default=None, gt=Decimal("0"))

    @field_validator("support", "resistance")
    @classmethod
    def validate_levels(cls, value: list[Decimal]) -> list[Decimal]:
        for level in value:
            _validate_finite_decimal(level, field_name="level")
            if level <= 0:
                raise ValueError("level must be positive")
        return value

    @field_validator("invalidation")
    @classmethod
    def validate_invalidation(cls, value: Decimal | None) -> Decimal | None:
        return _validate_optional_finite_decimal(value, field_name="invalidation")


class AnalystReportPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["agent_report.v1"] = AGENT_REPORT_SCHEMA_VERSION
    agent_name: AgentRole
    symbol: str
    timeframe: str
    timestamp: datetime
    direction: SignalDirection
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    score: int = Field(ge=0, le=100)
    summary: str = Field(min_length=1, max_length=2000)
    evidence: list[EvidenceItem] = Field(default_factory=list, max_length=50)
    key_levels: KeyLevels
    risks: list[str] = Field(default_factory=list, max_length=50)
    recommended_action: RecommendedAction

    @field_validator("symbol")
    @classmethod
    def validate_report_symbol(cls, value: str) -> str:
        return validate_symbol(value)

    @field_validator("timeframe")
    @classmethod
    def validate_report_timeframe(cls, value: str) -> str:
        return validate_timeframe(value)

    @field_validator("timestamp")
    @classmethod
    def validate_report_timestamp(cls, value: datetime) -> datetime:
        return require_exact_utc(value, field_name="timestamp")

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: Decimal) -> Decimal:
        return _validate_finite_decimal(value, field_name="confidence")

    @field_validator("risks")
    @classmethod
    def validate_risks(cls, value: list[str]) -> list[str]:
        return _validate_non_empty_strings(value, field_name="risks")


class ProposalEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: EntryType
    price: Decimal | None = Field(default=None, gt=Decimal("0"))

    @field_validator("price")
    @classmethod
    def validate_price(cls, value: Decimal | None) -> Decimal | None:
        return _validate_optional_finite_decimal(value, field_name="entry.price")

    @model_validator(mode="after")
    def validate_entry_price(self) -> ProposalEntry:
        if self.type == EntryType.LIMIT and self.price is None:
            raise ValueError("limit entry requires price")
        if self.type == EntryType.MARKET and self.price is not None:
            raise ValueError("market entry must not include price")
        return self


class TakeProfitTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price: Decimal = Field(gt=Decimal("0"))
    size_pct: Decimal = Field(gt=Decimal("0"), le=Decimal("1"))

    @field_validator("price", "size_pct")
    @classmethod
    def validate_decimal(cls, value: Decimal) -> Decimal:
        return _validate_finite_decimal(value, field_name="take_profit")


class TradeProposalPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["trade_proposal.v1"] = TRADE_PROPOSAL_SCHEMA_VERSION
    symbol: str
    timeframe: str
    timestamp: datetime
    source: str = Field(default="trader", min_length=1, max_length=64)
    side: ProposalSide
    entry: ProposalEntry | None = None
    stop_loss: Decimal | None = Field(default=None, gt=Decimal("0"))
    take_profit: list[TakeProfitTarget] = Field(default_factory=list, max_length=10)
    max_position_risk_pct: Decimal | None = Field(
        default=None,
        gt=Decimal("0"),
        le=Decimal("100"),
    )
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    thesis: str = Field(min_length=1, max_length=2000)
    invalidation: str | None = Field(default=None, min_length=1, max_length=1000)
    required_confirmations: list[str] = Field(default_factory=list, max_length=50)
    source_agents: list[AgentRole] = Field(default_factory=list, max_length=20)
    no_trade_reason: str | None = Field(default=None, min_length=1, max_length=1000)

    @field_validator("symbol")
    @classmethod
    def validate_proposal_symbol(cls, value: str) -> str:
        return validate_symbol(value)

    @field_validator("timeframe")
    @classmethod
    def validate_proposal_timeframe(cls, value: str) -> str:
        return validate_timeframe(value)

    @field_validator("timestamp")
    @classmethod
    def validate_proposal_timestamp(cls, value: datetime) -> datetime:
        return require_exact_utc(value, field_name="timestamp")

    @field_validator("source")
    @classmethod
    def normalize_source(cls, value: str) -> str:
        return value.strip()

    @field_validator("stop_loss", "max_position_risk_pct")
    @classmethod
    def validate_optional_decimal(cls, value: Decimal | None) -> Decimal | None:
        return _validate_optional_finite_decimal(value, field_name="proposal decimal")

    @field_validator("confidence")
    @classmethod
    def validate_proposal_confidence(cls, value: Decimal) -> Decimal:
        return _validate_finite_decimal(value, field_name="confidence")

    @field_validator("required_confirmations")
    @classmethod
    def validate_required_confirmations(cls, value: list[str]) -> list[str]:
        return _validate_non_empty_strings(value, field_name="required_confirmations")

    @model_validator(mode="after")
    def validate_shape(self) -> TradeProposalPayload:
        if self.side == ProposalSide.LONG:
            missing = [
                field_name
                for field_name, value in (
                    ("entry", self.entry),
                    ("stop_loss", self.stop_loss),
                    ("take_profit", self.take_profit),
                    ("max_position_risk_pct", self.max_position_risk_pct),
                    ("invalidation", self.invalidation),
                )
                if value is None or value == []
            ]
            if missing:
                raise ValueError(f"long proposal missing required fields: {', '.join(missing)}")
            total_take_profit = sum(target.size_pct for target in self.take_profit)
            if total_take_profit > Decimal("1"):
                raise ValueError("take_profit size_pct total cannot exceed 1")
            if self.no_trade_reason is not None:
                raise ValueError("long proposal must not include no_trade_reason")
            return self

        if self.entry is not None or self.stop_loss is not None:
            raise ValueError("flat proposal must not include entry or stop_loss")
        if self.take_profit:
            raise ValueError("flat proposal must not include take_profit")
        if self.max_position_risk_pct is not None:
            raise ValueError("flat proposal must not include max_position_risk_pct")
        if self.invalidation is not None:
            raise ValueError("flat proposal must not include invalidation")
        if self.no_trade_reason is None:
            raise ValueError("flat proposal requires no_trade_reason")
        return self


def validated_payload_json(model: BaseModel) -> dict[str, Any]:
    """Return a JSON-serializable dict suitable for JSONB persistence."""

    dumped = model.model_dump(mode="json")
    if not isinstance(dumped, dict):
        raise TypeError("validated payload must dump to an object")
    return dumped


def _validate_finite_decimal(value: Decimal, *, field_name: str) -> Decimal:
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return value


def _validate_optional_finite_decimal(
    value: Decimal | None,
    *,
    field_name: str,
) -> Decimal | None:
    if value is None:
        return None
    return _validate_finite_decimal(value, field_name=field_name)


def _validate_non_empty_strings(values: list[str], *, field_name: str) -> list[str]:
    normalized: list[str] = []
    for value in values:
        stripped = value.strip()
        if not stripped:
            raise ValueError(f"{field_name} entries must be non-empty")
        normalized.append(stripped)
    return normalized
