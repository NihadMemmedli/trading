"""add ai signal contract tables

Revision ID: 20260627_0011
Revises: 20260627_0010
Create Date: 2026-06-27 05:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260627_0011"
down_revision: str | None = "20260627_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pair_id", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent_name", sa.String(length=64), nullable=False),
        sa.Column("report_type", sa.String(length=64), nullable=False),
        sa.Column("output_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="agent_report_confidence_valid",
        ),
        sa.ForeignKeyConstraint(["pair_id"], ["trading_pairs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_reports_pair_timestamp",
        "agent_reports",
        ["pair_id", "timestamp"],
    )
    op.create_index("ix_agent_reports_agent_name", "agent_reports", ["agent_name"])

    op.create_table(
        "trade_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pair_id", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("entry_type", sa.String(length=16), nullable=True),
        sa.Column("entry_price", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("stop_loss", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("take_profit_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("thesis", sa.Text(), nullable=False),
        sa.Column("invalidation", sa.Text(), nullable=True),
        sa.Column("raw_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("side IN ('long', 'flat')", name="trade_proposal_side_valid"),
        sa.CheckConstraint(
            "status IN ('pending_risk', 'flat', 'approved', 'rejected', 'reduced')",
            name="trade_proposal_status_valid",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="trade_proposal_confidence_valid",
        ),
        sa.CheckConstraint(
            "entry_price IS NULL OR entry_price > 0",
            name="entry_price_positive",
        ),
        sa.CheckConstraint("stop_loss IS NULL OR stop_loss > 0", name="stop_loss_positive"),
        sa.ForeignKeyConstraint(["pair_id"], ["trading_pairs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_trade_proposals_pair_timestamp_status",
        "trade_proposals",
        ["pair_id", "timestamp", "status"],
    )

    op.create_table(
        "risk_decisions",
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("max_position_size", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("max_loss_usd", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("violated_rules_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("warnings_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("raw_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "inserted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision IN ('approve', 'reject', 'reduce')",
            name="risk_decision_valid",
        ),
        sa.CheckConstraint(
            "max_position_size IS NULL OR max_position_size >= 0",
            name="max_position_size_nonnegative",
        ),
        sa.CheckConstraint(
            "max_loss_usd IS NULL OR max_loss_usd >= 0",
            name="max_loss_usd_nonnegative",
        ),
        sa.ForeignKeyConstraint(["proposal_id"], ["trade_proposals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("proposal_id"),
    )
    op.create_index("ix_risk_decisions_created_at", "risk_decisions", ["created_at"])
    op.create_index(
        "ix_risk_decisions_decision_created_at",
        "risk_decisions",
        ["decision", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_risk_decisions_decision_created_at", table_name="risk_decisions")
    op.drop_index("ix_risk_decisions_created_at", table_name="risk_decisions")
    op.drop_table("risk_decisions")
    op.drop_index(
        "ix_trade_proposals_pair_timestamp_status",
        table_name="trade_proposals",
    )
    op.drop_table("trade_proposals")
    op.drop_index("ix_agent_reports_agent_name", table_name="agent_reports")
    op.drop_index("ix_agent_reports_pair_timestamp", table_name="agent_reports")
    op.drop_table("agent_reports")
