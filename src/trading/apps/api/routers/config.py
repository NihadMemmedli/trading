"""Safe configuration summary endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from trading.apps.api.dependencies import SettingsDependency

router = APIRouter(prefix="/config", tags=["config"])


@router.get("/summary")
async def config_summary(settings: SettingsDependency) -> dict[str, Any]:
    return settings.config_summary()
