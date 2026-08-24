"""L7 shared skills lifecycle module."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..bootstrap.lifecycle import LifecycleModule
from ..core.logger import get_logger
from ..control.permission.provider import get_permission_gateway
from .service_access import build_skills_runtime
from .tool_registry_port import ToolRegistryPort
from ..config.models import LLMScenario

logger = get_logger(__name__)


class SkillsModule(LifecycleModule):
    """Initialize the shared skills runtime owned by the skills layer."""

    def __init__(
        self,
        context: RuntimeBootstrapContext,
        tool_registry: ToolRegistryPort,
        *,
        orchestrator_factory: Callable[..., Any],
        agent_run_request_factory: Callable[..., Any],
    ):
        super().__init__(
            name="runtime_skills",
            dependencies=("runtime_llm", "runtime_configuration"),
        )
        self._context = context
        self._tool_registry = tool_registry
        self._orchestrator_factory = orchestrator_factory
        self._agent_run_request_factory = agent_run_request_factory

    async def init(self) -> None:
        if self._context.runtime_commands.full_clear_recovery_pending:
            logger.warning("Skills runtime held for full-clear recovery")
            return
        config = require_initialized(self._context.core.config, "runtime config")
        if not config.features.enable_skills:
            return

        llm_adapter = require_initialized(self._context.llm.llm_adapter, "llm adapter")
        bindings = build_skills_runtime(
            llm_adapter,
            active_model_provider=lambda: self._context.llm.scenario_llm_pool.resolve(
                LLMScenario.CORE
            ),
            scenario_llm_pool=self._context.llm.scenario_llm_pool,
            permission_gateway_provider=get_permission_gateway,
            tool_registry=self._tool_registry,
            orchestrator_factory=self._orchestrator_factory,
            agent_run_request_factory=self._agent_run_request_factory,
        )
        self._context.skills.skill_indexer = bindings.skill_indexer
        self._context.skills.skill_loader = bindings.skill_loader
        self._context.skills.skill_runner = bindings.skill_runner
        logger.info("Shared skills runtime initialized")

    async def shutdown(self) -> None:
        self._context.skills.skill_indexer = None
        self._context.skills.skill_loader = None
        self._context.skills.skill_runner = None
