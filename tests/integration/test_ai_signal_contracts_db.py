from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.exc import OperationalError

from alembic import command
from trading.core.settings import Settings
from trading.db.models import RiskDecision, TradeProposal
from trading.db.session import create_db_engine, create_session_factory
from trading.services.agent_signals import AgentSignalService, SignalValidationError
from trading.services.risk_decisions import RiskDecisionProposalStatusError, RiskDecisionService

pytestmark = pytest.mark.integration


def db_settings() -> Settings:
    return Settings(
        DATABASE_URL=os.environ.get(
            "DATABASE_URL",
            "postgresql://trading:trading@localhost:55432/trading",
        )
    )


def require_postgres() -> Settings:
    settings = db_settings()
    engine = None
    try:
        engine = create_db_engine(settings)
        with engine.connect() as connection:
            connection.execute(sa.text("SELECT 1"))
    except (ModuleNotFoundError, OperationalError) as exc:
        pytest.skip(f"Postgres is not reachable: {exc}")
    finally:
        if engine is not None:
            engine.dispose()
    return settings


def alembic_config(settings: Settings) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
    return config


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


def valid_flat_proposal_payload() -> dict[str, object]:
    return {
        "schema_version": "trade_proposal.v1",
        "symbol": "SOL/USDT",
        "timeframe": "1h",
        "timestamp": "2026-06-27T12:00:00Z",
        "side": "flat",
        "confidence": "0.55",
        "thesis": "No clean setup.",
        "required_confirmations": [],
        "source_agents": ["technical_analyst"],
        "no_trade_reason": "No actionable edge.",
    }


def risk_decision_payload(proposal_id: str) -> dict[str, object]:
    return {
        "schema_version": "risk_decision.v1",
        "proposal_id": proposal_id,
        "decision": "reject",
        "reason": "spread above threshold",
        "max_position_size": None,
        "max_loss_usd": None,
        "violated_rules": ["spread_limit"],
        "warnings": [],
        "metadata": {"policy_version": "2026-06-27"},
        "created_at": "2026-06-27T12:01:00Z",
    }


def test_ai_signal_migration_and_real_db_persistence() -> None:
    settings = require_postgres()
    config = alembic_config(settings)
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    engine = create_db_engine(settings)
    with engine.begin() as connection:
        agent_table = connection.execute(
            sa.text("SELECT to_regclass('public.agent_reports')")
        ).scalar_one()
        proposal_table = connection.execute(
            sa.text("SELECT to_regclass('public.trade_proposals')")
        ).scalar_one()
        risk_table = connection.execute(
            sa.text("SELECT to_regclass('public.risk_decisions')")
        ).scalar_one()
        agent_json_type = connection.execute(
            sa.text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_schema = 'public' "
                "AND table_name = 'agent_reports' "
                "AND column_name = 'output_json'"
            )
        ).scalar_one()
        proposal_json_type = connection.execute(
            sa.text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_schema = 'public' "
                "AND table_name = 'trade_proposals' "
                "AND column_name = 'raw_json'"
            )
        ).scalar_one()
        risk_json_type = connection.execute(
            sa.text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_schema = 'public' "
                "AND table_name = 'risk_decisions' "
                "AND column_name = 'raw_json'"
            )
        ).scalar_one()
        agent_index = connection.execute(
            sa.text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'agent_reports' "
                "AND indexname = 'ix_agent_reports_pair_timestamp'"
            )
        ).scalar_one()
        proposal_index = connection.execute(
            sa.text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'trade_proposals' "
                "AND indexname = 'ix_trade_proposals_pair_timestamp_status'"
            )
        ).scalar_one()
        risk_index = connection.execute(
            sa.text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename = 'risk_decisions' "
                "AND indexname = 'ix_risk_decisions_decision_created_at'"
            )
        ).scalar_one()

    assert agent_table == "agent_reports"
    assert proposal_table == "trade_proposals"
    assert risk_table == "risk_decisions"
    assert agent_json_type == "jsonb"
    assert proposal_json_type == "jsonb"
    assert risk_json_type == "jsonb"
    assert agent_index == "ix_agent_reports_pair_timestamp"
    assert proposal_index == "ix_trade_proposals_pair_timestamp_status"
    assert risk_index == "ix_risk_decisions_decision_created_at"

    session_factory = create_session_factory(engine)
    signal_service = AgentSignalService(session_factory)
    risk_service = RiskDecisionService(session_factory)

    report = signal_service.create_analyst_report(valid_report_payload())
    long_proposal = signal_service.create_trade_proposal(valid_long_proposal_payload())
    flat_proposal = signal_service.create_trade_proposal(valid_flat_proposal_payload())
    decision = risk_service.create_risk_decision(risk_decision_payload(str(long_proposal.id)))
    retrieved_report = signal_service.get_analyst_report(report.id)
    retrieved_proposal = signal_service.get_trade_proposal(long_proposal.id)
    listed_reports = signal_service.list_analyst_reports(symbol="BTC/USDT", limit=10)
    listed_proposals = signal_service.list_trade_proposals(status="rejected", limit=10)
    retrieved_decision = risk_service.get_risk_decision(long_proposal.id)

    assert retrieved_report.output_json["schema_version"] == "agent_report.v1"
    assert retrieved_report.timestamp == datetime(2026, 6, 27, 12, tzinfo=UTC)
    assert retrieved_proposal.raw_json["schema_version"] == "trade_proposal.v1"
    assert retrieved_proposal.status == "rejected"
    assert flat_proposal.status == "flat"
    assert decision.proposal_id == long_proposal.id
    assert retrieved_decision.violated_rules_json == ["spread_limit"]
    assert report.id in {row.id for row in listed_reports}
    assert long_proposal.id in {row.id for row in listed_proposals}

    with pytest.raises(SignalValidationError):
        signal_service.create_trade_proposal({**valid_long_proposal_payload(), "side": "short"})

    with session_factory() as session:
        persisted_proposal = session.get(TradeProposal, long_proposal.id)
        persisted_decision = session.get(RiskDecision, long_proposal.id)

    assert persisted_proposal is not None
    assert persisted_proposal.raw_json["entry"]["price"] == "61000"
    assert persisted_decision is not None
    assert persisted_decision.raw_json["metadata"] == {"policy_version": "2026-06-27"}


@pytest.mark.parametrize("proposal_status", ["flat", "approved", "rejected", "reduced"])
def test_risk_decision_rejects_non_pending_proposals(proposal_status: str) -> None:
    settings = require_postgres()
    command.upgrade(alembic_config(settings), "head")

    engine = create_db_engine(settings)
    session_factory = create_session_factory(engine)
    signal_service = AgentSignalService(session_factory)
    risk_service = RiskDecisionService(session_factory)

    if proposal_status == "flat":
        proposal = signal_service.create_trade_proposal(valid_flat_proposal_payload())
    else:
        proposal = signal_service.create_trade_proposal(valid_long_proposal_payload())
        with session_factory() as session:
            persisted_proposal = session.get(TradeProposal, proposal.id)
            assert persisted_proposal is not None
            persisted_proposal.status = proposal_status
            session.commit()

    with pytest.raises(RiskDecisionProposalStatusError) as exc_info:
        risk_service.create_risk_decision(risk_decision_payload(str(proposal.id)))

    assert str(exc_info.value) == (
        f"risk decision requires pending_risk trade proposal; proposal status is {proposal_status}"
    )
    with session_factory() as session:
        persisted_decision = session.get(RiskDecision, proposal.id)

    assert persisted_decision is None
