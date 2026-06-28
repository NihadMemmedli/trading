"""add prediction and label contract

Revision ID: 20260628_0014
Revises: 20260627_0013
Create Date: 2026-06-28 16:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260628_0014"
down_revision: str | None = "20260627_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "labels",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("dataset_id", sa.BigInteger(), nullable=False),
        sa.Column("feature_set_id", sa.BigInteger(), nullable=False),
        sa.Column("feature_row_id", sa.BigInteger(), nullable=False),
        sa.Column("pair_id", sa.Integer(), nullable=False),
        sa.Column("timeframe", sa.String(length=16), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("feature_hash", sa.String(length=64), nullable=False),
        sa.Column("label_name", sa.String(length=128), nullable=False),
        sa.Column("label_value_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("label_hash", sa.String(length=64), nullable=False),
        sa.Column("decision_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "observed_at >= decision_time",
            name="label_observed_after_decision",
        ),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"]),
        sa.ForeignKeyConstraint(["feature_set_id"], ["feature_sets.id"]),
        sa.ForeignKeyConstraint(
            ["feature_row_id"],
            ["feature_rows.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["pair_id"], ["trading_pairs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("feature_set_id", "feature_row_id", "label_name"),
    )
    op.create_index("ix_labels_dataset_feature_set", "labels", ["dataset_id", "feature_set_id"])
    op.create_index("ix_labels_feature_row_id", "labels", ["feature_row_id"])
    op.create_index(
        "ix_labels_pair_timeframe_timestamp",
        "labels",
        ["pair_id", "timeframe", "timestamp"],
    )
    op.create_index("ix_labels_hash", "labels", ["label_hash"])

    op.create_table(
        "model_predictions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("model_experiment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_id", sa.BigInteger(), nullable=False),
        sa.Column("feature_set_id", sa.BigInteger(), nullable=False),
        sa.Column("split_definition_id", sa.BigInteger(), nullable=False),
        sa.Column("feature_row_id", sa.BigInteger(), nullable=False),
        sa.Column("pair_id", sa.Integer(), nullable=False),
        sa.Column("timeframe", sa.String(length=16), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("feature_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "prediction_value_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("confidence", sa.Numeric(38, 18), nullable=False),
        sa.Column("decision_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("feature_row_decision_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prediction_hash", sa.String(length=64), nullable=False),
        sa.Column("lineage_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="model_prediction_confidence_valid",
        ),
        sa.CheckConstraint(
            "decision_time >= feature_row_decision_time",
            name="model_prediction_after_feature_decision",
        ),
        sa.ForeignKeyConstraint(
            ["model_experiment_id"],
            ["model_experiments.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"]),
        sa.ForeignKeyConstraint(["feature_set_id"], ["feature_sets.id"]),
        sa.ForeignKeyConstraint(["split_definition_id"], ["split_definitions.id"]),
        sa.ForeignKeyConstraint(
            ["feature_row_id"],
            ["feature_rows.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["pair_id"], ["trading_pairs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_experiment_id", "feature_row_id", "prediction_hash"),
    )
    op.create_index(
        "ix_model_predictions_experiment_decision",
        "model_predictions",
        ["model_experiment_id", "decision_time"],
    )
    op.create_index(
        "ix_model_predictions_feature_set_row",
        "model_predictions",
        ["feature_set_id", "feature_row_id"],
    )
    op.create_index("ix_model_predictions_hash", "model_predictions", ["prediction_hash"])


def downgrade() -> None:
    op.drop_index("ix_model_predictions_hash", table_name="model_predictions")
    op.drop_index("ix_model_predictions_feature_set_row", table_name="model_predictions")
    op.drop_index("ix_model_predictions_experiment_decision", table_name="model_predictions")
    op.drop_table("model_predictions")
    op.drop_index("ix_labels_hash", table_name="labels")
    op.drop_index("ix_labels_pair_timeframe_timestamp", table_name="labels")
    op.drop_index("ix_labels_feature_row_id", table_name="labels")
    op.drop_index("ix_labels_dataset_feature_set", table_name="labels")
    op.drop_table("labels")
