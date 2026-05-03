from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from .config import HttpTransport, MCPServerConfig, StdioTransport
from .connection import HttpConnection, MCPConnection, StdioConnection
from .tool_adapter import build_adapter_class

logger = logging.getLogger(__name__)


def _default_factory(cfg: MCPServerConfig) -> MCPConnection:
    if isinstance(cfg.transport, StdioTransport):
        return StdioConnection(cfg.transport)
    if isinstance(cfg.transport, HttpTransport):
        return HttpConnection(cfg.transport)
    raise ValueError(f"unknown transport {cfg.transport!r}")


class _ServerRuntime:
    def __init__(self, cfg: MCPServerConfig, conn: MCPConnection):
        self.cfg = cfg
        self.conn = conn
        self.registered_tool_names: list[str] = []
        self.resources: list[dict] = []
        self.watchdog: asyncio.Task | None = None
        self.last_error: str | None = None


_DEFAULT_RECONNECT_BACKOFF = [1.0, 2.0, 4.0, 8.0, 30.0]


class MCPManager:
    def __init__(
        self,
        registry,
        connection_factory: Callable[
            [MCPServerConfig], MCPConnection
        ] = _default_factory,
        reconnect_backoff: list[float] | None = None,
    ):
        self._registry = registry
        self._factory = connection_factory
        self._configs: dict[str, MCPServerConfig] = {}
        self._runtimes: dict[str, _ServerRuntime] = {}
        self._reconnect_backoff = list(
            reconnect_backoff or _DEFAULT_RECONNECT_BACKOFF
        )

    def add_config(self, cfg: MCPServerConfig) -> None:
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

    async def read_resource(self, server_id: str, uri: str) -> dict:
        rt = self._runtimes[server_id]
        return await rt.conn.request(
            "resources/read",
            {"uri": uri},
            timeout=rt.cfg.runtime.call_timeout_ms / 1000.0,
        )

    async def _handshake(self, rt: _ServerRuntime) -> None:
        timeout = rt.cfg.runtime.init_timeout_ms / 1000.0
        await rt.conn.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "magi", "version": "0.1.0"},
            },
            timeout=timeout,
        )
        await rt.conn.notify("notifications/initialized")

    async def _reconcile_tools(self, rt: _ServerRuntime) -> None:
        for name in rt.registered_tool_names:
            self._registry.unregister(name)
        rt.registered_tool_names.clear()
        try:
            result = await rt.conn.request(
                "tools/list",
                None,
                timeout=rt.cfg.runtime.init_timeout_ms / 1000.0,
            )
        except RuntimeError as exc:
            logger.warning("tools/list failed for %s: %s", rt.cfg.server.id, exc)
            return
        for remote in result.get("tools") or []:
            override = rt.cfg.tool_overrides.get(remote["name"])
            cls = build_adapter_class(
                server_id=rt.cfg.server.id,
                remote=remote,
                manager=self,
                call_timeout_ms=rt.cfg.runtime.call_timeout_ms,
                override=override,
            )
            self._registry.register(cls)
            rt.registered_tool_names.append(
                f"mcp__{rt.cfg.server.id}__{remote['name']}"
            )

    async def _reconcile_resources(self, rt: _ServerRuntime) -> None:
        try:
            result = await rt.conn.request(
                "resources/list",
                None,
                timeout=rt.cfg.runtime.init_timeout_ms / 1000.0,
            )
        except RuntimeError:
            rt.resources = []
            return
        rt.resources = result.get("resources") or []

    def _wire_change_notifications(self, rt: _ServerRuntime) -> None:
        rt.conn.on_notification(
            "notifications/tools/list_changed",
            lambda _p: asyncio.create_task(self._reconcile_tools(rt)),
        )
        rt.conn.on_notification(
            "notifications/resources/list_changed",
            lambda _p: asyncio.create_task(self._reconcile_resources(rt)),
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
                if rt.conn.state in (
                    ConnectionState.CONNECTING,
                    ConnectionState.CONNECTED,
                    ConnectionState.INIT,
                ):
                    await asyncio.sleep(0.05)
                    continue
                logger.warning(
                    "MCP server %s disconnected; will attempt reconnect",
                    server_id,
                )
                # Unregister tools while we try to reconnect.
                for name in rt.registered_tool_names:
                    self._registry.unregister(name)
                rt.registered_tool_names.clear()
                try:
                    await rt.conn.stop()
                except Exception:
                    pass

                attempts = min(
                    rt.cfg.runtime.max_restart_attempts,
                    len(self._reconnect_backoff),
                )
                reconnected = False
                for i in range(attempts):
                    delay = self._reconnect_backoff[i]
                    await asyncio.sleep(delay)
                    try:
                        new_conn = self._factory(rt.cfg)
                        try:
                            await new_conn.start()
                            if new_conn.state != ConnectionState.CONNECTED:
                                await new_conn.stop()
                                continue
                            rt.conn = new_conn
                        except BaseException:
                            # Includes asyncio.CancelledError. Avoid leaking
                            # the partially-started connection.
                            try:
                                await new_conn.stop()
                            except Exception:
                                pass
                            raise
                        await self._handshake(rt)
                        await self._reconcile_tools(rt)
                        await self._reconcile_resources(rt)
                        self._wire_change_notifications(rt)
                        rt.last_error = None
                        reconnected = True
                        logger.info("MCP server %s reconnected", server_id)
                        break
                    except Exception as exc:
                        rt.last_error = str(exc)
                        logger.warning(
                            "MCP reconnect attempt %d/%d failed for %s: %s",
                            i + 1,
                            attempts,
                            server_id,
                            exc,
                        )
                if not reconnected:
                    logger.error(
                        "MCP server %s exhausted reconnect attempts; giving up",
                        server_id,
                    )
                    self._runtimes.pop(server_id, None)
                    return
        except asyncio.CancelledError:
            return
