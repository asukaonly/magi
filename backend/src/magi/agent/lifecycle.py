"""L11 Agent Runtime lifecycle module."""

from __future__ import annotations

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..core.logger import get_logger
from ..core.runtime import AgentRuntime, RouterAgent, TaskAgentManager
from .scheduler_contrib import AgentSchedulerContrib
from .task_agents.factory import create_chat_agent_factory, create_default_agent_factory

logger = get_logger(__name__)


class AgentRuntimeModule(LifecycleModule):
    """Initialize TaskAgentManager, RouterAgent, and AgentRuntime (L11 - Agent Runtime layer)."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_agent_core",
            dependencies=(
                "runtime_sensor_executor",
                "runtime_context",
                "runtime_personality",
                "runtime_memory",
                "runtime_skills",
                "runtime_llm",
                "runtime_plugin_system",
                "runtime_configuration",
            ),
        )
        self._context = context

    async def init(self) -> None:
        config = require_initialized(self._context.core.config, "runtime config")
        llm_adapter = require_initialized(self._context.llm.llm_adapter, "llm adapter")
        llm_pool = require_initialized(self._context.llm.scenario_llm_pool, "llm pool")
        memory = require_initialized(self._context.personality.self_memory, "self memory")
        other_memory = require_initialized(self._context.personality.other_memory, "other memory")
        unified_memory = require_initialized(self._context.memory.unified_memory, "unified memory")
        memory_integration = require_initialized(self._context.memory.memory_integration, "memory integration")
        scenario_prompts_store = require_initialized(self._context.context.scenario_prompts_store, "scenario prompts store")
        sensor_hub = require_initialized(self._context.agent_runtime.sensor_hub, "sensor hub")
        action_emitter = require_initialized(self._context.agent_runtime.action_emitter, "action emitter")
        plugin_manager = require_initialized(self._context.plugins.plugin_manager, "plugin manager")
        sensor_registry = require_initialized(self._context.plugins.sensor_registry, "sensor registry")

        task_agent_manager = TaskAgentManager(
            create_chat_agent=create_chat_agent_factory(
                llm_adapter=llm_adapter,
                llm_pool=llm_pool,
                memory=memory,
                other_memory=other_memory,
                unified_memory=unified_memory,
                memory_integration=memory_integration,
                scenario_prompts_store=scenario_prompts_store,
                skill_executor=self._context.skills.skill_executor,
                config=config,
            ),
            create_default_agent=create_default_agent_factory(
                llm_adapter=llm_adapter,
                llm_pool=llm_pool,
                config=config,
                unified_memory=unified_memory,
                plugin_manager=plugin_manager,
                sensor_registry=sensor_registry,
            ),
            idle_ttl_seconds=config.agent.runtime.task_agent_manager_idle_ttl_seconds,
            max_dynamic_instances=config.agent.runtime.task_agent_manager_max_dynamic_instances,
        )
        router_agent = RouterAgent(
            sensor_hub=sensor_hub,
            task_agent_manager=task_agent_manager,
            batch_size=max(8, config.agent.num_task_agents * 4),
            poll_timeout_seconds=0.2,
            restart_backoff_seconds=config.agent.runtime.router_restart_backoff_seconds,
        )

        self._context.agent_runtime.task_agent_manager = task_agent_manager
        self._context.agent_runtime.agent_runtime = AgentRuntime(
            sensor_hub=sensor_hub,
            router_agent=router_agent,
            task_agent_manager=task_agent_manager,
            action_emitter=action_emitter,
        )
        await self._context.agent_runtime.agent_runtime.start()
        logger.info("AgentRuntime started (L11)")

    async def shutdown(self) -> None:
        if self._context.agent_runtime.agent_runtime is not None:
            await self._context.agent_runtime.agent_runtime.stop()
            self._context.agent_runtime.agent_runtime = None
        self._context.agent_runtime.task_agent_manager = None


class AgentScheduleRegistrationModule(LifecycleModule):
    """Register agent-owned scheduled handlers after scheduler startup."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_agent_scheduler",
            dependencies=("runtime_agent_core", "runtime_scheduler"),
        )
        self._context = context
        self._contrib: AgentSchedulerContrib | None = None

    async def init(self) -> None:
        scheduler_service = require_initialized(self._context.scheduler.scheduler_service, "scheduler service")
        task_agent_manager = require_initialized(
            self._context.agent_runtime.task_agent_manager,
            "task agent manager",
        )
        self._contrib = AgentSchedulerContrib(
            scheduler_service=scheduler_service,
            task_agent_manager=task_agent_manager,
        )
        await self._contrib.register_schedules(scheduler_service)

    async def shutdown(self) -> None:
        if self._contrib is None or self._context.scheduler.scheduler_service is None:
            return
        await self._contrib.unregister_schedules(self._context.scheduler.scheduler_service)
        self._contrib = None
