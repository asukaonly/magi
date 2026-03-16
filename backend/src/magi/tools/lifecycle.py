"""L7 Tools And Skills Layer lifecycle module."""

from __future__ import annotations

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..core.logger import get_logger

logger = get_logger(__name__)


class ToolsModule(LifecycleModule):
    """Configure runtime tool integrations and skills runtime bridge (L7)."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_tools",
            dependencies=("runtime_llm", "runtime_configuration"),
        )
        self._context = context

    async def init(self) -> None:
        config = require_initialized(self._context.core.config, "runtime config")
        llm_adapter = require_initialized(self._context.llm.llm_adapter, "llm adapter")

        from . import tool_registry

        agent_tool = tool_registry.get_tool("agent")
        if agent_tool and hasattr(agent_tool, "configure"):
            agent_tool.configure(llm_adapter=llm_adapter, tool_registry_instance=tool_registry)
            logger.info("Agent tool configured with runtime LLM adapter")

        if config.features.enable_skills:
            from ..skills.service_access import init_skills_module

            init_skills_module(llm_adapter)
            logger.info("Skills module initialized")
