"""Plugin registry and update routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, status

from ... import i18n as core_i18n
from ...plugins.contracts import PluginIdentifier
from ...plugins.install_admission import (
    PluginInstallCapacityError,
    PluginInstallConflictError,
)
from ...plugins.dependency_installation import (
    DependencyInstallResourceLimitError,
    PluginInstallWorkflowTimeoutError,
)
from ...plugins.install_service import (
    BuiltinPluginUpdateError,
    PluginDependencyConflictError,
    PluginPackageConflictError,
    PluginPackageNotInstalled,
    PluginRegistryEntryNotFound,
    PluginRegistrySourceConflictError,
    PluginRegistrySnapshotMismatchError,
    registry_source_matches_installed_package,
)
from ...plugins.icon_assets import sanitize_lucide_icon, sanitize_registry_icon
from .plugins_common import (
    _get_registry_client,
    _plugin_install_service,
    _require_plugin_manager,
    _serialize_package,
    _try_plugin_manager,
    _version_newer,
)
from .plugins_install_jobs import (
    PluginInstallJobCapacityError,
    PluginInstallJobConflictError,
    plugin_install_jobs,
)
from .plugins_schemas import (
    PluginInstallJobSnapshot,
    PluginPackageResponse,
    PluginRegistryApprovalRequest,
    PluginRegistryEntryResponse,
    PluginRegistryResponse,
    PluginUpdateCheckResponse,
)

plugins_registry_router = APIRouter()
logger = logging.getLogger(__name__)


def _safe_registry_display_group(display_group):
    if display_group is None:
        return None
    if isinstance(display_group, dict):
        return {
            **display_group,
            "icon": sanitize_lucide_icon(str(display_group.get("icon", "") or "")),
        }
    return display_group.model_copy(
        update={"icon": sanitize_lucide_icon(str(getattr(display_group, "icon", "") or ""))}
    )


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
    manager = _try_plugin_manager()
    registry = _get_registry_client()
    try:
        snapshot = await registry.fetch_snapshot(force=refresh)
    except Exception as exc:
        logger.exception("Failed to fetch plugin registry")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=core_i18n.t(
                "plugins.errors.registry_unreachable", fallback="Unable to reach plugin registry"
            ),
        ) from exc

    include_set = {p.strip() for p in (include or "").split(",") if p.strip()}
    include_libraries = "libraries" in include_set

    result: list[PluginRegistryEntryResponse] = []
    index = snapshot.index
    for entry in index.plugins:
        if entry.kind == "library" and not include_libraries:
            continue
        installed_version = manager.check_installed_version(entry.plugin_id) if manager else None
        installed = installed_version is not None
        update_available = False
        if (
            installed
            and installed_version
            and manager is not None
            and (installed_state := manager.get_package(entry.plugin_id)) is not None
            and registry_source_matches_installed_package(
                installed_state,
                snapshot,
            )
        ):
            update_available = _version_newer(entry.version, installed_version)
        result.append(
            PluginRegistryEntryResponse(
                plugin_id=entry.plugin_id,
                name=entry.name,
                name_i18n=entry.name_i18n,
                version=entry.version,
                description=entry.description,
                description_i18n=entry.description_i18n,
                author=entry.author,
                icon=sanitize_registry_icon(
                    str(getattr(entry, "icon_data", "") or ""),
                    str(entry.icon or ""),
                ),
                display_group=_safe_registry_display_group(getattr(entry, "display_group", None)),
                official=bool(snapshot.official_source and entry.official),
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
    return PluginRegistryResponse(
        plugins=result,
        registry_version=index.registry_version,
        install_fingerprint=snapshot.install_fingerprint,
    )


@plugins_registry_router.get("/updates", response_model=list[PluginUpdateCheckResponse])
async def check_plugin_updates():
    """Check all installed plugins for available updates."""
    manager = _require_plugin_manager()
    registry = _get_registry_client()

    all_installed = {
        state.manifest.plugin_id: state.manifest.version
        for state in manager.list_packages()
        if state.manifest.source != "builtin"
    }
    if not all_installed:
        return []

    try:
        snapshot = await registry.fetch_snapshot()
    except Exception as exc:
        logger.warning("Failed to check plugin updates", extra={"error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=core_i18n.t(
                "plugins.errors.registry_unreachable", fallback="Unable to reach plugin registry"
            ),
        ) from exc

    installed = {}
    for state in manager.list_packages():
        plugin_id = state.manifest.plugin_id
        if plugin_id not in all_installed:
            continue
        if registry_source_matches_installed_package(state, snapshot):
            installed[plugin_id] = state.manifest.version
    if not installed:
        return []
    update_entries = [
        entry
        for entry in snapshot.index.plugins
        if entry.plugin_id in installed
        and _version_newer(entry.version, installed[entry.plugin_id])
    ]

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
async def update_plugin(
    plugin_id: PluginIdentifier,
    request: PluginRegistryApprovalRequest,
):
    """Update a plugin to the latest version from the registry."""
    manager = _require_plugin_manager()
    install_service = _plugin_install_service(manager)

    try:
        new_state = await install_service.update_from_registry(
            plugin_id,
            expected_fingerprint=request.expected_fingerprint,
        )
    except PluginPackageNotInstalled as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=core_i18n.t("plugins.errors.not_found", fallback="Plugin not found"),
        ) from exc
    except BuiltinPluginUpdateError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=core_i18n.t(
                "plugins.errors.cannot_update_builtin", fallback="Cannot update builtin plugins"
            ),
        ) from exc
    except PluginRegistryEntryNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=core_i18n.t(
                "plugins.errors.not_found_in_registry", fallback="Plugin not found in registry"
            ),
        ) from exc
    except PluginInstallCapacityError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=core_i18n.t(
                "plugins.errors.install_job_capacity",
                fallback="Too many plugin installations are already active",
            ),
        ) from exc
    except PluginInstallConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=core_i18n.t(
                "plugins.errors.install_job_conflict",
                fallback="This plugin already has an active installation",
            ),
        ) from exc
    except PluginRegistrySnapshotMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": core_i18n.t(
                    "plugins.errors.registry_changed",
                    fallback="Marketplace information changed. Review it again before continuing.",
                ),
                "error_code": "PLUGIN_REGISTRY_CHANGED",
            },
        ) from exc
    except PluginDependencyConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=core_i18n.t(
                "plugins.errors.dependency_conflict",
                fallback=str(exc),
            ),
        ) from exc
    except (PluginPackageConflictError, PluginRegistrySourceConflictError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=core_i18n.t(
                "plugins.errors.package_source_conflict",
                fallback=str(exc),
            ),
        ) from exc
    except PluginInstallWorkflowTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={
                "message": core_i18n.t(
                    "plugins.errors.install_timeout",
                    fallback="Plugin installation took too long and was stopped",
                ),
                "error_code": "PLUGIN_INSTALL_TIMEOUT",
            },
        ) from exc
    except DependencyInstallResourceLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": core_i18n.t(
                    "plugins.errors.install_resource_limit",
                    fallback="Plugin installation exceeded the allowed resource limit",
                ),
                "error_code": "PLUGIN_INSTALL_RESOURCE_LIMIT",
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc
    return _serialize_package(new_state)


@plugins_registry_router.post("/{plugin_id}/update/jobs", response_model=PluginInstallJobSnapshot)
async def start_plugin_update_job(
    plugin_id: PluginIdentifier,
    request: PluginRegistryApprovalRequest,
):
    """Start a background plugin update job from the registry."""
    try:
        return await plugin_install_jobs.start_registry_update(
            plugin_id,
            expected_fingerprint=request.expected_fingerprint,
        )
    except PluginInstallJobCapacityError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=core_i18n.t(
                "plugins.errors.install_job_capacity",
                fallback="Too many plugin installations are already active",
            ),
        ) from exc
    except PluginInstallJobConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=core_i18n.t(
                "plugins.errors.install_job_conflict",
                fallback="This plugin already has an active installation",
            ),
        ) from exc
    except PluginRegistrySnapshotMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": core_i18n.t(
                    "plugins.errors.registry_changed",
                    fallback="Marketplace information changed. Review it again before continuing.",
                ),
                "error_code": "PLUGIN_REGISTRY_CHANGED",
            },
        ) from exc


__all__ = [
    "check_plugin_updates",
    "list_registry_plugins",
    "plugins_registry_router",
    "start_plugin_update_job",
    "update_plugin",
]
