"""Plugin registry and update routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from ... import i18n as core_i18n
from .plugins_common import legacy_plugins_module
from .plugins_install_jobs import plugin_install_jobs
from .plugins_schemas import (
    PluginInstallJobSnapshot,
    PluginPackageResponse,
    PluginRegistryEntryResponse,
    PluginRegistryResponse,
    PluginUpdateCheckResponse,
)

plugins_registry_router = APIRouter()


@plugins_registry_router.get("/registry", response_model=PluginRegistryResponse)
async def list_registry_plugins(
    include: str | None = Query(
        default=None,
        description=(
            "Comma-separated extras to include. Pass 'libraries' to also "
            "return library packages (hidden by default since they are "
            "installed automatically as dependencies, not by user choice)."
        ),
    ),
    refresh: bool = Query(
        default=False,
        description=(
            "Bypass the registry client's in-memory TTL cache and re-fetch "
            "the index from the remote source. Wired to the marketplace "
            "'refresh' button so a freshly published version shows up "
            "immediately instead of after the cache expires."
        ),
    ),
):
    """List all available plugins from the remote registry."""
    legacy = legacy_plugins_module()
    manager = legacy._try_plugin_manager()
    registry = legacy._get_registry_client()
    try:
        index = await registry.fetch_index(force=refresh)
    except Exception as exc:
        legacy.logger.exception("Failed to fetch plugin registry")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=core_i18n.t(
                "plugins.errors.registry_unreachable", fallback="Unable to reach plugin registry"
            ),
        ) from exc

    include_set = {p.strip() for p in (include or "").split(",") if p.strip()}
    include_libraries = "libraries" in include_set

    result: list[PluginRegistryEntryResponse] = []
    for entry in index.plugins:
        if entry.kind == "library" and not include_libraries:
            continue
        installed_version = manager.check_installed_version(entry.plugin_id) if manager else None
        installed = installed_version is not None
        update_available = False
        if installed and installed_version:
            update_available = legacy._version_newer(entry.version, installed_version)
        result.append(
            PluginRegistryEntryResponse(
                plugin_id=entry.plugin_id,
                name=entry.name,
                name_i18n=entry.name_i18n,
                version=entry.version,
                description=entry.description,
                description_i18n=entry.description_i18n,
                author=entry.author,
                official=entry.official,
                data_locality=entry.data_locality,
                contribution_types=entry.contribution_types,
                platforms=entry.platforms,
                min_sdk_version=entry.min_sdk_version,
                homepage=entry.homepage,
                repository=entry.repository,
                path=entry.path,
                installed=installed,
                installed_version=installed_version,
                update_available=update_available,
                capabilities=entry.capabilities,
            )
        )
    return PluginRegistryResponse(plugins=result, registry_version=index.registry_version)


@plugins_registry_router.get("/updates", response_model=list[PluginUpdateCheckResponse])
async def check_plugin_updates():
    """Check all installed plugins for available updates."""
    legacy = legacy_plugins_module()
    manager = legacy.resolve_plugin_manager()
    registry = legacy._get_registry_client()

    installed = {
        state.manifest.plugin_id: state.manifest.version
        for state in manager.list_packages()
        if state.manifest.source != "builtin"
    }
    if not installed:
        return []

    try:
        update_entries = await registry.check_updates(installed)
    except Exception as exc:
        legacy.logger.warning("Failed to check plugin updates", extra={"error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=core_i18n.t(
                "plugins.errors.registry_unreachable", fallback="Unable to reach plugin registry"
            ),
        ) from exc

    return [
        PluginUpdateCheckResponse(
            plugin_id=entry.plugin_id,
            current_version=installed[entry.plugin_id],
            latest_version=entry.version,
            update_available=True,
        )
        for entry in update_entries
    ]


@plugins_registry_router.post("/{plugin_id}/update", response_model=PluginPackageResponse)
async def update_plugin(plugin_id: str):
    """Update a plugin to the latest version from the registry."""
    legacy = legacy_plugins_module()
    manager, state = legacy._require_package(plugin_id)
    if state.manifest.source == "builtin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=core_i18n.t(
                "plugins.errors.cannot_update_builtin", fallback="Cannot update builtin plugins"
            ),
        )

    registry = legacy._get_registry_client()
    entry = await registry.fetch_entry(plugin_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=core_i18n.t(
                "plugins.errors.not_found_in_registry", fallback="Plugin not found in registry"
            ),
        )

    try:
        plugin_dir = await registry.clone_plugin(entry)
        new_state = manager.install_plugin_from_directory(plugin_dir)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    from ...config import save_config

    save_config(
        {
            f"plugins.packages.{plugin_id}.consented_capabilities": [
                c.model_dump() for c in entry.capabilities
            ]
        }
    )
    return legacy._serialize_package(new_state)


@plugins_registry_router.post("/{plugin_id}/update/jobs", response_model=PluginInstallJobSnapshot)
async def start_plugin_update_job(plugin_id: str):
    """Start a background plugin update job from the registry."""
    return plugin_install_jobs.start_registry_update(plugin_id)


__all__ = [
    "check_plugin_updates",
    "list_registry_plugins",
    "plugins_registry_router",
    "start_plugin_update_job",
    "update_plugin",
]
