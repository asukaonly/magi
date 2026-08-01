"""MCP client lifecycle module.

Loads `~/.magi/config/mcp/*.toml`, instantiates an :class:`MCPManager`
bound to the global `tool_registry`, and starts any servers marked
`autostart = true`. On shutdown, stops every running server.

Autostart runs in the background so a slow or unreachable MCP server
cannot block the rest of the runtime from finishing initialisation.
Tools register into the registry as each server's handshake completes;
callers that race the autostart will simply not see those tools yet.
"""

from __future__ import annotations

import asyncio

from ..bootstrap.context import RuntimeBootstrapContext
from ..bootstrap.lifecycle import LifecycleModule
from ..core.logger import get_logger
from ..utils.runtime import get_runtime_paths
from .loader import MCPConfigLoader
from .log_security import redact_mcp_traceback
from .manager import MCPManager

logger = get_logger(__name__)


_active_manager: MCPManager | None = None


def get_active_manager() -> MCPManager | None:
    """Return the manager constructed by :class:`MCPModule`, if any."""
    return _active_manager


class MCPModule(LifecycleModule):
    """Wire the MCP client into the runtime worker."""

    def __init__(self, context: RuntimeBootstrapContext) -> None:
        super().__init__(
            name="runtime_mcp",
            dependencies=("runtime_tools",),
            init=self._init,
            shutdown=self._shutdown,
        )
        self._context = context
        self._manager: MCPManager | None = None
        self._autostart_task: asyncio.Task | None = None

    async def _init(self) -> None:
        global _active_manager
        if self._context.runtime_commands.full_clear_recovery_pending:
            logger.warning("MCP runtime held for full-clear recovery")
            return
        from ..tools import tool_registry

        paths = get_runtime_paths()
        config_dir = paths.mcp_config_dir
        config_dir.mkdir(parents=True, exist_ok=True)

        manager = MCPManager(registry=tool_registry)
        try:
            configs = MCPConfigLoader(config_dir).load_all()
        except Exception as exc:
            logger.error(
                "Failed to load MCP server configs",
                config_dir=str(config_dir),
                traceback=redact_mcp_traceback(exc),
            )
            configs = []

        for cfg in configs:
            manager.add_config(cfg)

        autostart_count = sum(1 for c in configs if c.server.enabled and c.server.autostart)
        if autostart_count and not self._context.runtime_commands.full_clear_recovery_pending:
            self._autostart_task = asyncio.create_task(
                self._run_autostart(manager), name="mcp_autostart"
            )

        self._manager = manager
        _active_manager = manager
        logger.info(
            "MCP module initialized",
            servers=len(configs),
            autostart_pending=(
                0 if self._context.runtime_commands.full_clear_recovery_pending else autostart_count
            ),
        )

    @staticmethod
    async def _run_autostart(manager: MCPManager) -> None:
        try:
            await manager.start_all_autostart()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(
                "MCP autostart raised",
                traceback=redact_mcp_traceback(exc),
            )
        else:
            logger.info(
                "MCP autostart completed",
                running=sum(1 for c in manager.list_configs() if manager.is_running(c.server.id)),
            )

    async def _shutdown(self) -> None:
        global _active_manager
        if self._autostart_task is not None and not self._autostart_task.done():
            self._autostart_task.cancel()
            try:
                await self._autostart_task
            except (asyncio.CancelledError, Exception):
                pass
            self._autostart_task = None
        if self._manager is not None:
            try:
                await self._manager.stop_all()
            except Exception as exc:
                logger.error(
                    "MCP shutdown raised",
                    traceback=redact_mcp_traceback(exc),
                )
        if _active_manager is self._manager:
            _active_manager = None
        self._manager = None
