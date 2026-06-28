"""add model split and experiment spine

Revision ID: 20260627_0013
Revises: 20260627_0012
Create Date: 2026-06-27 07:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260627_0013"
down_revision: str | None = "20260627_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "split_definitions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("dataset_id", sa.BigInteger(), nullable=False),
        sa.Column("feature_set_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("split_type", sa.String(length=32), nullable=False),
        sa.Column("split_hash", sa.String(length=64), nullable=False),
        sa.Column("config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "split_type IN ('holdout', 'walk_forward')",
            name="split_definition_type_valid",
        ),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"]),
        sa.ForeignKeyConstraint(["feature_set_id"], ["feature_sets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_id", "feature_set_id", "name", "split_hash"),
    )
    op.create_index(
        "ix_split_definitions_dataset_feature_set",
        "split_definitions",
        ["dataset_id", "feature_set_id"],
    )
    op.create_index("ix_split_definitions_hash", "split_definitions", ["split_hash"])

    op.create_table(
        "split_windows",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("split_definition_id", sa.BigInteger(), nullable=False),
        sa.Column("window_index", sa.Integer(), nullable=False),
        sa.Column("split_name", sa.String(length=32), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "split_name IN ('train', 'validation', 'test')",
            name="split_window_name_valid",
        ),
        sa.CheckConstraint("window_index >= 0", name="split_window_index_nonnegative"),
        sa.CheckConstraint("start_at < end_at", name="split_window_range_valid"),
        sa.CheckConstraint(
            "end_at <= decision_time",
            name="split_window_decision_time_valid",
        ),
        sa.ForeignKeyConstraint(
            ["split_definition_id"],
            ["split_definitions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("split_definition_id", "window_index", "split_name"),
    )
    op.create_index(
        "ix_split_windows_definition_index_name",
        "split_windows",
        ["split_definition_id", "window_index", "split_name"],
    )

    op.create_table(
        "model_experiments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_id", sa.BigInteger(), nullable=False),
        sa.Column("feature_set_id", sa.BigInteger(), nullable=False),
        sa.Column("split_definition_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("parameter_hash", sa.String(length=64), nullable=False),
        sa.Column("experiment_hash", sa.String(length=64), nullable=False),
        sa.Column("code_version", sa.String(length=64), nullable=False),
        sa.Column("parameters_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metrics_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('created', 'running', 'succeeded', 'failed')",
            name="model_experiment_status_valid",
        ),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"]),
        sa.ForeignKeyConstraint(["feature_set_id"], ["feature_sets.id"]),
        sa.ForeignKeyConstraint(["split_definition_id"], ["split_definitions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_model_experiments_dataset_feature_set",
        "model_experiments",
        ["dataset_id", "feature_set_id"],
    )
    op.create_index(
        "ix_model_experiments_split_definition_id",
        "model_experiments",
        ["split_definition_id"],
    )
    op.create_index(
        "ix_model_experiments_status_created_at",
        "model_experiments",
        ["status", "created_at"],
    )
    op.create_index("ix_model_experiments_hash", "model_experiments", ["experiment_hash"])


def downgrade() -> None:
    op.drop_index("ix_model_experiments_hash", table_name="model_experiments")
    op.drop_index("ix_model_experiments_status_created_at", table_name="model_experiments")
    op.drop_index("ix_model_experiments_split_definition_id", table_name="model_experiments")
    op.drop_index("ix_model_experiments_dataset_feature_set", table_name="model_experiments")
    op.drop_table("model_experiments")
    op.drop_index("ix_split_windows_definition_index_name", table_name="split_windows")
    op.drop_table("split_windows")
    op.drop_index("ix_split_definitions_hash", table_name="split_definitions")
    op.drop_index(
        "ix_split_definitions_dataset_feature_set",
        table_name="split_definitions",
    )
    op.drop_table("split_definitions")
