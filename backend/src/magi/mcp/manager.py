from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from .config import HttpTransport, MCPServerConfig, StdioTransport
from .connection import HttpConnection, MCPConnection, StdioConnection
from .log_security import redact_mcp_log_text, register_mcp_transport_secrets
from .tool_adapter import build_adapter_class

logger = logging.getLogger(__name__)


def _default_factory(cfg: MCPServerConfig) -> MCPConnection:
    if isinstance(cfg.transport, StdioTransport):
        return StdioConnection(cfg.transport, label=f"mcp.{cfg.server.id}")
    if isinstance(cfg.transport, HttpTransport):
        return HttpConnection(cfg.transport)
    raise ValueError(f"unknown transport {cfg.transport!r}")


class _ServerRuntime:
    def __init__(self, cfg: MCPServerConfig, conn: MCPConnection):
        self.cfg = cfg
        self.conn = conn
        self.registered_tool_names: list[str] = []
        self.tools: list[dict] = []
        self.resources: list[dict] = []
        self.resource_templates: list[dict] = []
        self.prompts: list[dict] = []
        self.server_capabilities: dict[str, Any] = {}
        self.watchdog: asyncio.Task | None = None
        self.last_error: str | None = None


_DEFAULT_RECONNECT_BACKOFF = [1.0, 2.0, 4.0, 8.0, 30.0]
_MAX_LIST_PAGES = 50


