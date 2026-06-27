"""store ingestion request limit

Revision ID: 20260627_0002
Revises: 20260627_0001
Create Date: 2026-06-27 00:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260627_0002"
down_revision: str | None = "20260627_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ingestion_runs",
        sa.Column("requested_limit", sa.Integer(), server_default="500", nullable=False),
    )
    op.alter_column("ingestion_runs", "requested_limit", server_default=None)


def downgrade() -> None:
    op.drop_column("ingestion_runs", "requested_limit")
