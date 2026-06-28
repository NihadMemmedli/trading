"""Agent report API."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from trading.agents.contracts import AnalystReportPayload
from trading.apps.api.dependencies import AgentSignalServiceDependency
from trading.apps.api.schemas.agent_signals import (
    AnalystReportListResponse,
    AnalystReportResponse,
)
from trading.data.market import MarketDataError, validate_symbol
from trading.services.agent_signals import AgentReportNotFoundError, SignalValidationError

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post(
    "/reports",
    response_model=AnalystReportResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_analyst_report(
    payload: AnalystReportPayload,
    service: AgentSignalServiceDependency,
) -> AnalystReportResponse:
    try:
        report = service.create_analyst_report(payload)
    except SignalValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return AnalystReportResponse.from_report(report)


@router.get("/reports/{report_id}", response_model=AnalystReportResponse)
def get_analyst_report(
    report_id: uuid.UUID,
    service: AgentSignalServiceDependency,
) -> AnalystReportResponse:
    try:
        report = service.get_analyst_report(report_id)
    except AgentReportNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="agent report not found",
        ) from exc
    return AnalystReportResponse.from_report(report)


@router.get("/reports", response_model=AnalystReportListResponse)
def list_analyst_reports(
    service: AgentSignalServiceDependency,
    symbol: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AnalystReportListResponse:
    try:
        normalized_symbol = validate_symbol(symbol) if symbol is not None else None
    except MarketDataError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    reports = [
        AnalystReportResponse.from_report(report)
        for report in service.list_analyst_reports(symbol=normalized_symbol, limit=limit)
    ]
    return AnalystReportListResponse(reports=reports)
