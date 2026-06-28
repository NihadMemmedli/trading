from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from trading.apps.api import create_app
from trading.apps.api.dependencies import get_risk_decision_service
from trading.core.settings import Settings
from trading.db.models import RiskDecision, TradeProposal
from trading.services import risk_decisions
from trading.services.risk_decisions import RiskDecisionProposalStatusError, RiskDecisionService


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


@pytest.mark.parametrize("proposal_status", ["flat", "approved", "rejected", "reduced"])
def test_create_risk_decision_rejects_non_pending_proposals(
    monkeypatch: pytest.MonkeyPatch,
    proposal_status: str,
) -> None:
    lookups: list[type[object]] = []

    def get_model(model: type[object], _id: object) -> SimpleNamespace | None:
        lookups.append(model)
        if model is TradeProposal:
            return SimpleNamespace(status=proposal_status)
        if model is RiskDecision:
            return None
        return None

    session = SimpleNamespace(get=get_model)

    @contextmanager
    def fake_session_scope(_factory: object):
        yield session

    monkeypatch.setattr(risk_decisions, "session_scope", fake_session_scope)
    service = RiskDecisionService(session_factory=object())  # type: ignore[arg-type]

    with pytest.raises(RiskDecisionProposalStatusError) as exc_info:
        service.create_risk_decision(valid_risk_decision_payload())

    assert str(exc_info.value) == (
        f"risk decision requires pending_risk trade proposal; proposal status is {proposal_status}"
    )
    assert lookups == [TradeProposal, RiskDecision]


@pytest.mark.parametrize("proposal_status", ["flat", "approved", "rejected", "reduced"])
def test_risk_decision_api_maps_non_pending_proposal_error(proposal_status: str) -> None:
    class FakeRiskDecisionService:
        def create_risk_decision(self, _payload: object) -> object:
            raise RiskDecisionProposalStatusError(
                "risk decision requires pending_risk trade proposal; "
                f"proposal status is {proposal_status}"
            )

    app = create_app(Settings(APP_ENV="test"))
    app.dependency_overrides[get_risk_decision_service] = FakeRiskDecisionService

    with TestClient(app) as client:
        response = client.post("/risk/decisions", json=valid_risk_decision_payload())

    assert response.status_code == 409
    assert response.json()["detail"] == (
        f"risk decision requires pending_risk trade proposal; proposal status is {proposal_status}"
    )
