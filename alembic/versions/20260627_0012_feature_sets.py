"""add feature set registry tables

Revision ID: 20260627_0012
Revises: 20260627_0011
Create Date: 2026-06-27 06:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260627_0012"
down_revision: str | None = "20260627_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feature_sets",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("dataset_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("dataset_hash", sa.String(length=64), nullable=False),
        sa.Column("feature_set_hash", sa.String(length=64), nullable=False),
        sa.Column("parameter_hash", sa.String(length=64), nullable=False),
        sa.Column("code_version", sa.String(length=64), nullable=False),
        sa.Column("parameters_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("feature_names_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("selector_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("output_location", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_id", "name", "parameter_hash", "code_version"),
    )
    op.create_index("ix_feature_sets_dataset_id", "feature_sets", ["dataset_id"])
    op.create_index("ix_feature_sets_hash", "feature_sets", ["feature_set_hash"])
    op.create_index("ix_feature_sets_parameter_hash", "feature_sets", ["parameter_hash"])

    op.create_table(
        "feature_rows",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("feature_set_id", sa.BigInteger(), nullable=False),
        sa.Column("pair_id", sa.Integer(), nullable=False),
        sa.Column("timeframe", sa.String(length=16), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("features_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("feature_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "available_at <= decision_time",
            name="feature_row_available_before_decision",
        ),
        sa.ForeignKeyConstraint(["feature_set_id"], ["feature_sets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pair_id"], ["trading_pairs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "feature_set_id",
            "pair_id",
            "timeframe",
            "timestamp",
            "decision_time",
        ),
    )
    op.create_index(
        "ix_feature_rows_feature_set_timestamp",
        "feature_rows",
        ["feature_set_id", "timestamp"],
    )
    op.create_index(
        "ix_feature_rows_pair_timeframe_available_at",
        "feature_rows",
        ["pair_id", "timeframe", "available_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_feature_rows_pair_timeframe_available_at", table_name="feature_rows")
    op.drop_index("ix_feature_rows_feature_set_timestamp", table_name="feature_rows")
    op.drop_table("feature_rows")
    op.drop_index("ix_feature_sets_parameter_hash", table_name="feature_sets")
    op.drop_index("ix_feature_sets_hash", table_name="feature_sets")
    op.drop_index("ix_feature_sets_dataset_id", table_name="feature_sets")
    op.drop_table("feature_sets")
