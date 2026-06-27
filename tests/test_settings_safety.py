from __future__ import annotations

import pytest
from pydantic import ValidationError

from trading.core.settings import Settings

UNSAFE_FLAGS = (
    "LIVE_TRADING_ENABLED",
    "ORDER_EXECUTION_ENABLED",
    "SANDBOX_ORDER_EXECUTION_ENABLED",
    "ALLOW_LEVERAGE",
    "ALLOW_WITHDRAWALS",
    "ALLOW_CUSTODY",
)


def test_defaults_disable_unsafe_capabilities() -> None:
    settings = Settings()

    assert settings.TRADING_MODE == "paper"
    for flag_name in UNSAFE_FLAGS:
        assert getattr(settings, flag_name) is False


@pytest.mark.parametrize("truthy", ["true", "1", "yes", "on", "TRUE", True])
@pytest.mark.parametrize("flag_name", UNSAFE_FLAGS)
def test_truthy_unsafe_flags_fail_validation(flag_name: str, truthy: str | bool) -> None:
    with pytest.raises(ValidationError):
        Settings(**{flag_name: truthy})


@pytest.mark.parametrize("mode", ["research", "backtest", "paper"])
def test_allowed_trading_modes(mode: str) -> None:
    settings = Settings(TRADING_MODE=mode)

    assert settings.TRADING_MODE == mode


@pytest.mark.parametrize(
    "mode",
    [
        "live",
        "sandbox",
        "margin",
        "futures",
        "perps",
        "options",
        "withdrawal",
        "custody",
        "unknown",
    ],
)
def test_disallowed_and_unknown_trading_modes_fail(mode: str) -> None:
    with pytest.raises(ValidationError):
        Settings(TRADING_MODE=mode)
