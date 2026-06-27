"""Pydantic schemas for ingestion API endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from trading.data.market import IngestionStatus, OhlcvRequest


class OhlcvIngestionRequest(OhlcvRequest):
    """API request body for public OHLCV ingestion metadata."""


class IngestionRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    exchange: str
    symbol: str
    timeframe: str
    status: IngestionStatus
    requested_since: datetime | None
    requested_until: datetime | None
    requested_limit: int
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    rows_raw: int
    rows_normalized: int
    created_at: datetime
    updated_at: datetime


class IngestionRunListResponse(BaseModel):
    runs: list[IngestionRunResponse] = Field(default_factory=list)
