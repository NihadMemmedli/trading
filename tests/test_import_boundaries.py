from __future__ import annotations

import importlib
import inspect
import pkgutil

import trading
from trading.data.adapters import PublicMarketDataAdapter
from trading.data.providers import ProviderDataset, require_enabled_provider

FORBIDDEN_MODULE_FRAGMENTS = (
    ".execution",
    "ccxt",
    "freqtrade",
    "hummingbot",
    "condor",
    "broker",
    "custody",
    "wallet",
)
FORBIDDEN_SYMBOL_FRAGMENTS = (
    "OrderExecutor",
    "LiveExecutor",
    "SandboxExecutor",
    "BrokerClient",
    "CustodyClient",
    "WalletClient",
)


def test_no_forbidden_runtime_modules_exist_or_import_from_trading_package() -> None:
    discovered = [
        module_info.name
        for module_info in pkgutil.walk_packages(trading.__path__, prefix="trading.")
    ]

    assert all(
        forbidden not in module_name.lower()
        for module_name in discovered
        for forbidden in FORBIDDEN_MODULE_FRAGMENTS
    )


def test_api_and_agent_modules_expose_no_executor_or_client_symbols() -> None:
    modules_to_check = [
        module_info.name
        for module_info in pkgutil.walk_packages(trading.__path__, prefix="trading.")
        if module_info.name.startswith(("trading.apps.api", "trading.agents"))
    ]

    for module_name in modules_to_check:
        module = importlib.import_module(module_name)
        exported_names = set(dir(module))
        assert exported_names.isdisjoint(FORBIDDEN_SYMBOL_FRAGMENTS)


def test_public_adapter_exports_no_private_or_execution_methods() -> None:
    method_names = {
        name
        for name, value in inspect.getmembers(PublicMarketDataAdapter, predicate=inspect.isfunction)
        if not name.startswith("_")
    }

    assert method_names == {"fetch_ohlcv", "fetch_trades", "fetch_order_book"}
    assert not any(
        fragment in method_name.lower()
        for method_name in method_names
        for fragment in ("cancel", "withdraw", "transfer", "leverage")
    )


def test_provider_registry_metadata_exposes_no_execution_or_private_credentials() -> None:
    metadata = require_enabled_provider("binance")
    metadata_values = (
        metadata.source_name,
        metadata.source_type.value,
        metadata.rate_limit_policy,
        *metadata.supported_symbols,
        *(dataset.value for dataset in metadata.supported_datasets),
    )

    assert metadata.requires_api_key is False
    assert metadata.env_keys == ()
    assert set(metadata.supported_datasets) == {
        ProviderDataset.OHLCV,
        ProviderDataset.TRADES,
        ProviderDataset.ORDER_BOOKS,
    }
    assert not any(
        fragment in value.lower()
        for value in metadata_values
        for fragment in (
            "broker",
            "custody",
            "wallet",
            "withdraw",
            "transfer",
            "leverage",
            "margin",
            "futures",
            "private",
        )
    )
