"""Installed plugin lifecycle and settings routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from ...core.logger import get_logger
from ...core.runtime_bindings import require_runtime_command_queue
from ...events.contracts import RefreshChannelsCommand
from ...plugins.contracts import PluginSettingsResourcePayload
from .plugins_common import legacy_plugins_module
from .plugins_schemas import (
    PluginPackageResponse,
    PluginSettingsActionRequest,
    PluginSettingsActionRunResponse,
    PluginSettingsResourceResponse,
    PluginSettingsUpdateRequest,
    PluginsListResponse,
)

plugins_core_router = APIRouter()
logger = get_logger(__name__)


async def _enqueue_runtime_channels_refresh_command(*, reason: str) -> None:
    """Notify the runtime worker process to restart channel adapters."""
    try:
        queue = require_runtime_command_queue()
    except RuntimeError:
        logger.info("Runtime command queue unavailable during plugin channels refresh notification", reason=reason)
        return

    await queue.enqueue_refresh_channels(
        RefreshChannelsCommand(
            source="plugins_api",
            reason=reason,
        )
    )


async def _refresh_channels_after_plugin_change(plugin_id: str, reason: str) -> None:
    await _enqueue_runtime_channels_refresh_command(reason=f"plugin_{plugin_id}_{reason}")


@plugins_core_router.get("", response_model=PluginsListResponse)
async def list_plugins():
    legacy = legacy_plugins_module()
    try:
        manager = legacy.resolve_plugin_manager()
    except RuntimeError:
        return PluginsListResponse(plugins=[], total=0)
    packages = manager.list_packages()
    return PluginsListResponse(
        plugins=[legacy._serialize_package(item) for item in packages],
        total=len(packages),
    )


@plugins_core_router.post("/rescan", response_model=PluginsListResponse)
async def rescan_plugins():
    legacy = legacy_plugins_module()
    manager = legacy.resolve_plugin_manager()
    packages = manager.rescan_runtime()
    return PluginsListResponse(
        plugins=[legacy._serialize_package(item) for item in packages],
        total=len(packages),
    )


@plugins_core_router.post("/{plugin_id}/enable", response_model=PluginPackageResponse)
async def enable_plugin(plugin_id: str):
    legacy = legacy_plugins_module()
    manager, _ = legacy._require_package(plugin_id)
    state = manager.enable_plugin(plugin_id)
    await _refresh_channels_after_plugin_change(plugin_id, "enabled")
    return legacy._serialize_package(state)


@plugins_core_router.post("/{plugin_id}/disable", response_model=PluginPackageResponse)
async def disable_plugin(plugin_id: str):
    legacy = legacy_plugins_module()
    manager, _ = legacy._require_package(plugin_id)
    state = manager.disable_plugin(plugin_id)
    await _refresh_channels_after_plugin_change(plugin_id, "disabled")
    return legacy._serialize_package(state)


@plugins_core_router.post("/{plugin_id}/reload", response_model=PluginPackageResponse)
async def reload_plugin(plugin_id: str):
    legacy = legacy_plugins_module()
    manager, _ = legacy._require_package(plugin_id)
    state = manager.reload_plugin(plugin_id)
    await _refresh_channels_after_plugin_change(plugin_id, "reloaded")
    return legacy._serialize_package(state)


@plugins_core_router.get("/{plugin_id}/settings", response_model=PluginPackageResponse)
async def get_plugin_settings(plugin_id: str):
    legacy = legacy_plugins_module()
    _, package = legacy._require_package(plugin_id)
    return legacy._serialize_package(package)


@plugins_core_router.put("/{plugin_id}/settings", response_model=PluginPackageResponse)
async def update_plugin_settings(plugin_id: str, request: PluginSettingsUpdateRequest):
    legacy = legacy_plugins_module()
    manager, _ = legacy._require_package(plugin_id)
    state = manager.update_plugin_settings(plugin_id, request.updates)
    if request.updates:
        await _refresh_channels_after_plugin_change(plugin_id, "settings_updated")
    return legacy._serialize_package(state)


@plugins_core_router.get("/{plugin_id}/settings/resources/{resource_name}", response_model=PluginSettingsResourceResponse)
async def read_plugin_settings_resource(plugin_id: str, resource_name: str):
    legacy = legacy_plugins_module()
    manager, _ = legacy._require_package(plugin_id)
    try:
        payload = manager.read_plugin_settings_resource(plugin_id, resource_name)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plugin settings resource not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if isinstance(payload, PluginSettingsResourcePayload):
        return PluginSettingsResourceResponse(**payload.model_dump())
    return PluginSettingsResourceResponse(**payload)


def _serialize_action_run(plugin_id: str, action_id: str, run) -> PluginSettingsActionRunResponse:
    result = run.result
    return PluginSettingsActionRunResponse(
        plugin_id=plugin_id,
        action_id=action_id,
        session_id=run.session_id,
        status=result.status,
        message=result.message,
        data=dict(result.data),
        settings_updates=dict(result.settings_updates),
    )


@plugins_core_router.post(
    "/{plugin_id}/settings/actions/{action_id}/start",
    response_model=PluginSettingsActionRunResponse,
)
async def start_plugin_settings_action(
    plugin_id: str,
    action_id: str,
    request: PluginSettingsActionRequest,
):
    legacy = legacy_plugins_module()
    manager, _ = legacy._require_package(plugin_id)
    try:
        run = await manager.start_plugin_settings_action(
            plugin_id,
            action_id,
            field_values=request.field_values,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plugin settings action not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if run.result.status == "succeeded" and run.result.settings_updates:
        await _refresh_channels_after_plugin_change(plugin_id, f"settings_action_{action_id}_succeeded")
    return _serialize_action_run(plugin_id, action_id, run)


@plugins_core_router.post(
    "/{plugin_id}/settings/actions/{action_id}/sessions/{session_id}/poll",
    response_model=PluginSettingsActionRunResponse,
)
async def poll_plugin_settings_action(
    plugin_id: str,
    action_id: str,
    session_id: str,
    request: PluginSettingsActionRequest,
):
    legacy = legacy_plugins_module()
    manager, _ = legacy._require_package(plugin_id)
    try:
        run = await manager.poll_plugin_settings_action(
            plugin_id,
            action_id,
            session_id=session_id,
            field_values=request.field_values,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plugin settings action session not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if run.result.status == "succeeded" and run.result.settings_updates:
        await _refresh_channels_after_plugin_change(plugin_id, f"settings_action_{action_id}_succeeded")
    return _serialize_action_run(plugin_id, action_id, run)


@plugins_core_router.post(
    "/{plugin_id}/settings/actions/{action_id}/sessions/{session_id}/cancel",
    response_model=PluginSettingsActionRunResponse,
)
async def cancel_plugin_settings_action(
    plugin_id: str,
    action_id: str,
    session_id: str,
):
    legacy = legacy_plugins_module()
    manager, _ = legacy._require_package(plugin_id)
    try:
        run = await manager.cancel_plugin_settings_action(
            plugin_id,
            action_id,
            session_id=session_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plugin settings action session not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _serialize_action_run(plugin_id, action_id, run)


__all__ = [
    "disable_plugin",
    "enable_plugin",
    "get_plugin_settings",
    "list_plugins",
    "plugins_core_router",
    "cancel_plugin_settings_action",
    "read_plugin_settings_resource",
    "reload_plugin",
    "rescan_plugins",
    "poll_plugin_settings_action",
    "start_plugin_settings_action",
    "update_plugin_settings",
]