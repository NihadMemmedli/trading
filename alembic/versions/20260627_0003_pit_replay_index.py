"""add point-in-time candle replay index

Revision ID: 20260627_0003
Revises: 20260627_0002
Create Date: 2026-06-27 00:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260627_0003"
down_revision: str | None = "20260627_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_candles_pit_replay",
        "candles",
        ["pair_id", "timeframe", "source", "available_at", "timestamp"],
    )


def downgrade() -> None:
    op.drop_index("ix_candles_pit_replay", table_name="candles")
