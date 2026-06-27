"""Application settings and Phase 1 configuration gates."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from trading.core.redaction import redact_mapping
from trading.core.safety import (
    ALLOWED_TRADING_MODES,
    SafetyPolicy,
    parse_phase1_disabled_flag,
)

TradingMode = Literal["research", "backtest", "paper"]


class Settings(BaseSettings):
    """Environment-backed application configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    APP_NAME: str = "crypto-ai-trading-research"
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"

    TRADING_MODE: TradingMode = "paper"
    LIVE_TRADING_ENABLED: bool = False
    ORDER_EXECUTION_ENABLED: bool = False
    SANDBOX_ORDER_EXECUTION_ENABLED: bool = False
    REQUIRE_MANUAL_APPROVAL: bool = True

    EXCHANGE_NAME: str = ""
    EXCHANGE_USE_SANDBOX: bool = True
    EXCHANGE_BASE_URL: str = ""
    EXCHANGE_SANDBOX_BASE_URL: str = ""
    EXCHANGE_API_KEY: str = ""
    EXCHANGE_API_SECRET: str = ""
    EXCHANGE_API_PASSPHRASE: str = ""

    QUOTE_CURRENCY: str = "USDT"
    SYMBOL_ALLOWLIST: str = "BTC/USDT,ETH/USDT,SOL/USDT"
    SYMBOL_BLOCKLIST: str = ""
    MAX_SYMBOLS: int = 10

    DATA_DIR: str = "./data"
    RAW_DATA_DIR: str = "./data/raw"
    PROCESSED_DATA_DIR: str = "./data/processed"
    REPORTS_DIR: str = "./reports"

    INITIAL_CASH: float = 10000
    TAKER_FEE_BPS: float = 10
    MAKER_FEE_BPS: float = 5
    SLIPPAGE_BPS: float = 5
    MAX_POSITION_PCT: float = 10
    MAX_PORTFOLIO_DRAWDOWN_PCT: float = 10

    MAX_ORDER_NOTIONAL: float = 100
    MAX_DAILY_LOSS_PCT: float = 2
    KILL_SWITCH_ENABLED: bool = True
    ALLOW_LEVERAGE: bool = False
    ALLOW_WITHDRAWALS: bool = False
    ALLOW_CUSTODY: bool = False

    MODEL_PROVIDER: str = ""
    MODEL_NAME: str = ""
    MODEL_API_KEY: str = ""
    MODEL_TEMPERATURE: float = 0

    STRUCTURED_LOGS: bool = True
    METRICS_ENABLED: bool = False
    SENTRY_DSN: str = ""

    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 55432
    POSTGRES_DB: str = "trading"
    POSTGRES_USER: str = "trading"
    POSTGRES_PASSWORD: str = "trading"
    DATABASE_URL: str = Field(
        default="postgresql://trading:trading@localhost:55432/trading",
    )

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_URL: str = "redis://localhost:6379/0"

    @field_validator("TRADING_MODE", mode="before")
    @classmethod
    def validate_trading_mode(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("TRADING_MODE must be a string")
        normalized = value.strip().lower()
        if normalized not in ALLOWED_TRADING_MODES:
            raise ValueError(f"TRADING_MODE={value!r} is disabled or unsupported in Phase 1")
        return normalized

    @field_validator(
        "LIVE_TRADING_ENABLED",
        "ORDER_EXECUTION_ENABLED",
        "SANDBOX_ORDER_EXECUTION_ENABLED",
        "ALLOW_LEVERAGE",
        "ALLOW_WITHDRAWALS",
        "ALLOW_CUSTODY",
        mode="before",
    )
    @classmethod
    def validate_disabled_capability_flag(cls, value: object, info: Any) -> bool:
        return parse_phase1_disabled_flag(value, name=info.field_name)

    def enforce_safety_policy(self) -> None:
        SafetyPolicy(
            trading_mode=self.TRADING_MODE,
            unsafe_flags={
                "LIVE_TRADING_ENABLED": self.LIVE_TRADING_ENABLED,
                "ORDER_EXECUTION_ENABLED": self.ORDER_EXECUTION_ENABLED,
                "SANDBOX_ORDER_EXECUTION_ENABLED": self.SANDBOX_ORDER_EXECUTION_ENABLED,
                "ALLOW_LEVERAGE": self.ALLOW_LEVERAGE,
                "ALLOW_WITHDRAWALS": self.ALLOW_WITHDRAWALS,
                "ALLOW_CUSTODY": self.ALLOW_CUSTODY,
            },
        ).validate()

    @model_validator(mode="after")
    def validate_model_safety_policy(self) -> Settings:
        self.enforce_safety_policy()
        return self

    @property
    def symbol_allowlist(self) -> list[str]:
        return [symbol.strip() for symbol in self.SYMBOL_ALLOWLIST.split(",") if symbol.strip()]

    def config_summary(self) -> dict[str, Any]:
        """Return an operationally useful summary without leaking secrets."""

        raw_summary: dict[str, Any] = {
            "app": self.APP_NAME,
            "environment": self.APP_ENV,
            "trading_mode": self.TRADING_MODE,
            "capabilities": {
                "live_trading_enabled": self.LIVE_TRADING_ENABLED,
                "order_execution_enabled": self.ORDER_EXECUTION_ENABLED,
                "sandbox_order_execution_enabled": self.SANDBOX_ORDER_EXECUTION_ENABLED,
                "leverage_enabled": self.ALLOW_LEVERAGE,
                "withdrawals_enabled": self.ALLOW_WITHDRAWALS,
                "custody_enabled": self.ALLOW_CUSTODY,
            },
            "market_universe": {
                "quote_currency": self.QUOTE_CURRENCY,
                "symbol_allowlist": self.symbol_allowlist,
                "max_symbols": self.MAX_SYMBOLS,
            },
            "infrastructure": redact_mapping(
                {
                    "POSTGRES_HOST": self.POSTGRES_HOST,
                    "POSTGRES_PORT": self.POSTGRES_PORT,
                    "POSTGRES_DB": self.POSTGRES_DB,
                    "POSTGRES_USER": self.POSTGRES_USER,
                    "POSTGRES_PASSWORD": self.POSTGRES_PASSWORD,
                    "DATABASE_URL": self.DATABASE_URL,
                    "REDIS_HOST": self.REDIS_HOST,
                    "REDIS_PORT": self.REDIS_PORT,
                    "REDIS_URL": self.REDIS_URL,
                    "SENTRY_DSN": self.SENTRY_DSN,
                }
            ),
            "providers": redact_mapping(
                {
                    "EXCHANGE_NAME": self.EXCHANGE_NAME,
                    "EXCHANGE_USE_SANDBOX": self.EXCHANGE_USE_SANDBOX,
                    "EXCHANGE_BASE_URL": self.EXCHANGE_BASE_URL,
                    "EXCHANGE_SANDBOX_BASE_URL": self.EXCHANGE_SANDBOX_BASE_URL,
                    "EXCHANGE_API_KEY": self.EXCHANGE_API_KEY,
                    "EXCHANGE_API_SECRET": self.EXCHANGE_API_SECRET,
                    "EXCHANGE_API_PASSPHRASE": self.EXCHANGE_API_PASSPHRASE,
                    "MODEL_PROVIDER": self.MODEL_PROVIDER,
                    "MODEL_NAME": self.MODEL_NAME,
                    "MODEL_API_KEY": self.MODEL_API_KEY,
                }
            ),
        }
        return raw_summary


def load_settings(**overrides: Any) -> Settings:
    """Load settings with optional explicit overrides for tests and app factories."""

    try:
        return Settings(**overrides)
    except ValidationError:
        raise
