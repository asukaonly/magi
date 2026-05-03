"""L11 Agent Runtime lifecycle module."""

from __future__ import annotations

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..bootstrap.background_tasks import (
    build_background_task_wiring,
    build_completion_handshake_listener,
)
from ..chat import get_chat_read_service
from ..core.logger import get_logger
from ..agent.control.provider import resolve_control_session_store
from ..agent.control.permission.provider import get_permission_gateway
from ..tools import tool_registry
from ..transport.chat_events import broadcast_background_task_state_changed
from ..utils.runtime import get_runtime_paths
from .runtime import AgentRuntime, RouterAgent, TaskAgentManager
from .scheduled_agent_task import UserAgentTaskScheduleContributor
from .task_agents.factory import create_chat_agent_factory, create_default_agent_factory

logger = get_logger(__name__)


class AgentRuntimeModule(LifecycleModule):
    """Initialize TaskAgentManager, RouterAgent, and AgentRuntime (L11 - Agent Runtime layer)."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_agent_core",
            dependencies=(
                "runtime_sensor_hub",
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
        self._background_wiring = None

    async def init(self) -> None:
        config = require_initialized(self._context.core.config, "runtime config")
        llm_adapter = require_initialized(self._context.llm.llm_adapter, "llm adapter")
        llm_pool = require_initialized(self._context.llm.scenario_llm_pool, "llm pool")
        memory = require_initialized(self._context.personality.self_memory, "self memory")
        unified_memory = require_initialized(self._context.memory.unified_memory, "unified memory")
        hybrid_retrieval_service = require_initialized(
            self._context.memory.hybrid_retrieval_service,
            "hybrid retrieval service",
        )
        memory_integration = require_initialized(self._context.memory.memory_integration, "memory integration")
        runtime_trace_store = require_initialized(self._context.runtime_trace.store, "runtime trace store")
        chat_store = require_initialized(self._context.chat.store, "chat store")
        chat_projector = require_initialized(self._context.chat.projector, "chat projector")
        sensor_hub = require_initialized(self._context.agent_runtime.sensor_hub, "sensor hub")
        event_emitter = require_initialized(self._context.agent_runtime.event_emitter, "event emitter")
        plugin_manager = require_initialized(self._context.plugins.plugin_manager, "plugin manager")
        sensor_registry = require_initialized(self._context.plugins.sensor_registry, "sensor registry")

        runtime_paths = get_runtime_paths()
        bg_settings = config.agent.background_tasks
        background_wiring = build_background_task_wiring(
            store_db_path=str(runtime_paths.background_tasks_db_path),
            llm_adapter=llm_adapter,
            llm_pool=llm_pool,
            skill_runner=self._context.skills.skill_runner,
            runtime_trace_store=runtime_trace_store,
            max_concurrent=bg_settings.max_concurrent,
            history_retention_days=bg_settings.history_retention_days,
            permission_gateway_provider=get_permission_gateway,
        )
        self._background_wiring = background_wiring
        self._context.agent_runtime.background_task_manager = background_wiring.manager

        task_agent_manager = TaskAgentManager(
            create_chat_agent=create_chat_agent_factory(
                llm_adapter=llm_adapter,
                llm_pool=llm_pool,
                memory=memory,
                unified_memory=unified_memory,
                hybrid_retrieval_service=hybrid_retrieval_service,
                memory_integration=memory_integration,
                skill_runner=self._context.skills.skill_runner,
                runtime_trace_store=runtime_trace_store,
                chat_store=chat_store,
                chat_projector=chat_projector,
                chat_read_service_factory=get_chat_read_service,
                config=config,
                background_dispatcher=background_wiring.dispatcher if bg_settings.enabled else None,
                background_launch_service=background_wiring.launch_service if bg_settings.enabled else None,
                permission_gateway_provider=get_permission_gateway,
                control_session_store_provider=resolve_control_session_store,
            ),
            create_default_agent=create_default_agent_factory(
                llm_adapter=llm_adapter,
                llm_pool=llm_pool,
                config=config,
                unified_memory=unified_memory,
                plugin_manager=plugin_manager,
                sensor_registry=sensor_registry,
                control_session_store_provider=resolve_control_session_store,
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
            event_emitter=event_emitter,
        )
        agent_tool = tool_registry.get_tool("agent")
        if agent_tool and hasattr(agent_tool, "configure"):
            agent_tool.configure(
                llm_adapter=llm_adapter,
                tool_registry_instance=tool_registry,
                task_agent_manager=task_agent_manager,
                message_bus=require_initialized(self._context.message_bus.message_bus, "message bus"),
                runtime_trace_store=runtime_trace_store,
                scenario_llm_pool=llm_pool,
                permission_gateway_provider=get_permission_gateway,
            )
        await self._context.agent_runtime.agent_runtime.start()

        handshake_listener = build_completion_handshake_listener(
            get_task_agent_manager=lambda: self._context.agent_runtime.task_agent_manager,
        )
        background_wiring.manager.add_listener(handshake_listener)
        background_wiring.manager.add_listener(broadcast_background_task_state_changed)
        await background_wiring.manager.start()
        await background_wiring.retention_gc.start()

        logger.info(
            "AgentRuntime started (L11)",
            background_tasks_enabled=bg_settings.enabled,
            background_tasks_max_concurrent=bg_settings.max_concurrent,
        )

    async def shutdown(self) -> None:
        if self._background_wiring is not None:
            await self._background_wiring.retention_gc.stop()
            await self._background_wiring.manager.stop()
            self._background_wiring = None
            self._context.agent_runtime.background_task_manager = None
        if self._context.agent_runtime.agent_runtime is not None:
            await self._context.agent_runtime.agent_runtime.stop()
            self._context.agent_runtime.agent_runtime = None
        self._context.agent_runtime.task_agent_manager = None


class AgentScheduleRegistrationModule(LifecycleModule):
    """Register agent-owned scheduler target handlers."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_agent_schedule_registration",
            dependencies=("runtime_agent_core", "runtime_scheduler"),
        )
        self._context = context
        self._contrib: UserAgentTaskScheduleContributor | None = None

    async def init(self) -> None:
        scheduler_service = require_initialized(self._context.scheduler.scheduler_service, "scheduler service")
        background_task_manager = require_initialized(
            self._context.agent_runtime.background_task_manager,
            "background task manager",
        )
        self._contrib = UserAgentTaskScheduleContributor(background_task_manager)
        await self._contrib.register_schedules(scheduler_service)
        logger.info("Agent schedule handler registered")

    async def shutdown(self) -> None:
        if self._contrib is not None and self._context.scheduler.scheduler_service is not None:
            await self._contrib.unregister_schedules(self._context.scheduler.scheduler_service)
        self._contrib = None
