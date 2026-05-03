"""MCP client lifecycle module.

Loads `~/.magi/config/mcp/*.toml`, instantiates an :class:`MCPManager`
bound to the global `tool_registry`, and starts any servers marked
`autostart = true`. On shutdown, stops every running server.
"""

from __future__ import annotations

from ..bootstrap.context import RuntimeBootstrapContext
from ..bootstrap.lifecycle import LifecycleModule
from ..core.logger import get_logger
from ..utils.runtime import get_runtime_paths
from .loader import MCPConfigLoader
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

    async def _init(self) -> None:
        global _active_manager
        from ..tools import tool_registry

        paths = get_runtime_paths()
        config_dir = paths.mcp_config_dir
        config_dir.mkdir(parents=True, exist_ok=True)

        manager = MCPManager(registry=tool_registry)
        try:
            configs = MCPConfigLoader(config_dir).load_all()
        except Exception:
            logger.exception(
                "Failed to load MCP server configs",
                config_dir=str(config_dir),
            )
            configs = []

        for cfg in configs:
            manager.add_config(cfg)

        try:
            await manager.start_all_autostart()
        except Exception:
            logger.exception("MCP autostart raised")

        self._manager = manager
        _active_manager = manager
        logger.info(
            "MCP module initialized",
            servers=len(configs),
            running=sum(1 for c in configs if manager.is_running(c.server.id)),
        )

    async def _shutdown(self) -> None:
        global _active_manager
        if self._manager is not None:
            try:
                await self._manager.stop_all()
            except Exception:
                logger.exception("MCP shutdown raised")
        if _active_manager is self._manager:
            _active_manager = None
        self._manager = None
