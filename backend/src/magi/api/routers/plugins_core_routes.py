"""Installed plugin lifecycle and settings routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from ... import i18n as core_i18n
from ...config import get_config
from ...core.logger import get_logger
from ...core.runtime_bindings import require_runtime_command_queue
from ...events.contracts import RefreshChannelsCommand
from ...plugins.operation_execution import (
    run_plugin_callback_operation,
    run_plugin_lifecycle_operation,
)
from ...plugins.contracts import PluginSettingsResourcePayload
from ...plugins.operation_authorization import build_host_invocation
from ..services.plugin_secrets import (
    mask_plugin_setting_values,
)
from .plugins_common import (
    _get_plugin_i18n,
    _require_plugin_manager,
    _require_package,
    _serialize_package,
    _try_plugin_manager,
    translate_with_fallback,
)
from .plugins_schemas import (
    PluginPackageResponse,
    PluginSettingsActionRequest,
    PluginSettingsActionRunResponse,
    PluginSettingsResourceResponse,
    PluginsListResponse,
)

plugins_core_router = APIRouter()
logger = get_logger(__name__)


async def _enqueue_runtime_channels_refresh_command(*, reason: str) -> None:
    """Notify the runtime worker process to restart channel adapters."""
    try:
        queue = require_runtime_command_queue()
    except RuntimeError:
        logger.info(
            "Runtime command queue unavailable during plugin channels refresh notification",
            reason=reason,
        )
        return

    await queue.enqueue_refresh_channels(
        RefreshChannelsCommand(
            source="plugins_api",
            reason=reason,
        )
    )


async def _refresh_channels_after_plugin_change(plugin_id: str, reason: str) -> None:
    await _enqueue_runtime_channels_refresh_command(reason=f"plugin_{plugin_id}_{reason}")


def _plugin_settings_service(manager):
    return getattr(manager, "settings_service", manager)


@plugins_core_router.get("", response_model=PluginsListResponse)
async def list_plugins(
    include: str | None = Query(
        default=None,
        description=(
            "Comma-separated extras to include. Pass 'libraries' to also "
            "return library packages (hidden by default — they are auto-"
            "installed and managed via refcount, not user toggle)."
        ),
    ),
):
    manager = _try_plugin_manager()
    if manager is None:
        return PluginsListResponse(plugins=[], total=0)
    packages = manager.list_packages()
    include_set = {p.strip() for p in (include or "").split(",") if p.strip()}
    include_libraries = "libraries" in include_set
    if not include_libraries:
        packages = [p for p in packages if p.manifest.kind != "library"]
    # Read config.plugins.packages ONCE and thread it through the projection
    # so serializing M plugins does one config read (glob + stat) not M.
    config_packages = get_config().plugins.packages
    return PluginsListResponse(
        plugins=[_serialize_package(item, packages=config_packages) for item in packages],
        total=len(packages),
    )


@plugins_core_router.post("/rescan", response_model=PluginsListResponse)
async def rescan_plugins():
    manager = _require_plugin_manager()
    packages = await run_plugin_lifecycle_operation(manager.rescan_runtime)
    config_packages = get_config().plugins.packages
    return PluginsListResponse(
        plugins=[_serialize_package(item, packages=config_packages) for item in packages],
        total=len(packages),
    )


@plugins_core_router.post("/{plugin_id}/reload", response_model=PluginPackageResponse)
async def reload_plugin(plugin_id: str):
    manager, _ = _require_package(plugin_id)
    state = await run_plugin_lifecycle_operation(lambda: manager.reload_plugin(plugin_id))
    await _refresh_channels_after_plugin_change(plugin_id, "reloaded")
    return _serialize_package(state)


def _translate_resource_payload(payload_dict: dict[str, Any], plugin_id: str) -> dict[str, Any]:
    """Resolve any ``*_i18n_key`` references inside a settings-resource payload.

    The plugin emits ``label_i18n_key`` / ``description_i18n_key`` strings that
    refer into its own i18n bundle (e.g. ``{plugin_id}.permissions.x.label``).
    The frontend i18next instance does not load plugin bundles, so we translate
    the keys server-side here and write the result back into ``label`` /
    ``description`` before responding.
    """

    state = payload_dict.get("data") if isinstance(payload_dict, dict) else None
    if not isinstance(state, dict):
        return payload_dict

    package = _try_plugin_manager()
    package_state = package.get_package(plugin_id) if package is not None else None
    plugin_dir = (
        package_state.manifest.plugin_dir if package_state and package_state.manifest else ""
    )
    try:
        i18n = _get_plugin_i18n(plugin_id, plugin_dir)
    except Exception:  # noqa: BLE001 - never block a payload on i18n
        return payload_dict
    if i18n is None:
        return payload_dict

    def _resolve_item(item: Any) -> Any:
        if not isinstance(item, dict):
            return item
        resolved = dict(item)
        label_key = resolved.get("label_i18n_key")
        if isinstance(label_key, str) and label_key:
            translated = translate_with_fallback(i18n, label_key, None)
            if translated:
                resolved["label"] = translated
        description_key = resolved.get("description_i18n_key")
        if isinstance(description_key, str) and description_key:
            translated = translate_with_fallback(i18n, description_key, None)
            if translated:
                resolved["description"] = translated
        return resolved

    def _walk(node: Any) -> Any:
        if isinstance(node, list):
            return [_walk(child) for child in node]
        if isinstance(node, dict):
            walked = {key: _walk(value) for key, value in node.items()}
            return _resolve_item(walked)
        return node

    payload_dict["data"] = _walk(state)
    return payload_dict


def _require_settings_connection(connection_id: str):
    """Resolve a settings target without interpreting package IDs as connections."""
    manager = _require_plugin_manager()
    try:
        connection = manager.connection_store.get(connection_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Plugin connection not found") from exc
    package = manager.get_package(connection.plugin_id)
    if package is None:
        raise HTTPException(status_code=404, detail="Plugin package not found")
    return manager, connection, package


@plugins_core_router.get(
    "/connections/{connection_id}/settings/resources/{resource_name}", response_model=PluginSettingsResourceResponse
)
async def read_plugin_settings_resource(connection_id: str, resource_name: str):
    manager, connection, _ = _require_settings_connection(connection_id)
    plugin_id = connection.plugin_id
    settings_service = _plugin_settings_service(manager)
    try:
        payload = await settings_service.read_plugin_settings_resource(connection_id, resource_name)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=core_i18n.t(
                "plugins.errors.settings_resource_not_found",
                fallback="Plugin settings resource not found",
            ),
        ) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if isinstance(payload, PluginSettingsResourcePayload):
        payload_dict = payload.model_dump()
    else:
        payload_dict = dict(payload)
    payload_dict = _translate_resource_payload(payload_dict, plugin_id)
    return PluginSettingsResourceResponse(connection_id=connection_id, **payload_dict)


def _serialize_action_run(
    connection_id: str,
    plugin_id: str,
    action_id: str,
    run,
    contributions,
) -> PluginSettingsActionRunResponse:
    result = run.result
    return PluginSettingsActionRunResponse(
        connection_id=connection_id,
        plugin_id=plugin_id,
        action_id=action_id,
        session_id=run.session_id,
        status=result.status,
        message=result.message,
        data=dict(result.data),
        settings_updates=mask_plugin_setting_values(
            dict(result.settings_updates),
            contributions,
        ),
    )


@plugins_core_router.post(
    "/connections/{connection_id}/settings/actions/{action_id}/start",
    response_model=PluginSettingsActionRunResponse,
)
async def start_plugin_settings_action(
    connection_id: str,
    action_id: str,
    request: PluginSettingsActionRequest,
):
    manager, connection, package = _require_settings_connection(connection_id)
    plugin_id = connection.plugin_id
    settings_service = _plugin_settings_service(manager)
    try:
        run = await settings_service.start_plugin_settings_action(
            connection_id,
            action_id,
            identity=build_host_invocation(connection, trigger="user"),
            field_values=request.field_values,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=core_i18n.t(
                "plugins.errors.settings_action_not_found",
                fallback="Plugin settings action not found",
            ),
        ) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if run.result.status == "succeeded" and (
        run.result.settings_updates or bool(run.result.data.get("refresh_channels"))
    ):
        await _refresh_channels_after_plugin_change(
            plugin_id, f"settings_action_{action_id}_succeeded"
        )
    return _serialize_action_run(connection_id, plugin_id, action_id, run, package.contributions)


@plugins_core_router.post(
    "/connections/{connection_id}/settings/actions/{action_id}/sessions/{session_id}/poll",
    response_model=PluginSettingsActionRunResponse,
)
async def poll_plugin_settings_action(
    connection_id: str,
    action_id: str,
    session_id: str,
    request: PluginSettingsActionRequest,
):
    manager, connection, package = _require_settings_connection(connection_id)
    plugin_id = connection.plugin_id
    settings_service = _plugin_settings_service(manager)
    try:
        run = await settings_service.poll_plugin_settings_action(
            connection_id,
            action_id,
            identity=build_host_invocation(connection, trigger="user"),
            session_id=session_id,
            field_values=request.field_values,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=core_i18n.t(
                "plugins.errors.settings_action_session_not_found",
                fallback="Plugin settings action session not found",
            ),
        ) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if run.result.status == "succeeded" and (
        run.result.settings_updates or bool(run.result.data.get("refresh_channels"))
    ):
        await _refresh_channels_after_plugin_change(
            plugin_id, f"settings_action_{action_id}_succeeded"
        )
    return _serialize_action_run(connection_id, plugin_id, action_id, run, package.contributions)


@plugins_core_router.post(
    "/connections/{connection_id}/settings/actions/{action_id}/sessions/{session_id}/cancel",
    response_model=PluginSettingsActionRunResponse,
)
async def cancel_plugin_settings_action(
    connection_id: str,
    action_id: str,
    session_id: str,
):
    manager, connection, package = _require_settings_connection(connection_id)
    plugin_id = connection.plugin_id
    settings_service = _plugin_settings_service(manager)
    try:
        run = await settings_service.cancel_plugin_settings_action(
            connection_id,
            action_id,
            identity=build_host_invocation(connection, trigger="user"),
            session_id=session_id,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=core_i18n.t(
                "plugins.errors.settings_action_session_not_found",
                fallback="Plugin settings action session not found",
            ),
        ) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _serialize_action_run(connection_id, plugin_id, action_id, run, package.contributions)


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
