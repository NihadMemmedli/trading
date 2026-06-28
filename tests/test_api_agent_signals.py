from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from fastapi.testclient import TestClient

from trading.apps.api import create_app
from trading.apps.api.dependencies import get_agent_signal_service, get_risk_decision_service
from trading.core.settings import Settings
from trading.services.agent_signals import (
    AgentReportNotFoundError,
    SignalValidationError,
    TradeProposalNotFoundError,
)
from trading.services.risk_decisions import RiskDecisionConflictError, RiskDecisionNotFoundError


class FakeAgentSignalService:
    def __init__(self) -> None:
        self.report_id = uuid.UUID("00000000-0000-4000-8000-000000000021")
        self.proposal_id = uuid.UUID("00000000-0000-4000-8000-000000000031")
        self.created = datetime(2026, 6, 27, 12, 2, tzinfo=UTC)
        self.report_payloads: list[object] = []
        self.proposal_payloads: list[object] = []

    def _report(self, **overrides: object) -> SimpleNamespace:
        defaults = {
            "id": self.report_id,
            "pair_id": 1,
            "timestamp": datetime(2026, 6, 27, 12, tzinfo=UTC),
            "agent_name": "technical_analyst",
            "report_type": "analyst_report",
            "output_json": valid_report_payload(),
            "confidence": Decimal("0.71"),
            "created_at": self.created,
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def _proposal(self, **overrides: object) -> SimpleNamespace:
        defaults = {
            "id": self.proposal_id,
            "pair_id": 1,
            "timestamp": datetime(2026, 6, 27, 12, tzinfo=UTC),
            "source": "trader",
            "side": "long",
            "entry_type": "limit",
            "entry_price": Decimal("61000"),
            "stop_loss": Decimal("59400"),
            "take_profit_json": [{"price": "62500", "size_pct": "0.4"}],
            "confidence": Decimal("0.68"),
            "thesis": "Trend continuation after support retest.",
            "invalidation": "Close below 59400.",
            "raw_json": valid_long_proposal_payload(),
            "status": "pending_risk",
            "created_at": self.created,
            "updated_at": self.created,
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def create_analyst_report(self, payload: object) -> SimpleNamespace:
        self.report_payloads.append(payload)
        if getattr(payload, "summary", "") == "service-invalid":
            raise SignalValidationError("invalid report")
        return self._report(output_json=payload.model_dump(mode="json"))

    def get_analyst_report(self, report_id: uuid.UUID) -> SimpleNamespace:
        if report_id != self.report_id:
            raise AgentReportNotFoundError(str(report_id))
        return self._report()

    def list_analyst_reports(
        self,
        *,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[SimpleNamespace]:
        output = {**valid_report_payload(), "symbol": symbol or "BTC/USDT"}
        return [self._report(output_json=output)][:limit]

    def create_trade_proposal(self, payload: object) -> SimpleNamespace:
        self.proposal_payloads.append(payload)
        if getattr(payload, "thesis", "") == "service-invalid":
            raise SignalValidationError("invalid proposal")
        return self._proposal(raw_json=payload.model_dump(mode="json"))

    def get_trade_proposal(self, proposal_id: uuid.UUID) -> SimpleNamespace:
        if proposal_id != self.proposal_id:
            raise TradeProposalNotFoundError(str(proposal_id))
        return self._proposal()

    def list_trade_proposals(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> list[SimpleNamespace]:
        return [self._proposal(status=status or "pending_risk")][:limit]


class FakeRiskDecisionService:
    def __init__(self) -> None:
        self.proposal_id = uuid.UUID("00000000-0000-4000-8000-000000000031")
        self.created = datetime(2026, 6, 27, 12, 1, tzinfo=UTC)
        self.inserted = datetime(2026, 6, 27, 12, 2, tzinfo=UTC)
        self.payloads: list[object] = []

    def _decision(self, **overrides: object) -> SimpleNamespace:
        defaults = {
            "proposal_id": self.proposal_id,
            "decision": "reject",
            "reason": "spread above threshold",
            "max_position_size": None,
            "max_loss_usd": None,
            "violated_rules_json": ["spread_limit"],
            "warnings_json": [],
            "raw_json": valid_risk_decision_payload(),
            "created_at": self.created,
            "inserted_at": self.inserted,
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def create_risk_decision(self, payload: object) -> SimpleNamespace:
        self.payloads.append(payload)
        if str(payload.proposal_id).endswith("0040"):
            raise TradeProposalNotFoundError(str(payload.proposal_id))
        if str(payload.proposal_id).endswith("0041"):
            raise RiskDecisionConflictError(str(payload.proposal_id))
        if payload.reason == "service-invalid":
            raise SignalValidationError("invalid risk decision")
        return self._decision(
            proposal_id=payload.proposal_id,
            raw_json=payload.model_dump(mode="json"),
        )

    def get_risk_decision(self, proposal_id: uuid.UUID) -> SimpleNamespace:
        if proposal_id != self.proposal_id:
            raise RiskDecisionNotFoundError(str(proposal_id))
        return self._decision()

    def list_risk_decisions(self, *, limit: int = 50) -> list[SimpleNamespace]:
        return [self._decision()][:limit]


def client_with_fake_services(
    signal_service: FakeAgentSignalService | None = None,
    risk_service: FakeRiskDecisionService | None = None,
) -> TestClient:
    app = create_app(Settings(APP_ENV="test"))
    app.dependency_overrides[get_agent_signal_service] = (
        lambda: signal_service or FakeAgentSignalService()
    )
    app.dependency_overrides[get_risk_decision_service] = (
        lambda: risk_service or FakeRiskDecisionService()
    )
    return TestClient(app)


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
        "evidence": [],
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


def valid_risk_decision_payload() -> dict[str, object]:
    return {
        "schema_version": "risk_decision.v1",
        "proposal_id": "00000000-0000-4000-8000-000000000031",
        "decision": "reject",
        "reason": "spread above threshold",
        "max_position_size": None,
        "max_loss_usd": None,
        "violated_rules": ["spread_limit"],
        "warnings": [],
        "metadata": {"policy_version": "2026-06-27"},
        "created_at": "2026-06-27T12:01:00Z",
    }


def test_agent_report_create_get_list_and_validation_mapping() -> None:
    service = FakeAgentSignalService()
    service_invalid = valid_report_payload()
    service_invalid["summary"] = "service-invalid"

    with client_with_fake_services(signal_service=service) as client:
        created = client.post("/agents/reports", json=valid_report_payload())
        fetched = client.get("/agents/reports/00000000-0000-4000-8000-000000000021")
        listed = client.get("/agents/reports?symbol=btc_usdt&limit=1")
        missing = client.get("/agents/reports/00000000-0000-4000-8000-000000000022")
        malformed = client.post(
            "/agents/reports",
            json={**valid_report_payload(), "agent_name": "bad"},
        )
        service_rejected = client.post("/agents/reports", json=service_invalid)

    assert created.status_code == 201
    assert created.json()["output"]["schema_version"] == "agent_report.v1"
    assert fetched.status_code == 200
    assert listed.status_code == 200
    assert listed.json()["reports"][0]["output"]["symbol"] == "BTC/USDT"
    assert missing.status_code == 404
    assert malformed.status_code == 422
    assert service_rejected.status_code == 422
    assert len(service.report_payloads) == 2


def test_trade_proposal_create_get_list_and_validation_mapping() -> None:
    service = FakeAgentSignalService()
    service_invalid = valid_long_proposal_payload()
    service_invalid["thesis"] = "service-invalid"

    with client_with_fake_services(signal_service=service) as client:
        created = client.post("/trade-proposals", json=valid_long_proposal_payload())
        fetched = client.get("/trade-proposals/00000000-0000-4000-8000-000000000031")
        listed = client.get("/trade-proposals?status=pending_risk&limit=1")
        missing = client.get("/trade-proposals/00000000-0000-4000-8000-000000000032")
        malformed = client.post(
            "/trade-proposals",
            json={**valid_long_proposal_payload(), "side": "short"},
        )
        service_rejected = client.post("/trade-proposals", json=service_invalid)

    assert created.status_code == 201
    assert created.json()["status"] == "pending_risk"
    assert created.json()["raw"]["entry"]["price"] == "61000"
    assert fetched.status_code == 200
    assert listed.status_code == 200
    assert listed.json()["proposals"][0]["status"] == "pending_risk"
    assert missing.status_code == 404
    assert malformed.status_code == 422
    assert service_rejected.status_code == 422
    assert len(service.proposal_payloads) == 2


def test_risk_decision_create_get_list_and_error_mapping() -> None:
    service = FakeRiskDecisionService()

    with client_with_fake_services(risk_service=service) as client:
        created = client.post("/risk/decisions", json=valid_risk_decision_payload())
        fetched = client.get("/risk/decisions/00000000-0000-4000-8000-000000000031")
        listed = client.get("/risk/decisions?limit=1")
        missing = client.get("/risk/decisions/00000000-0000-4000-8000-000000000032")
        malformed = client.post(
            "/risk/decisions",
            json={**valid_risk_decision_payload(), "decision": "allow"},
        )
        not_found_payload = {
            **valid_risk_decision_payload(),
            "proposal_id": "00000000-0000-4000-8000-000000000040",
        }
        conflict_payload = {
            **valid_risk_decision_payload(),
            "proposal_id": "00000000-0000-4000-8000-000000000041",
        }
        not_found = client.post("/risk/decisions", json=not_found_payload)
        conflict = client.post("/risk/decisions", json=conflict_payload)

    assert created.status_code == 201
    assert created.json()["decision"] == "reject"
    assert created.json()["violated_rules"] == ["spread_limit"]
    assert fetched.status_code == 200
    assert listed.status_code == 200
    assert listed.json()["decisions"][0]["proposal_id"] == "00000000-0000-4000-8000-000000000031"
    assert missing.status_code == 404
    assert malformed.status_code == 422
    assert not_found.status_code == 404
    assert conflict.status_code == 409
