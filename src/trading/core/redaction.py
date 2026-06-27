"""Redaction helpers for safe configuration surfaces."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

REDACTED_VALUE = "********"
SENSITIVE_KEY_MARKERS = (
    "SECRET",
    "TOKEN",
    "API_KEY",
    "PRIVATE_KEY",
    "PASSPHRASE",
    "PASSWORD",
    "DSN",
    "DATABASE_URL",
    "REDIS_URL",
    "WEBHOOK",
    "CREDENTIAL",
    "SEED",
    "MNEMONIC",
)


def is_sensitive_key(key: str) -> bool:
    upper_key = key.upper()
    return any(marker in upper_key for marker in SENSITIVE_KEY_MARKERS)


def redact_value(key: str, value: Any) -> Any:
    if is_sensitive_key(key) and value not in (None, ""):
        return REDACTED_VALUE
    return value


def redact_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
    return {key: redact_value(key, value) for key, value in values.items()}
