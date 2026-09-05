"""Authenticated product API for explicit plugin connection instances."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from magi_plugin_sdk.runtime import CapabilityReadiness, PluginConnection

from ...plugins.connections import ConnectionNotFoundError, ConnectionRevisionError, ConnectionStoreError
from ...plugins.connection_settings import connection_fields, validate_connection_settings
from ...plugins.operation_execution import run_plugin_lifecycle_operation
from .plugins_common import _require_package
from .plugins_core_routes import _refresh_channels_after_plugin_change

class _ConnectionRoute(APIRoute):
    """Keep write-only credential values out of request validation responses."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError as exc:
                raise HTTPException(422, "Plugin connection request is invalid") from exc
        return handle


plugins_connection_router = APIRouter(route_class=_ConnectionRoute)
_T = TypeVar("_T")


class PluginConnectionResponse(PluginConnection):
    readiness: list[CapabilityReadiness]


class PluginConnectionsResponse(BaseModel):
    connections: list[PluginConnectionResponse]
    total: int


class ConnectionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    display_name: str = Field(min_length=1, max_length=256)
    enabled: bool = False
    settings: dict[str, JsonValue] = Field(default_factory=dict)
    credentials: dict[str, str] = Field(default_factory=dict, repr=False)


class ConnectionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=0, strict=True)
    display_name: str | None = Field(default=None, min_length=1, max_length=256)
    enabled: bool | None = None
    settings: dict[str, JsonValue] | None = None
    credential_refs: dict[str, str] | None = None
    credentials: dict[str, str | None] | None = Field(default=None, repr=False)


class ConnectionRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0, strict=True)


def _manager(plugin_id: str):
    manager, package = _require_package(plugin_id)
    if package.manifest.kind == "library":
        raise HTTPException(422, "Library packages cannot own connections")
    return manager, package


def _owned(manager, plugin_id: str, connection_id: str) -> PluginConnection:
    connection = manager.connection_store.get(connection_id)
    if connection.plugin_id != plugin_id:
        raise ConnectionNotFoundError(connection_id)
    return connection


def _validate_settings(package, settings: dict[str, JsonValue] | None) -> None:
    if settings is None:
        return
    validate_connection_settings(PluginConnection(
        connection_id="validation", plugin_id=package.manifest.plugin_id,
        display_name="Validation", settings=settings,
    ), connection_fields(package))


def _validate_enable(package, enabled: bool | None) -> None:
    if enabled and not package.trusted:
        raise HTTPException(403, "Package authorization is required before enabling a connection")


def _response(manager, connection: PluginConnection) -> PluginConnectionResponse:
    return PluginConnectionResponse(
        **connection.model_dump(), readiness=manager.connection_readiness(connection.connection_id),
    )


async def _execute(operation: Callable[[], _T]) -> _T:
    try:
        return await run_plugin_lifecycle_operation(operation)
    except ConnectionNotFoundError as exc:
        raise HTTPException(404, "Plugin connection not found") from exc
    except ConnectionRevisionError as exc:
        raise HTTPException(409, {"code": "connection_revision_conflict",
                                  "current_revision": exc.actual_revision}) from exc
    except PermissionError as exc:
        raise HTTPException(403, "Plugin connection authorization is required") from exc
    except ConnectionStoreError as exc:
        raise HTTPException(503, "Plugin connection storage is unavailable") from exc
    except ValueError as exc:
        raise HTTPException(422, "Plugin connection configuration is invalid") from exc


@plugins_connection_router.get("/{plugin_id}/connections", response_model=PluginConnectionsResponse)
async def list_plugin_connections(plugin_id: str) -> PluginConnectionsResponse:
    def operation() -> PluginConnectionsResponse:
        manager, _ = _manager(plugin_id)
        connections = [_response(manager, connection) for connection in manager.connection_store.list(plugin_id)]
        return PluginConnectionsResponse(connections=connections, total=len(connections))
    return await _execute(operation)


@plugins_connection_router.post("/{plugin_id}/connections", response_model=PluginConnectionResponse, status_code=201)
async def create_plugin_connection(plugin_id: str, request: ConnectionCreateRequest) -> PluginConnectionResponse:
    def operation() -> PluginConnectionResponse:
        manager, package = _manager(plugin_id)
        _validate_enable(package, request.enabled)
        _validate_settings(package, request.settings)
        connection = manager.create_connection(plugin_id, **request.model_dump())
        return _response(manager, connection)
    connection = await _execute(operation)
    if connection.enabled:
        await _refresh_channels_after_plugin_change(plugin_id, "connection_created")
    return connection


@plugins_connection_router.get("/{plugin_id}/connections/{connection_id}", response_model=PluginConnectionResponse)
async def get_plugin_connection(plugin_id: str, connection_id: str) -> PluginConnectionResponse:
    def operation() -> PluginConnectionResponse:
        manager, _ = _manager(plugin_id)
        return _response(manager, _owned(manager, plugin_id, connection_id))
    return await _execute(operation)


@plugins_connection_router.patch("/{plugin_id}/connections/{connection_id}", response_model=PluginConnectionResponse)
async def update_plugin_connection(
    plugin_id: str, connection_id: str, request: ConnectionUpdateRequest,
) -> PluginConnectionResponse:
    def operation() -> PluginConnectionResponse:
        manager, package = _manager(plugin_id)
        _owned(manager, plugin_id, connection_id)
        _validate_enable(package, request.enabled)
        _validate_settings(package, request.settings)
        connection = manager.update_connection(connection_id, **request.model_dump(exclude_unset=True))
        return _response(manager, connection)
    connection = await _execute(operation)
    await _refresh_channels_after_plugin_change(plugin_id, "connection_updated")
    return connection


@plugins_connection_router.delete("/{plugin_id}/connections/{connection_id}", status_code=204)
async def disconnect_plugin_connection(
    plugin_id: str, connection_id: str, expected_revision: int = Query(ge=0),
) -> Response:
    def operation() -> None:
        manager, _ = _manager(plugin_id)
        _owned(manager, plugin_id, connection_id)
        manager.disconnect_connection(connection_id, expected_revision=expected_revision)
    await _execute(operation)
    await _refresh_channels_after_plugin_change(plugin_id, "connection_disconnected")
    return Response(status_code=204)


@plugins_connection_router.post("/{plugin_id}/connections/{connection_id}/clear", response_model=PluginConnectionResponse)
async def clear_plugin_connection_content(
    plugin_id: str, connection_id: str, request: ConnectionRevisionRequest,
) -> PluginConnectionResponse:
    def operation() -> PluginConnectionResponse:
        manager, _ = _manager(plugin_id)
        _owned(manager, plugin_id, connection_id)
        connection = manager.clear_connection_content(connection_id, expected_revision=request.expected_revision)
        return _response(manager, connection)
    connection = await _execute(operation)
    await _refresh_channels_after_plugin_change(plugin_id, "connection_content_cleared")
    return connection
