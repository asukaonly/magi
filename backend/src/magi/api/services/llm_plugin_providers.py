"""Live plugin model choices for catalog reads and configuration validation."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from ...plugins.provider import resolve_plugin_manager
from ...plugins.providers import PluginProviderRegistry


class PluginModelProviderCatalogEntry(BaseModel):
    provider_id: str
    plugin_id: str
    connection_id: str
    display_name: str
    model_selection: Literal["manual"] = "manual"


def get_plugin_model_provider_registry() -> PluginProviderRegistry | None:
    """Return no choices before the plugin runtime has been initialized."""
    try:
        return resolve_plugin_manager().provider_registry
    except RuntimeError:
        return None


def list_plugin_model_providers() -> list[PluginModelProviderCatalogEntry]:
    registry = get_plugin_model_provider_registry()
    if registry is None:
        return []
    return [
        PluginModelProviderCatalogEntry.model_validate(entry)
        for entry in registry.describe("model")
    ]
