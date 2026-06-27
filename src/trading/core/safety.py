"""Phase 1 safety invariants."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

ALLOWED_TRADING_MODES = frozenset({"research", "backtest", "paper"})
DISALLOWED_TRADING_MODES = frozenset(
    {"live", "sandbox", "margin", "futures", "perps", "options", "withdrawal", "custody"}
)
UNSAFE_FLAG_NAMES = (
    "LIVE_TRADING_ENABLED",
    "ORDER_EXECUTION_ENABLED",
    "SANDBOX_ORDER_EXECUTION_ENABLED",
    "ALLOW_LEVERAGE",
    "ALLOW_WITHDRAWALS",
    "ALLOW_CUSTODY",
)
TRUTHY_VALUES = frozenset({"1", "true", "t", "yes", "y", "on"})
FALSY_VALUES = frozenset({"0", "false", "f", "no", "n", "off"})


class SafetyPolicyError(ValueError):
    """Raised when configuration violates Phase 1 safety invariants."""


@dataclass(frozen=True)
class SafetyPolicy:
    """Validates that Phase 1 remains research/backtest/paper only."""

    trading_mode: str
    unsafe_flags: Mapping[str, bool]

    def validate(self) -> None:
        mode = self.trading_mode.strip().lower()
        if mode not in ALLOWED_TRADING_MODES:
            if mode in DISALLOWED_TRADING_MODES:
                raise SafetyPolicyError(f"TRADING_MODE={mode!r} is disabled in Phase 1")
            raise SafetyPolicyError(f"TRADING_MODE={self.trading_mode!r} is not supported")

        enabled_flags = [name for name, enabled in self.unsafe_flags.items() if enabled]
        if enabled_flags:
            joined = ", ".join(enabled_flags)
            raise SafetyPolicyError(f"Unsafe Phase 1 capability flag enabled: {joined}")


def parse_phase1_disabled_flag(value: object, *, name: str) -> bool:
    """Parse an unsafe flag and fail if it is enabled or not a clear boolean."""

    if isinstance(value, bool):
        parsed = value
    elif isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in TRUTHY_VALUES:
            parsed = True
        elif normalized in FALSY_VALUES:
            parsed = False
        else:
            raise ValueError(f"{name} must be a boolean-like value")
    else:
        raise ValueError(f"{name} must be a boolean-like value")

    if parsed:
        raise ValueError(f"{name} is disabled in Phase 1 and must be false")
    return False
