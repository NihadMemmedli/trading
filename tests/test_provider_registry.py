from __future__ import annotations

import pytest

from trading.data.market import ALLOWED_SYMBOLS, MarketDataError
from trading.data.providers import (
    BINANCE_PUBLIC_SPOT_METADATA,
    ProviderDataset,
    ProviderMetadata,
    SourceType,
    enabled_provider_metadata,
    enabled_public_exchange_names,
    get_provider_metadata,
    require_enabled_provider,
)


def test_provider_metadata_contract_shape_is_explicit() -> None:
    assert set(ProviderMetadata.model_fields) == {
        "source_name",
        "source_type",
        "enabled",
        "requires_api_key",
        "env_keys",
        "rate_limit_policy",
        "freshness_sla_seconds",
        "supports_backfill",
        "supports_realtime",
        "supported_symbols",
        "supported_datasets",
    }


def test_binance_public_spot_metadata_defaults() -> None:
    metadata = get_provider_metadata(" BINANCE ")

    assert metadata == BINANCE_PUBLIC_SPOT_METADATA
    assert metadata.source_name == "binance"
    assert metadata.source_type == SourceType.EXCHANGE
    assert metadata.enabled is True
    assert metadata.rate_limit_policy == "ccxt_enable_rate_limit_public_spot"
    assert metadata.supports_backfill is True
    assert metadata.supports_realtime is False
    assert metadata.supported_symbols == tuple(sorted(ALLOWED_SYMBOLS))
    assert metadata.supported_datasets == (
        ProviderDataset.OHLCV,
        ProviderDataset.TRADES,
        ProviderDataset.ORDER_BOOKS,
    )
    assert not metadata.supports_dataset(ProviderDataset.DERIVATIVES_METRICS)
    assert not metadata.supports_dataset(ProviderDataset.FUNDING_RATES)
    assert metadata.freshness_sla_seconds == {
        ProviderDataset.OHLCV: 120,
        ProviderDataset.TRADES: 300,
        ProviderDataset.ORDER_BOOKS: 30,
    }
    assert metadata.supports_dataset(ProviderDataset.ORDER_BOOKS)


def test_binance_public_spot_requires_no_private_env_keys() -> None:
    metadata = require_enabled_provider("binance")

    assert metadata.requires_api_key is False
    assert metadata.env_keys == ()


def test_unsupported_provider_fails_closed() -> None:
    with pytest.raises(MarketDataError, match="unsupported data provider: kraken"):
        get_provider_metadata("kraken")

    with pytest.raises(MarketDataError, match="provider source name cannot be blank"):
        get_provider_metadata(" ")


def test_disabled_provider_is_visible_but_not_enabled() -> None:
    disabled = BINANCE_PUBLIC_SPOT_METADATA.model_copy(update={"enabled": False})
    registry = {"binance": disabled}

    assert get_provider_metadata("binance", registry=registry).enabled is False
    assert enabled_provider_metadata(registry) == ()
    assert enabled_public_exchange_names(registry) == ()

    with pytest.raises(MarketDataError, match="data provider is disabled: binance"):
        require_enabled_provider("binance", registry=registry)
