from __future__ import annotations

import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from trading.agents.contracts import AnalystReportPayload, TradeProposalPayload
from trading.risk.contracts import RiskDecisionPayload


def valid_report_payload() -> dict[str, object]:
    return {
        "schema_version": "agent_report.v1",
        "agent_name": "technical_analyst",
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "timestamp": "2026-06-27T12:00:00Z",
        "direction": "long",
        "confidence": "0.71",
        "score": 68,
        "summary": "Trend is bullish but volatility is elevated.",
        "evidence": [
            {
                "source": "candles",
                "description": "Higher highs and higher lows over the session.",
                "weight": "0.6",
            }
        ],
        "key_levels": {
            "support": ["60200"],
            "resistance": ["62500"],
            "invalidation": "59400",
        },
        "risks": ["Resistance nearby"],
        "recommended_action": "consider_long",
    }


def valid_long_proposal_payload() -> dict[str, object]:
    return {
        "schema_version": "trade_proposal.v1",
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "timestamp": "2026-06-27T12:00:00Z",
        "side": "long",
        "entry": {"type": "limit", "price": "61000"},
        "stop_loss": "59400",
        "take_profit": [{"price": "62500", "size_pct": "0.4"}],
        "max_position_risk_pct": "0.5",
        "confidence": "0.68",
        "thesis": "Trend continuation after support retest.",
        "invalidation": "Close below 59400.",
        "required_confirmations": ["spread_bps < 10"],
        "source_agents": ["technical_analyst", "price_action_analyst"],
    }


def valid_flat_proposal_payload() -> dict[str, object]:
    return {
        "schema_version": "trade_proposal.v1",
        "symbol": "ETH/USDT",
        "timeframe": "4h",
        "timestamp": "2026-06-27T12:00:00Z",
        "side": "flat",
        "confidence": "0.62",
        "thesis": "Setup quality is below threshold.",
        "required_confirmations": [],
        "source_agents": ["technical_analyst"],
        "no_trade_reason": "Reward-to-risk is insufficient.",
    }


def valid_risk_decision_payload() -> dict[str, object]:
    return {
        "schema_version": "risk_decision.v1",
        "proposal_id": str(uuid.UUID("00000000-0000-4000-8000-000000000011")),
        "decision": "reject",
        "reason": "spread above threshold",
        "max_position_size": None,
        "max_loss_usd": None,
        "violated_rules": ["spread_limit"],
        "warnings": [],
        "metadata": {"policy_version": "2026-06-27"},
        "created_at": "2026-06-27T12:01:00Z",
    }


def test_accepts_valid_agent_report_flat_proposal_long_proposal_and_risk_decision() -> None:
    report = AnalystReportPayload.model_validate(valid_report_payload())
    long_proposal = TradeProposalPayload.model_validate(valid_long_proposal_payload())
    flat_proposal = TradeProposalPayload.model_validate(valid_flat_proposal_payload())
    risk_decision = RiskDecisionPayload.model_validate(valid_risk_decision_payload())

    assert report.symbol == "BTC/USDT"
    assert long_proposal.entry is not None
    assert long_proposal.entry.price == Decimal("61000")
    assert flat_proposal.no_trade_reason == "Reward-to-risk is insufficient."
    assert risk_decision.decision == "reject"


def test_trade_proposal_source_is_stripped_and_rejects_blank_after_stripping() -> None:
    payload = valid_long_proposal_payload()
    payload["source"] = "  trader_research  "

    proposal = TradeProposalPayload.model_validate(payload)

    assert proposal.source == "trader_research"

    payload["source"] = "   "

    with pytest.raises(ValidationError):
        TradeProposalPayload.model_validate(payload)


@pytest.mark.parametrize(
    "bad_value",
    [float("nan"), float("inf"), float("-inf"), Decimal("NaN"), Decimal("Infinity")],
)
def test_risk_decision_metadata_rejects_non_finite_numbers(bad_value: object) -> None:
    payload = valid_risk_decision_payload()
    payload["metadata"] = {"policy_version": "2026-06-27", "score": bad_value}

    with pytest.raises(ValidationError):
        RiskDecisionPayload.model_validate(payload)


@pytest.mark.parametrize(
    ("payload_factory", "field_name"),
    [
        (valid_report_payload, "summary"),
        (valid_long_proposal_payload, "entry"),
        (valid_risk_decision_payload, "reason"),
    ],
)
def test_contracts_reject_missing_required_fields(
    payload_factory,
    field_name: str,
) -> None:
    payload = payload_factory()
    del payload[field_name]
    model = _model_for_payload(payload)

    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize(
    ("payload", "field_name", "bad_value", "model"),
    [
        (valid_report_payload(), "agent_name", "chart_watcher", AnalystReportPayload),
        (valid_report_payload(), "confidence", Decimal("NaN"), AnalystReportPayload),
        (valid_report_payload(), "schema_version", "agent_report.v0", AnalystReportPayload),
        (valid_report_payload(), "symbol", "DOGE/USDT", AnalystReportPayload),
        (valid_report_payload(), "timeframe", "2h", AnalystReportPayload),
        (
            valid_report_payload(),
            "timestamp",
            datetime(2026, 6, 27, 16, 0, tzinfo=timezone(timedelta(hours=4))),
            AnalystReportPayload,
        ),
        (valid_long_proposal_payload(), "side", "short", TradeProposalPayload),
        (valid_risk_decision_payload(), "decision", "allow", RiskDecisionPayload),
    ],
)
def test_contracts_reject_unknown_enums_non_finite_numbers_version_and_bad_selectors(
    payload: dict[str, object],
    field_name: str,
    bad_value: object,
    model: type[AnalystReportPayload] | type[TradeProposalPayload] | type[RiskDecisionPayload],
) -> None:
    bad_payload = deepcopy(payload)
    bad_payload[field_name] = bad_value

    with pytest.raises(ValidationError):
        model.model_validate(bad_payload)


def test_contracts_reject_extra_fields_and_invalid_flat_or_long_shapes() -> None:
    extra_report = valid_report_payload()
    extra_report["order_id"] = "forbidden"
    flat_with_entry = valid_flat_proposal_payload()
    flat_with_entry["entry"] = {"type": "limit", "price": "100"}
    long_without_stop = valid_long_proposal_payload()
    del long_without_stop["stop_loss"]

    with pytest.raises(ValidationError):
        AnalystReportPayload.model_validate(extra_report)
    with pytest.raises(ValidationError):
        TradeProposalPayload.model_validate(flat_with_entry)
    with pytest.raises(ValidationError):
        TradeProposalPayload.model_validate(long_without_stop)


def _model_for_payload(
    payload: dict[str, object],
) -> type[AnalystReportPayload] | type[TradeProposalPayload] | type[RiskDecisionPayload]:
    schema_version = payload["schema_version"]
    if schema_version == "agent_report.v1":
        return AnalystReportPayload
    if schema_version == "trade_proposal.v1":
        return TradeProposalPayload
    return RiskDecisionPayload
