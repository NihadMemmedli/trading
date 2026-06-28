"""Provider registry metadata for public market-data sources."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading.data.market import ALLOWED_SYMBOLS, MarketDataError, validate_symbol


class SourceType(StrEnum):
    EXCHANGE = "exchange"
    DEFI = "defi"
    MARKET_DATA = "market_data"
    ANALYTICS = "analytics"
    NEWS = "news"


class ProviderDataset(StrEnum):
    OHLCV = "ohlcv"
    TRADES = "trades"
    ORDER_BOOKS = "order_books"
    DERIVATIVES_METRICS = "derivatives_metrics"
    FUNDING_RATES = "funding_rates"


class ProviderMetadata(BaseModel):
    """Declarative provider capabilities and safety gates."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_name: str = Field(min_length=1, max_length=64)
    source_type: SourceType
    enabled: bool
    requires_api_key: bool
    env_keys: tuple[str, ...]
    rate_limit_policy: str = Field(min_length=1)
    freshness_sla_seconds: Mapping[ProviderDataset, int]
    supports_backfill: bool
    supports_realtime: bool
    supported_symbols: tuple[str, ...]
    supported_datasets: tuple[ProviderDataset, ...]

    @field_validator("source_name")
    @classmethod
    def normalize_source_name(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("env_keys")
    @classmethod
    def validate_env_keys(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(key.strip().upper() for key in value)
        if any(not key for key in normalized):
            raise ValueError("env_keys cannot contain blank values")
        return normalized

    @field_validator("supported_symbols")
    @classmethod
    def validate_supported_symbols(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("supported_symbols cannot be empty")
        return tuple(validate_symbol(symbol) for symbol in value)

    @field_validator("supported_datasets")
    @classmethod
    def validate_supported_datasets(
        cls,
        value: tuple[ProviderDataset, ...],
    ) -> tuple[ProviderDataset, ...]:
        if not value:
            raise ValueError("supported_datasets cannot be empty")
        return value

    @model_validator(mode="after")
    def validate_metadata_contract(self) -> Self:
        if self.requires_api_key and not self.env_keys:
            raise ValueError("providers requiring API keys must declare env_keys")

        supported_datasets = set(self.supported_datasets)
        freshness_datasets = set(self.freshness_sla_seconds)
        if freshness_datasets != supported_datasets:
            raise ValueError("freshness_sla_seconds must cover each supported dataset exactly")

        for dataset, seconds in self.freshness_sla_seconds.items():
            if seconds <= 0:
                raise ValueError(f"{dataset} freshness SLA must be positive")

        return self

    def supports_dataset(self, dataset: ProviderDataset) -> bool:
        return dataset in self.supported_datasets


BINANCE_PUBLIC_SPOT_METADATA = ProviderMetadata(
    source_name="binance",
    source_type=SourceType.EXCHANGE,
    enabled=True,
    requires_api_key=False,
    env_keys=(),
    rate_limit_policy="ccxt_enable_rate_limit_public_spot",
    freshness_sla_seconds={
        ProviderDataset.OHLCV: 120,
        ProviderDataset.TRADES: 300,
        ProviderDataset.ORDER_BOOKS: 30,
    },
    supports_backfill=True,
    supports_realtime=False,
    supported_symbols=tuple(sorted(ALLOWED_SYMBOLS)),
    supported_datasets=(
        ProviderDataset.OHLCV,
        ProviderDataset.TRADES,
        ProviderDataset.ORDER_BOOKS,
    ),
)

PUBLIC_PROVIDER_REGISTRY: Mapping[str, ProviderMetadata] = {
    BINANCE_PUBLIC_SPOT_METADATA.source_name: BINANCE_PUBLIC_SPOT_METADATA,
}


def normalize_provider_name(source_name: str) -> str:
    normalized = source_name.strip().lower()
    if not normalized:
        raise MarketDataError("provider source name cannot be blank")
    return normalized


def list_provider_metadata(
    registry: Mapping[str, ProviderMetadata] = PUBLIC_PROVIDER_REGISTRY,
) -> tuple[ProviderMetadata, ...]:
    return tuple(registry[name] for name in sorted(registry))


def get_provider_metadata(
    source_name: str,
    registry: Mapping[str, ProviderMetadata] = PUBLIC_PROVIDER_REGISTRY,
) -> ProviderMetadata:
    normalized = normalize_provider_name(source_name)
    metadata = registry.get(normalized)
    if metadata is None:
        raise MarketDataError(f"unsupported data provider: {normalized}")
    return metadata


def require_enabled_provider(
    source_name: str,
    registry: Mapping[str, ProviderMetadata] = PUBLIC_PROVIDER_REGISTRY,
) -> ProviderMetadata:
    metadata = get_provider_metadata(source_name, registry=registry)
    if not metadata.enabled:
        raise MarketDataError(f"data provider is disabled: {metadata.source_name}")
    return metadata


def enabled_provider_metadata(
    registry: Mapping[str, ProviderMetadata] = PUBLIC_PROVIDER_REGISTRY,
) -> tuple[ProviderMetadata, ...]:
    return tuple(metadata for metadata in list_provider_metadata(registry) if metadata.enabled)


def enabled_public_exchange_names(
    registry: Mapping[str, ProviderMetadata] = PUBLIC_PROVIDER_REGISTRY,
) -> tuple[str, ...]:
    return tuple(
        metadata.source_name
        for metadata in enabled_provider_metadata(registry)
        if metadata.source_type == SourceType.EXCHANGE
    )
