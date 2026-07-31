"""REST API for MCP server management.

Endpoints (under `/api/mcp`):
- `GET    /servers`              list configured servers + status
- `POST   /servers`              create a new server (writes TOML, optionally autostart)
- `PATCH  /servers/{id}`         update server fields
- `DELETE /servers/{id}`         stop and remove
- `POST   /servers/{id}/start`   manual start
- `POST   /servers/{id}/stop`    manual stop
- `GET    /servers/{id}/logs`    stderr tail (stdio only) + last_error
- `GET    /resources`            flat list of resources from running servers
- `POST   /resources/read`       fetch one resource by `{server_id, uri}`
- `GET    /resource-templates`   flat list of resource templates
- `GET    /prompts`              flat list of prompts from running servers
- `POST   /prompts/get`          render a prompt by `{server_id, name, arguments?}`
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, Field, model_validator

from ... import i18n as core_i18n
from ...core.logger import get_logger
from ...mcp import _toml_writer
from ...mcp.config import MCPServerConfig
from ...mcp.connection import ConnectionState, StdioConnection
from ...mcp.lifecycle import get_active_manager
from ...mcp.log_security import redact_mcp_log_text, register_mcp_transport_secrets
from ...mcp.manager import MCPManager
from ...utils.runtime import get_runtime_paths

logger = get_logger(__name__)


mcp_router = APIRouter()


def _manager() -> MCPManager:
    mgr = get_active_manager()
    if mgr is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=core_i18n.t(
                "mcp.errors.manager_not_initialized", fallback="MCP manager not initialized"
            ),
        )
    return mgr


def _config_path(server_id: str):
    return get_runtime_paths().mcp_config_dir / f"{server_id}.toml"


def _mask_transport(transport_data: dict[str, Any]) -> dict[str, Any]:
    """Mask sensitive header values for outbound API responses.

    Header *names* are preserved (so the UI can show "Authorization is set"),
    but non-empty values are replaced with a sentinel. This is read-side only;
    on-disk config is never touched.
    """
    if transport_data.get("kind") != "http":
        return transport_data
    headers = transport_data.get("headers")
    if not isinstance(headers, dict):
        return transport_data
    masked = {name: ("***" if value else "") for name, value in headers.items()}
    transport_data["headers"] = masked
    return transport_data


def _serialize_status(mgr: MCPManager, cfg: MCPServerConfig) -> dict[str, Any]:
    rt = mgr._runtimes.get(cfg.server.id)  # type: ignore[attr-defined]
    if rt is None:
        state = "disconnected" if cfg.server.enabled else "disabled"
        tool_count = 0
        resource_count = 0
        resource_template_count = 0
        prompt_count = 0
        last_error = None
    else:
        state_map = {
            ConnectionState.INIT: "connecting",
            ConnectionState.CONNECTING: "connecting",
            ConnectionState.CONNECTED: "connected",
            ConnectionState.DISCONNECTED: "disconnected",
            ConnectionState.ERROR: "error",
        }
        state = state_map.get(rt.conn.state, "error")
        tool_count = len(rt.registered_tool_names)
        resource_count = len(rt.resources)
        resource_template_count = len(rt.resource_templates)
        prompt_count = len(rt.prompts)
        last_error = redact_mcp_log_text(rt.last_error)
    return {
        "id": cfg.server.id,
        "name": cfg.server.name,
        "description": cfg.server.description,
        "enabled": cfg.server.enabled,
        "autostart": cfg.server.autostart,
        "transport": _mask_transport(cfg.transport.model_dump()),
        "runtime": cfg.runtime.model_dump(),
        "state": state,
        "tool_count": tool_count,
        "resource_count": resource_count,
        "resource_template_count": resource_template_count,
        "prompt_count": prompt_count,
        "last_error": last_error,
    }


def _config_to_toml_dict(cfg: MCPServerConfig) -> dict[str, Any]:
    server = cfg.server.model_dump()
    transport = cfg.transport.model_dump()
    runtime = cfg.runtime.model_dump()
    out: dict[str, Any] = {
        "server": server,
        "transport": transport,
        "runtime": runtime,
    }
    if cfg.tool_overrides:
        out["tool_overrides"] = {
            name: {k: v for k, v in ov.model_dump().items() if v is not None}
            for name, ov in cfg.tool_overrides.items()
        }
    return out


def _persist(cfg: MCPServerConfig) -> None:
    path = _config_path(cfg.server.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_toml_writer.dumps(_config_to_toml_dict(cfg)), encoding="utf-8")


class CreateOrUpdatePayload(BaseModel):
    server: dict
    transport: dict
    runtime: dict | None = None
    tool_overrides: dict | None = None

    @model_validator(mode="before")
    @classmethod
    def _register_secrets_before_validation(cls, value: Any) -> Any:
        register_mcp_transport_secrets(value)
        return value


@mcp_router.get("/servers")
async def list_servers() -> dict[str, Any]:
    mgr = _manager()
    return {"data": [_serialize_status(mgr, c) for c in mgr.list_configs()]}


@mcp_router.post("/servers", status_code=201)
async def create_server(payload: CreateOrUpdatePayload) -> dict[str, Any]:
    mgr = _manager()
    raw = payload.model_dump(exclude_none=True)
    register_mcp_transport_secrets(raw)
    try:
        cfg = MCPServerConfig.model_validate(raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=redact_mcp_log_text(exc))
    if cfg.server.id in {c.server.id for c in mgr.list_configs()}:
        raise HTTPException(
            status_code=409,
            detail=core_i18n.t("mcp.errors.server_id_exists", fallback="server id already exists"),
        )
    _persist(cfg)
    mgr.add_config(cfg)
    if cfg.server.enabled and cfg.server.autostart:
        try:
            await mgr.start_server(cfg.server.id)
        except Exception as exc:
            logger.warning(
                "MCP autostart on create failed",
                server_id=cfg.server.id,
                error=redact_mcp_log_text(exc),
            )
    return _serialize_status(mgr, cfg)


@mcp_router.patch("/servers/{server_id}")
async def update_server(server_id: str, payload: CreateOrUpdatePayload) -> dict[str, Any]:
    mgr = _manager()
    existing = next((c for c in mgr.list_configs() if c.server.id == server_id), None)
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail=core_i18n.t("mcp.errors.server_not_found", fallback="server not found"),
        )

    raw = payload.model_dump(exclude_none=True)
    raw.setdefault("server", {})["id"] = server_id  # id is path-locked
    register_mcp_transport_secrets(raw)
    try:
        cfg = MCPServerConfig.model_validate(raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=redact_mcp_log_text(exc))

    was_running = mgr.is_running(server_id)
    if was_running:
        await mgr.stop_server(server_id)
    _persist(cfg)
    mgr.add_config(cfg)
    if cfg.server.enabled and (was_running or cfg.server.autostart):
        try:
            await mgr.start_server(server_id)
        except Exception as exc:
            logger.warning(
                "MCP restart after update failed",
                server_id=server_id,
                error=redact_mcp_log_text(exc),
            )
    return _serialize_status(mgr, cfg)


@mcp_router.delete("/servers/{server_id}", status_code=204, response_class=Response)
async def delete_server(server_id: str) -> Response:
    mgr = _manager()
    if not any(c.server.id == server_id for c in mgr.list_configs()):
        raise HTTPException(
            status_code=404,
            detail=core_i18n.t("mcp.errors.server_not_found", fallback="server not found"),
        )
    if mgr.is_running(server_id):
        await mgr.stop_server(server_id)
    mgr._configs.pop(server_id, None)  # type: ignore[attr-defined]
    path = _config_path(server_id)
    if path.exists():
        path.unlink()
    return Response(status_code=204)


@mcp_router.post("/servers/{server_id}/start")
async def start_server(server_id: str) -> dict[str, Any]:
    mgr = _manager()
    cfg = next((c for c in mgr.list_configs() if c.server.id == server_id), None)
    if cfg is None:
        raise HTTPException(
            status_code=404,
            detail=core_i18n.t("mcp.errors.server_not_found", fallback="server not found"),
        )
    try:
        await mgr.start_server(server_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=redact_mcp_log_text(exc))
    return _serialize_status(mgr, cfg)


@mcp_router.post("/servers/{server_id}/stop")
async def stop_server(server_id: str) -> dict[str, Any]:
    mgr = _manager()
    cfg = next((c for c in mgr.list_configs() if c.server.id == server_id), None)
    if cfg is None:
        raise HTTPException(
            status_code=404,
            detail=core_i18n.t("mcp.errors.server_not_found", fallback="server not found"),
        )
    await mgr.stop_server(server_id)
    return _serialize_status(mgr, cfg)


@mcp_router.get("/servers/{server_id}/logs")
async def server_logs(server_id: str) -> dict[str, Any]:
    mgr = _manager()
    rt = mgr._runtimes.get(server_id)  # type: ignore[attr-defined]
    if rt is None:
        return {"server_id": server_id, "stderr": [], "last_error": None}
    stderr: list[str] = []
    if isinstance(rt.conn, StdioConnection):
        stderr = [
            redacted
            for line in rt.conn.stderr_tail
            if (redacted := redact_mcp_log_text(line)) is not None
        ]
    return {
        "server_id": server_id,
        "stderr": stderr,
        "last_error": redact_mcp_log_text(rt.last_error),
    }


@mcp_router.get("/resources")
async def list_resources() -> dict[str, Any]:
    mgr = _manager()
    return {"data": await mgr.list_resources()}


class ResourceReadPayload(BaseModel):
    server_id: str = Field(..., min_length=1)
    uri: str = Field(..., min_length=1)


@mcp_router.post("/resources/read")
async def read_resource(payload: ResourceReadPayload) -> dict[str, Any]:
    mgr = _manager()
    if not mgr.is_running(payload.server_id):
        raise HTTPException(
            status_code=400,
            detail=core_i18n.t(
                "mcp.errors.server_not_running",
                fallback="server {server_id!r} is not running",
                server_id=payload.server_id,
            ),
        )
    try:
        return await mgr.read_resource(payload.server_id, payload.uri)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=redact_mcp_log_text(exc))


@mcp_router.get("/resource-templates")
async def list_resource_templates() -> dict[str, Any]:
    mgr = _manager()
    return {"data": await mgr.list_resource_templates()}


@mcp_router.get("/prompts")
async def list_prompts() -> dict[str, Any]:
    mgr = _manager()
    return {"data": await mgr.list_prompts()}


class PromptGetPayload(BaseModel):
    server_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    arguments: dict[str, Any] | None = None


@mcp_router.post("/prompts/get")
async def get_prompt(payload: PromptGetPayload) -> dict[str, Any]:
    mgr = _manager()
    if not mgr.is_running(payload.server_id):
        raise HTTPException(
            status_code=400,
            detail=core_i18n.t(
                "mcp.errors.server_not_running",
                fallback="server {server_id!r} is not running",
                server_id=payload.server_id,
            ),
        )
    try:
        return await mgr.get_prompt(payload.server_id, payload.name, payload.arguments)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=redact_mcp_log_text(exc))
