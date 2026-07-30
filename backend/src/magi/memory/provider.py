"""Container-backed providers for memory-domain runtime services."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ..core.container import get_container

if TYPE_CHECKING:
    from . import UnifiedMemoryStore
    from .hybrid_retrieval.service import HybridRetrievalService
    from .integration import MemoryIntegrationModule
    from .manual_entries import (
        ManualEntryAssetStore,
        ManualEntryStore,
        WeatherFetcher,
    )


def _require_memory_binding(provider_name: str) -> Any:
    provider = getattr(get_container(), provider_name)
    instance = provider()
    if instance is None:
        raise RuntimeError(f"{provider_name} binding is not initialized")
    if type(instance).__name__ == "object" and not provider.overridden:
        raise RuntimeError(f"{provider_name} binding is not initialized")
    return instance


def get_memory_integration() -> "MemoryIntegrationModule":
    """Return the active memory integration binding."""
    return cast("MemoryIntegrationModule", _require_memory_binding("memory_integration"))


def get_unified_memory() -> "UnifiedMemoryStore":
    """Return the active unified memory binding."""
    return cast("UnifiedMemoryStore", _require_memory_binding("unified_memory"))


def get_hybrid_retrieval_service() -> "HybridRetrievalService":
    """Return the active hybrid retrieval service binding."""
    return cast("HybridRetrievalService", _require_memory_binding("hybrid_retrieval_service"))


def get_manual_entry_store() -> "ManualEntryStore":
    """Return the active manual-entry store binding."""
    return cast("ManualEntryStore", _require_memory_binding("manual_entry_store"))


def get_manual_entry_asset_store() -> "ManualEntryAssetStore":
    """Return the active manual-entry asset-store binding."""
    return cast("ManualEntryAssetStore", _require_memory_binding("manual_entry_asset_store"))


def get_manual_entry_weather_fetcher() -> "WeatherFetcher":
    """Return the active manual-entry weather-fetcher binding."""
    return cast("WeatherFetcher", _require_memory_binding("manual_entry_weather_fetcher"))


def get_history_import_service() -> Any:
    """Return the active one-shot history import service."""

    return _require_memory_binding("history_import_service")
