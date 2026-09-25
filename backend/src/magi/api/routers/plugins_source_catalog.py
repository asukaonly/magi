"""Source discovery for explicit browsing, independent of recommendation limits."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from magi.core.logger import get_logger
from magi.plugins.contracts import PluginManifest, PluginRegistryEntry
from magi.plugins.operation_execution import run_plugin_lifecycle_operation
from magi.system_suggestions.candidates import _candidate_icon

from .availability_routes import _get_or_create_resolver
from .plugins_common import _get_registry_client, _try_plugin_manager
from .system_suggestions_routes import _active_source_plugin_ids

logger = get_logger(__name__)
source_catalog_router = APIRouter()

SourceCatalogStatus = Literal[
    "available", "connected", "unsupported_platform", "missing_file",
    "missing_executable", "app_not_installed", "check_error", "no_descriptor",
    "review_in_settings", "setup_in_settings",
]


class SourceCatalogItem(BaseModel):
    plugin_id: str
    name: str
    name_i18n: dict[str, str] = Field(default_factory=dict)
    description: str = ""
    description_i18n: dict[str, str] = Field(default_factory=dict)
    icon: str = ""
    installed: bool
    scope: dict[str, str] | None = None
    status: SourceCatalogStatus


class SourceCatalogResponse(BaseModel):
    items: list[SourceCatalogItem]
    catalog_mode: Literal["full", "installed_only"]


@source_catalog_router.get("/source-catalog", response_model=SourceCatalogResponse)
async def list_source_catalog() -> SourceCatalogResponse:
    """List all source packages, including unavailable and same-category entries."""
    manager = _try_plugin_manager()
    packages = await run_plugin_lifecycle_operation(manager.list_packages) if manager else []
    registry_entries: list[PluginRegistryEntry] = []
    official_source = False
    catalog_mode: Literal["full", "installed_only"] = "full"
    try:
        snapshot = await _get_registry_client().fetch_snapshot()
        registry_entries = list(snapshot.index.plugins)
        official_source = snapshot.official_source
    except Exception:
        logger.warning("Source catalog registry unavailable", exc_info=True)
        catalog_mode = "installed_only"
    active_ids = await _active_source_plugin_ids()

    def read() -> SourceCatalogResponse:
        entries: dict[str, tuple[PluginManifest | PluginRegistryEntry, bool]] = {
            entry.plugin_id: (entry, False) for entry in registry_entries
        }
        entries.update({package.manifest.plugin_id: (package.manifest, True) for package in packages})
        resolver = _get_or_create_resolver()
        items: list[SourceCatalogItem] = []
        for plugin_id, (entry, installed) in entries.items():
            if "source" not in entry.contribution_types:
                continue
            descriptor = entry.suggestion_descriptor
            surface = descriptor.surfaces.first_context if descriptor else None
            if plugin_id in active_ids:
                status = "connected"
            elif not installed and not official_source:
                # Explicit browsing must not authorize probes from a custom registry.
                status = "review_in_settings"
            elif descriptor is None:
                status = "no_descriptor"
            else:
                result = resolver.evaluate_descriptor(descriptor, plugin_id=plugin_id)
                status = result.reason.value
                if result.available and (surface is None or entry.activation_flow is None):
                    status = "setup_in_settings"
            items.append(SourceCatalogItem(
                plugin_id=plugin_id, name=entry.name, name_i18n=entry.name_i18n,
                description=entry.description, description_i18n=entry.description_i18n,
                icon=_candidate_icon(entry, descriptor, installed=installed),
                installed=installed,
                scope=surface.scope.model_dump() if surface and surface.scope else None,
                status=status,
            ))
        items.sort(key=lambda item: (item.status not in {"available", "connected"}, item.name.casefold()))
        return SourceCatalogResponse(items=items, catalog_mode=catalog_mode)

    return await run_plugin_lifecycle_operation(read)
