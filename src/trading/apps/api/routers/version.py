"""Version endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from trading.apps.api.dependencies import SettingsDependency
from trading.core.version import __version__

router = APIRouter(tags=["system"])


@router.get("/version")
async def version(settings: SettingsDependency) -> dict[str, str | None]:
    return {
        "app": settings.APP_NAME,
        "version": __version__,
        "environment": settings.APP_ENV,
        "git_sha": None,
    }
