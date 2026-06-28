"""add dataset lineage to backtest runs

Revision ID: 20260627_0009
Revises: 20260627_0008
Create Date: 2026-06-27 03:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260627_0009"
down_revision: str | None = "20260627_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "backtest_runs",
        sa.Column("dataset_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_backtest_runs_dataset_id",
        "backtest_runs",
        "datasets",
        ["dataset_id"],
        ["id"],
    )
    op.create_index(
        "ix_backtest_runs_dataset_id",
        "backtest_runs",
        ["dataset_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_backtest_runs_dataset_id", table_name="backtest_runs")
    op.drop_constraint("fk_backtest_runs_dataset_id", "backtest_runs", type_="foreignkey")
    op.drop_column("backtest_runs", "dataset_id")
