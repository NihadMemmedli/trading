from __future__ import annotations

import importlib
import inspect
import pkgutil

import trading
from trading.data.adapters import PublicMarketDataAdapter

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

    assert method_names == {"fetch_ohlcv"}
    assert not any(
        fragment in method_name.lower()
        for method_name in method_names
        for fragment in ("order", "cancel", "withdraw", "transfer", "leverage")
    )
