"""Pydantic schemas for registered dataset endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DatasetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    dataset_hash: str
    decision_time: datetime
    artifact_id: int | None
    created_at: datetime
    backtest_run_count: int


class DatasetListResponse(BaseModel):
    datasets: list[DatasetResponse] = Field(default_factory=list)
