"""L7 shared skills lifecycle module."""

from __future__ import annotations

from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..bootstrap.lifecycle import LifecycleModule
from ..core.logger import get_logger
from .service_access import build_skills_runtime

logger = get_logger(__name__)


class SkillsModule(LifecycleModule):
    """Initialize the shared skills runtime owned by the skills layer."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_skills",
            dependencies=("runtime_tools", "runtime_llm", "runtime_configuration"),
        )
        self._context = context

    async def init(self) -> None:
        config = require_initialized(self._context.core.config, "runtime config")
        if not config.features.enable_skills:
            return

        llm_adapter = require_initialized(self._context.llm.llm_adapter, "llm adapter")
        bindings = build_skills_runtime(llm_adapter)
        self._context.skills.skill_indexer = bindings.skill_indexer
        self._context.skills.skill_loader = bindings.skill_loader
        self._context.skills.skill_executor = bindings.skill_executor
        logger.info("Shared skills runtime initialized")

    async def shutdown(self) -> None:
        self._context.skills.skill_indexer = None
        self._context.skills.skill_loader = None
        self._context.skills.skill_executor = None