class MCPManager:
    def __init__(
        self,
        registry,
        connection_factory: Callable[[MCPServerConfig], MCPConnection] = _default_factory,
        reconnect_backoff: list[float] | None = None,
    ):
        self._registry = registry
        self._factory = connection_factory
        self._configs: dict[str, MCPServerConfig] = {}
        self._runtimes: dict[str, _ServerRuntime] = {}
        self._reconnect_backoff = list(reconnect_backoff or _DEFAULT_RECONNECT_BACKOFF)

    def add_config(self, cfg: MCPServerConfig) -> None:
        register_mcp_transport_secrets(cfg)
        self._configs[cfg.server.id] = cfg

    def list_configs(self) -> list[MCPServerConfig]:
        return list(self._configs.values())

    def is_running(self, server_id: str) -> bool:
        return server_id in self._runtimes

    async def start_all_autostart(self) -> None:
        await asyncio.gather(
            *(
                self.start_server(c.server.id)
                for c in self._configs.values()
                if c.server.enabled and c.server.autostart
            ),
            return_exceptions=True,
        )

    async def start_server(self, server_id: str) -> None:
        if server_id in self._runtimes:
            return
        cfg = self._configs[server_id]
        if not cfg.server.enabled:
            raise RuntimeError(f"server {server_id!r} disabled")
        conn = self._factory(cfg)
        await conn.start()
        rt = _ServerRuntime(cfg, conn)
        self._runtimes[server_id] = rt
        try:
            await self._handshake(rt)
            await self._reconcile_tools(rt)
            await self._reconcile_resources(rt)
            await self._reconcile_resource_templates(rt)
            await self._reconcile_prompts(rt)
            self._wire_change_notifications(rt)
        except Exception:
            await self.stop_server(server_id)
            raise
        rt.watchdog = asyncio.create_task(self._watchdog_loop(server_id))

    async def stop_server(self, server_id: str) -> None:
        rt = self._runtimes.pop(server_id, None)
        if rt is None:
            return
        if rt.watchdog is not None:
            rt.watchdog.cancel()
        for name in rt.registered_tool_names:
            self._registry.unregister(name)
        await rt.conn.stop()

    async def stop_all(self) -> None:
        await asyncio.gather(
            *(self.stop_server(sid) for sid in list(self._runtimes.keys())),
            return_exceptions=True,
        )

    async def call_remote(
        self,
        server_id: str,
        tool_name: str,
        args: dict,
        timeout_ms: int,
    ) -> Any:
        rt = self._runtimes.get(server_id)
        if rt is None:
            await self.start_server(server_id)
            rt = self._runtimes[server_id]
        return await rt.conn.request(
            "tools/call",
            {"name": tool_name, "arguments": args},
            timeout=timeout_ms / 1000.0,
        )

    async def list_resources(self) -> list[dict]:
        out: list[dict] = []
        for sid, rt in self._runtimes.items():
            for r in rt.resources:
                out.append({"server_id": sid, **r})
        return out

    async def list_resource_templates(self) -> list[dict]:
        out: list[dict] = []
        for sid, rt in self._runtimes.items():
            for r in rt.resource_templates:
                out.append({"server_id": sid, **r})
        return out

    async def list_prompts(self) -> list[dict]:
        out: list[dict] = []
        for sid, rt in self._runtimes.items():
            for p in rt.prompts:
                out.append({"server_id": sid, **p})
        return out

    async def get_prompt(self, server_id: str, name: str, arguments: dict | None = None) -> dict:
        rt = self._runtimes[server_id]
        params: dict[str, Any] = {"name": name}
        if arguments:
            params["arguments"] = arguments
        return await rt.conn.request(
            "prompts/get",
            params,
            timeout=rt.cfg.runtime.call_timeout_ms / 1000.0,
        )

    async def read_resource(self, server_id: str, uri: str) -> dict:
        rt = self._runtimes[server_id]
        return await rt.conn.request(
            "resources/read",
            {"uri": uri},
            timeout=rt.cfg.runtime.call_timeout_ms / 1000.0,
        )

    async def _handshake(self, rt: _ServerRuntime) -> None:
        timeout = rt.cfg.runtime.init_timeout_ms / 1000.0
        result = await rt.conn.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "magi", "version": "0.1.0"},
            },
            timeout=timeout,
        )
        rt.server_capabilities = (result or {}).get("capabilities") or {}
        await rt.conn.notify("notifications/initialized")

    async def _reconcile_tools(self, rt: _ServerRuntime) -> None:
        for name in rt.registered_tool_names:
            self._registry.unregister(name)
        rt.registered_tool_names.clear()
        try:
            tools = await self._list_paginated(rt, "tools/list", "tools")
        except Exception as exc:
            logger.warning(
                "tools/list failed for %s: %s",
                rt.cfg.server.id,
                redact_mcp_log_text(exc),
            )
            rt.tools = []
            return
        rt.tools = tools
        for remote in tools:
            if not rt.cfg.tools.allows(remote["name"]):
                continue
            override = rt.cfg.tool_overrides.get(remote["name"])
            cls = build_adapter_class(
                server_id=rt.cfg.server.id,
                remote=remote,
                manager=self,
                call_timeout_ms=rt.cfg.runtime.call_timeout_ms,
                override=override,
            )
            self._registry.register(cls)
            rt.registered_tool_names.append(f"mcp__{rt.cfg.server.id}__{remote['name']}")

    async def _reconcile_resources(self, rt: _ServerRuntime) -> None:
        if "resources" not in rt.server_capabilities:
            rt.resources = []
            return
        try:
            rt.resources = await self._list_paginated(rt, "resources/list", "resources")
        except Exception as exc:
            logger.debug(
                "resources/list failed for %s: %s",
                rt.cfg.server.id,
                redact_mcp_log_text(exc),
            )
            rt.resources = []

    async def _reconcile_resource_templates(self, rt: _ServerRuntime) -> None:
        if "resources" not in rt.server_capabilities:
            rt.resource_templates = []
            return
        try:
            rt.resource_templates = await self._list_paginated(
                rt, "resources/templates/list", "resourceTemplates"
            )
        except Exception as exc:
            logger.debug(
                "resources/templates/list failed for %s: %s",
                rt.cfg.server.id,
                redact_mcp_log_text(exc),
            )
            rt.resource_templates = []

    async def _reconcile_prompts(self, rt: _ServerRuntime) -> None:
        if "prompts" not in rt.server_capabilities:
            rt.prompts = []
            return
        try:
            rt.prompts = await self._list_paginated(rt, "prompts/list", "prompts")
        except Exception as exc:
            logger.debug(
                "prompts/list failed for %s: %s",
                rt.cfg.server.id,
                redact_mcp_log_text(exc),
            )
            rt.prompts = []

    async def _list_paginated(
        self,
        rt: _ServerRuntime,
        method: str,
        items_key: str,
    ) -> list[dict]:
        timeout = rt.cfg.runtime.init_timeout_ms / 1000.0
        items: list[dict] = []
        cursor: str | None = None
        for _ in range(_MAX_LIST_PAGES):
            params: dict[str, Any] | None = {"cursor": cursor} if cursor is not None else None
            result = await rt.conn.request(method, params, timeout=timeout)
            page = result.get(items_key)
            if page:
                items.extend(page)
            next_cursor = result.get("nextCursor")
            if not next_cursor:
                return items
            cursor = next_cursor
        logger.warning(
            "MCP %s on %s exceeded %d pages; truncating",
            method,
            rt.cfg.server.id,
            _MAX_LIST_PAGES,
        )
        return items

    def _wire_change_notifications(self, rt: _ServerRuntime) -> None:
        rt.conn.on_notification(
            "notifications/tools/list_changed",
            lambda _p: asyncio.create_task(self._reconcile_tools(rt)),
        )
        rt.conn.on_notification(
            "notifications/resources/list_changed",
            lambda _p: asyncio.create_task(self._reconcile_resources(rt)),
        )
        rt.conn.on_notification(
            "notifications/prompts/list_changed",
            lambda _p: asyncio.create_task(self._reconcile_prompts(rt)),
        )

    async def _watchdog_loop(self, server_id: str) -> None:
        """Watch the connection state. On disconnect, unregister tools and
        attempt to reconnect with exponential backoff. After exhaustion,
        drop the runtime entirely."""
        from .connection import ConnectionState

        try:
            while True:
                rt = self._runtimes.get(server_id)
                if rt is None:
                    return
                if _connection_is_alive(rt.conn.state, ConnectionState):
                    await asyncio.sleep(0.05)
                    continue
                if not await self._handle_disconnected_runtime(server_id, rt, ConnectionState):
                    return
        except asyncio.CancelledError:
            return

    async def _handle_disconnected_runtime(
        self,
        server_id: str,
        rt: _ServerRuntime,
        connection_state: Any,
    ) -> bool:
        logger.warning(
            "MCP server %s disconnected; will attempt reconnect",
            server_id,
        )
        self._unregister_runtime_tools(rt)
        await _stop_connection_quietly(rt.conn)
        if await self._reconnect_runtime(server_id, rt, connection_state):
            return True
        logger.error(
            "MCP server %s exhausted reconnect attempts; giving up",
            server_id,
        )
        self._runtimes.pop(server_id, None)
        return False

    def _unregister_runtime_tools(self, rt: _ServerRuntime) -> None:
        for name in rt.registered_tool_names:
            self._registry.unregister(name)
        rt.registered_tool_names.clear()

    async def _reconnect_runtime(
        self,
        server_id: str,
        rt: _ServerRuntime,
        connection_state: Any,
    ) -> bool:
        attempts = rt.cfg.runtime.max_restart_attempts
        for i in range(attempts):
            delay = self._reconnect_backoff[min(i, len(self._reconnect_backoff) - 1)]
            await asyncio.sleep(delay)
            try:
                if not await self._attempt_reconnect(rt, connection_state):
                    continue
                rt.last_error = None
                logger.info("MCP server %s reconnected", server_id)
                return True
            except Exception as exc:
                rt.last_error = redact_mcp_log_text(exc)
                logger.warning(
                    "MCP reconnect attempt %d/%d failed for %s: %s",
                    i + 1,
                    attempts,
                    server_id,
                    redact_mcp_log_text(exc),
                )
        return False

    async def _attempt_reconnect(
        self,
        rt: _ServerRuntime,
        connection_state: Any,
    ) -> bool:
        new_conn = self._factory(rt.cfg)
        try:
            await new_conn.start()
            if new_conn.state != connection_state.CONNECTED:
                await new_conn.stop()
                return False
            rt.conn = new_conn
        except BaseException:
            await _stop_connection_quietly(new_conn)
            raise
        await self._refresh_runtime_bindings(rt)
        return True

    async def _refresh_runtime_bindings(self, rt: _ServerRuntime) -> None:
        await self._handshake(rt)
        await self._reconcile_tools(rt)
        await self._reconcile_resources(rt)
        await self._reconcile_resource_templates(rt)
        await self._reconcile_prompts(rt)
        self._wire_change_notifications(rt)


def _connection_is_alive(state: Any, connection_state: Any) -> bool:
    return state in (
        connection_state.CONNECTING,
        connection_state.CONNECTED,
        connection_state.INIT,
    )


async def _stop_connection_quietly(conn: MCPConnection) -> None:
    try:
        await conn.stop()
    except Exception:
        pass
