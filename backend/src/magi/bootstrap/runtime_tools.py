"""Composition-root registrar for first-party host runtime tools.

This module lives in the composition root (``bootstrap/``), which sits outside
the numbered layer stack and may import any layer. It is the home for wiring
host runtime tools — tools that are part of the agent runtime rather than
plugin-contributed capabilities — into the shared ``tool_registry``.

Why here and not in the tool layer: ``magi.agent.runtime_tools`` is L12 (it
reaches into ``magi.agent.workers`` to spawn sub-agents), which is *above* the
L8 tool registry. The L8 tool plumbing (``magi.tools.core_tools`` /
``magi.tools.lifecycle``) therefore cannot import it. The composition root can,
so registration is performed from here.

NOTE: This is the natural home for future first-party runtime tools too. If
plan-mode / todo control tools (``magi.control.tools``) ever need to be
host-registered the same way, they can be wired in here.
"""

from __future__ import annotations

from ..core.logger import get_logger
from .context import RuntimeBootstrapContext
from .lifecycle import LifecycleModule

logger = get_logger(__name__)


def register_runtime_tools(registry) -> tuple[str, ...]:
    """Register every first-party runtime tool into ``registry``.

    Args:
        registry: The runtime ``ToolRegistry`` to populate.

    Returns:
        The tuple of registered tool names (for logging / assertions).
    """
    # Imported lazily so this composition-root module does not pull the agent
    # layer in at import time before the runtime is being assembled.
    from ..agent.batch.tools import BATCH_TOOL_CLASSES
    from ..agent.runtime_tools import AGENT_RUNTIME_TOOL_CLASSES

    registered: list[str] = []
    for tool_class in (*AGENT_RUNTIME_TOOL_CLASSES, *BATCH_TOOL_CLASSES):
        registry.register(tool_class)
        registered.append(tool_class().get_schema().name)
    return tuple(registered)


class RuntimeFirstPartyToolsModule(LifecycleModule):
    """Always-on bootstrap step that host-registers first-party runtime tools.

    Runs after the plugin system has registered the core-tools plugin (so the
    registry already exists and holds the plugin-contributed tools) and before
    ``ToolsModule`` configures the ``agent`` tool with the runtime LLM adapter.
    """

    def __init__(self, context: RuntimeBootstrapContext) -> None:
        super().__init__(
            name="runtime_first_party_tools",
            dependencies=("runtime_plugin_system",),
        )
        self._context = context

    async def init(self) -> None:
        if self._context.runtime_commands.full_clear_recovery_pending:
            logger.warning("First-party runtime tools held for full-clear recovery")
            return
        from ..tools import tool_registry

        registered = register_runtime_tools(tool_registry)
        logger.info(
            "Registered first-party runtime tools",
            tools=list(registered),
        )


__all__ = [
    "RuntimeFirstPartyToolsModule",
    "register_runtime_tools",
]
