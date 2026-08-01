"""L7 Tools And Skills Layer lifecycle module."""

from __future__ import annotations

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..core.logger import get_logger

logger = get_logger(__name__)


class ToolsModule(LifecycleModule):
    """Configure runtime tool integrations for L7."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_tools",
            dependencies=(
                "runtime_llm",
                "runtime_configuration",
                # The composition root host-registers the `agent` runtime tool
                # (magi.agent.runtime_tools) into the registry. Depend on it so
                # the tool is present before we configure it with the LLM adapter.
                "runtime_first_party_tools",
            ),
        )
        self._context = context

    async def init(self) -> None:
        if self._context.runtime_commands.full_clear_recovery_pending:
            logger.warning("Runtime tool configuration held for full-clear recovery")
            return
        llm_adapter = require_initialized(self._context.llm.llm_adapter, "llm adapter")

        from . import tool_registry

        agent_tool = tool_registry.get_tool("agent")
        if agent_tool and hasattr(agent_tool, "configure"):
            agent_tool.configure(llm_adapter=llm_adapter, tool_registry_instance=tool_registry)
            logger.info("Agent tool configured with runtime LLM adapter")
