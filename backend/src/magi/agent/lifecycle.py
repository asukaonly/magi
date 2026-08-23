"""L11 Agent Runtime lifecycle module."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..bootstrap.background_tasks import (
    BackgroundTaskWiring,
    build_background_task_wiring,
)
from ..core.logger import get_logger
from ..control.provider import resolve_control_session_store
from ..control.permission.provider import get_permission_gateway
from ..tools import tool_registry
from .background.notifications import broadcast_background_task_state_changed
from .post_turn_understanding import (
    AcceptedBackgroundAttempt,
    PostTurnUnderstandingService,
)
from ..utils.runtime import get_runtime_paths
from .runtime import AgentRuntime, RouterAgent, TaskAgentManager
from .scheduled_agent_task import UserAgentTaskScheduleContributor
from .task_agents.factory import create_default_agent_factory
from ..config.models import LLMScenario

if TYPE_CHECKING:
    from .runtime import TaskAgent

logger = get_logger(__name__)


@dataclass(slots=True)
class _AgentRuntimeDependencies:
    config: Any
    llm_adapter: Any
    llm_pool: Any
    memory: Any
    unified_memory: Any
    hybrid_retrieval_service: Any
    memory_integration: Any
    runtime_trace_store: Any
    chat_store: Any
    message_bus: Any
    runtime_command_queue: Any
    sensor_hub: Any
    event_emitter: Any
    plugin_manager: Any
    sensor_registry: Any
    skill_runner: Any


class AgentRuntimeModule(LifecycleModule):
    """Initialize TaskAgentManager, RouterAgent, and AgentRuntime (L11 - Agent Runtime layer)."""

    def __init__(
        self,
        context: RuntimeBootstrapContext,
        *,
        create_chat_agent_factory: Callable[..., Callable[[str], "TaskAgent"]],
        chat_read_service_factory: Callable[..., Any],
        build_timeline_handler: Callable[..., Any],
        global_clear_pending: Callable[[], Awaitable[bool]],
    ):
        super().__init__(
            name="runtime_agent_core",
            dependencies=(
                "runtime_sensor_hub",
                "runtime_command_queue",
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
        self._full_clear_background_owner = None
        self._create_chat_agent_factory = create_chat_agent_factory
        self._chat_read_service_factory = chat_read_service_factory
        self._build_timeline_handler = build_timeline_handler
        self._global_clear_pending = global_clear_pending

    async def init(self) -> None:
        if self._context.runtime_commands.full_clear_recovery_pending:
            await self._prepare_full_clear_dependencies()
            logger.warning("Agent runtime held for full-clear recovery")
            return
        deps = _load_agent_runtime_dependencies(self._context)
        post_turn_understanding_service = PostTurnUnderstandingService(
            unified_memory=deps.unified_memory,
            self_memory=deps.memory,
        )
        self._context.agent_runtime.post_turn_understanding_service = (
            post_turn_understanding_service
        )
        background_wiring = self._build_background_wiring(deps)
        self._register_background_attempt_listener(
            background_wiring,
            post_turn_understanding_service,
        )
        self._publish_background_wiring(background_wiring)
        self._register_batch_driver(background_wiring)

        task_agent_manager = self._build_task_agent_manager(
            deps,
            background_wiring,
            post_turn_understanding_service,
        )
        router_agent = self._build_router_agent(deps, task_agent_manager)
        agent_runtime = AgentRuntime(
            sensor_hub=deps.sensor_hub,
            router_agent=router_agent,
            task_agent_manager=task_agent_manager,
            event_emitter=deps.event_emitter,
            post_turn_understanding_service=post_turn_understanding_service,
        )
        self._publish_agent_runtime(task_agent_manager, agent_runtime)
        self._configure_agent_tool(deps, task_agent_manager)
        await self._start_runtime_services(deps, agent_runtime, background_wiring)

    async def _prepare_full_clear_dependencies(self) -> None:
        """Expose durable clear ownership without constructing execution services."""

        from .background import BackgroundTaskStore
        from .background.full_clear import BackgroundTaskFullClearOwner

        runtime_paths = require_initialized(
            self._context.core.runtime_paths,
            "runtime paths",
        )
        owner = BackgroundTaskFullClearOwner(
            store=BackgroundTaskStore(
                db_path=str(runtime_paths.background_tasks_db_path),
            )
        )
        await owner.start()
        self._full_clear_background_owner = owner
        self._context.agent_runtime.background_task_manager = owner

    def _build_background_wiring(
        self,
        deps: _AgentRuntimeDependencies,
    ) -> BackgroundTaskWiring:
        runtime_paths = get_runtime_paths()
        bg_settings = deps.config.agent.background_tasks
        background_wiring = build_background_task_wiring(
            store_db_path=str(runtime_paths.background_tasks_db_path),
            llm_adapter=deps.llm_adapter,
            llm_pool=deps.llm_pool,
            skill_runner=deps.skill_runner,
            runtime_trace_store=deps.runtime_trace_store,
            chat_task_budget_store=deps.chat_store,
            max_concurrent=bg_settings.max_concurrent,
            permission_gateway_provider=get_permission_gateway,
        )
        return background_wiring

    def _publish_background_wiring(self, background_wiring: BackgroundTaskWiring) -> None:
        self._background_wiring = background_wiring
        self._context.agent_runtime.background_task_manager = background_wiring.manager
        self._context.agent_runtime.background_task_retention_schedule = (
            background_wiring.retention_schedule
        )

    @staticmethod
    def _register_batch_driver(background_wiring: BackgroundTaskWiring) -> None:
        # Batch orchestrator (W2): drive manifest jobs via the same manager —
        # each finished background run fires this listener, which continues the
        # batch (next slice) or finalizes it. Non-batch runs are ignored.
        from .batch.driver import BatchDriver
        from ..tools import tool_registry

        background_wiring.manager.add_listener(
            BatchDriver(
                background_wiring.manager,
                tool_registry=tool_registry,
            ).on_terminal
        )

    @staticmethod
    def _register_background_attempt_listener(
        background_wiring: BackgroundTaskWiring,
        service: PostTurnUnderstandingService,
    ) -> None:
        async def admit_attempt(task: Any) -> None:
            spec = task.spec
            await service.admit_background_attempt(
                AcceptedBackgroundAttempt(
                    outcome_id=(
                        f"background-task:{task.task_id}:"
                        f"attempt:{int(task.attempt_index)}:started"
                    ),
                    source_turn_id=(str(getattr(spec, "origin_turn_id", "") or "").strip() or None),
                    user_id=str(getattr(spec, "user_id", "") or ""),
                    session_id=str(getattr(spec, "session_id", "") or ""),
                    task_id=str(task.task_id),
                    task_attempt=int(task.attempt_index),
                    accepted_at=float(
                        task.started_at if task.started_at is not None else task.updated_at
                    ),
                )
            )

        background_wiring.manager.add_attempt_listener(admit_attempt)

    def _build_task_agent_manager(
        self,
        deps: _AgentRuntimeDependencies,
        background_wiring: BackgroundTaskWiring,
        post_turn_understanding_service: PostTurnUnderstandingService,
    ) -> TaskAgentManager:
        runtime_settings = deps.config.agent.runtime
        return TaskAgentManager(
            create_chat_agent=self._build_chat_agent_factory(
                deps,
                background_wiring,
                post_turn_understanding_service,
            ),
            create_default_agent=self._build_default_agent_factory(deps),
            idle_ttl_seconds=runtime_settings.task_agent_manager_idle_ttl_seconds,
            max_dynamic_instances=runtime_settings.task_agent_manager_max_dynamic_instances,
            user_message_generation_getter=(
                deps.runtime_command_queue.current_user_message_generation
            ),
            user_message_scope_blocker=(deps.runtime_command_queue.is_user_message_scope_blocked),
            user_message_delivery_admitter=(deps.chat_store.mark_user_turn_delivery_admitted),
            runtime_command_acknowledger=deps.runtime_command_queue.ack,
        )

    def _build_chat_agent_factory(
        self,
        deps: _AgentRuntimeDependencies,
        background_wiring: BackgroundTaskWiring,
        post_turn_understanding_service: PostTurnUnderstandingService,
    ) -> Callable[[str], "TaskAgent"]:
        bg_settings = deps.config.agent.background_tasks
        return self._create_chat_agent_factory(
            llm_adapter=deps.llm_adapter,
            llm_pool=deps.llm_pool,
            memory=deps.memory,
            unified_memory=deps.unified_memory,
            post_turn_understanding_service=post_turn_understanding_service,
            hybrid_retrieval_service=deps.hybrid_retrieval_service,
            memory_integration=deps.memory_integration,
            skill_runner=deps.skill_runner,
            runtime_trace_store=deps.runtime_trace_store,
            chat_store=deps.chat_store,
            chat_read_service_factory=self._chat_read_service_factory,
            config=deps.config,
            background_dispatcher=background_wiring.dispatcher if bg_settings.enabled else None,
            background_launch_service=(
                background_wiring.launch_service if bg_settings.enabled else None
            ),
            permission_gateway_provider=get_permission_gateway,
            control_session_store_provider=resolve_control_session_store,
            delivery_dispatcher_resolver=self._resolve_delivery_dispatcher,
            conversation_log_resolver=self._resolve_conversation_log,
            message_bus=deps.message_bus,
        )

    def _build_default_agent_factory(
        self,
        deps: _AgentRuntimeDependencies,
    ) -> Callable[[str], "TaskAgent"]:
        return create_default_agent_factory(
            llm_adapter=deps.llm_adapter,
            llm_pool=deps.llm_pool,
            config=deps.config,
            unified_memory=deps.unified_memory,
            plugin_manager=deps.plugin_manager,
            sensor_registry=deps.sensor_registry,
            sensor_ingestion_gateway=require_initialized(
                self._context.agent_runtime.sensor_ingestion_gateway,
                "sensor ingestion gateway",
            ),
            build_timeline_handler=self._build_timeline_handler,
            control_session_store_provider=resolve_control_session_store,
            chat_store=deps.chat_store,
        )

    def _build_router_agent(
        self,
        deps: _AgentRuntimeDependencies,
        task_agent_manager: TaskAgentManager,
    ) -> RouterAgent:
        return RouterAgent(
            sensor_hub=deps.sensor_hub,
            task_agent_manager=task_agent_manager,
            batch_size=max(8, deps.config.agent.num_task_agents * 4),
            poll_timeout_seconds=0.2,
            restart_backoff_seconds=deps.config.agent.runtime.router_restart_backoff_seconds,
        )

    def _publish_agent_runtime(
        self,
        task_agent_manager: TaskAgentManager,
        agent_runtime: AgentRuntime,
    ) -> None:
        self._context.agent_runtime.task_agent_manager = task_agent_manager
        self._context.agent_runtime.agent_runtime = agent_runtime

    def _configure_agent_tool(
        self,
        deps: _AgentRuntimeDependencies,
        task_agent_manager: TaskAgentManager,
    ) -> None:
        agent_tool = tool_registry.get_tool("agent")
        if agent_tool and hasattr(agent_tool, "configure"):
            agent_tool.configure(
                llm_adapter=deps.llm_adapter,
                tool_registry_instance=tool_registry,
                task_agent_manager=task_agent_manager,
                message_bus=deps.message_bus,
                runtime_trace_store=deps.runtime_trace_store,
                scenario_llm_pool=deps.llm_pool,
                active_model_provider=lambda: deps.llm_pool.resolve(LLMScenario.CORE),
                permission_gateway_provider=get_permission_gateway,
            )

    async def _start_runtime_services(
        self,
        deps: _AgentRuntimeDependencies,
        agent_runtime: AgentRuntime,
        background_wiring: BackgroundTaskWiring,
    ) -> None:
        if self._context.runtime_commands.full_clear_recovery_pending:
            logger.warning("Agent and background task execution held for full-clear recovery")
            return
        await agent_runtime.start()
        background_wiring.manager.add_listener(broadcast_background_task_state_changed)
        await background_wiring.manager.start()
        await self._resume_batch_jobs(
            background_wiring,
            global_clear_pending=self._global_clear_pending,
        )

        bg_settings = deps.config.agent.background_tasks
        logger.info(
            "AgentRuntime started (L11)",
            background_tasks_enabled=bg_settings.enabled,
            background_tasks_auto_detect_long_task=bg_settings.auto_detect_long_task,
            background_tasks_max_concurrent=bg_settings.max_concurrent,
        )

    @staticmethod
    async def _resume_batch_jobs(
        background_wiring: BackgroundTaskWiring,
        *,
        global_clear_pending: Callable[[], Awaitable[bool]],
    ) -> None:
        # Batch restart-recovery: pick up RUNNING batch jobs left by a previous
        # process (manager._running is empty after restart) and refill their runs.
        from .batch.driver import BatchDriver
        from .batch.store import default_batch_store
        from ..tools import tool_registry

        if await global_clear_pending():
            cleared = await default_batch_store().clear_all()
            logger.info(
                "discarded batch manifests during interrupted data clear recovery",
                **cleared,
            )
            return

        resumed = await BatchDriver(
            background_wiring.manager,
            tool_registry=tool_registry,
        ).resume_running_jobs()
        if resumed:
            logger.info("batch jobs resumed after restart", count=resumed)

    def _resolve_delivery_dispatcher(self) -> Any:
        return getattr(
            getattr(self._context.channels, "module", None),
            "_chat_delivery_dispatcher",
            None,
        )

    def _resolve_conversation_log(self) -> Any:
        return getattr(
            getattr(self._context.chat, "module", None),
            "_conversation_log",
            None,
        )

    async def shutdown(self) -> None:
        if self._full_clear_background_owner is not None:
            await self._full_clear_background_owner.stop()
            self._full_clear_background_owner = None
            self._context.agent_runtime.background_task_manager = None
        if self._background_wiring is not None:
            await self._background_wiring.manager.stop()
            self._background_wiring = None
            self._context.agent_runtime.background_task_manager = None
            self._context.agent_runtime.background_task_retention_schedule = None
        if self._context.agent_runtime.agent_runtime is not None:
            await self._context.agent_runtime.agent_runtime.stop()
            self._context.agent_runtime.agent_runtime = None
        self._context.agent_runtime.task_agent_manager = None
        post_turn_understanding_service = (
            self._context.agent_runtime.post_turn_understanding_service
        )
        if post_turn_understanding_service is not None:
            flushed = await post_turn_understanding_service.shutdown(
                flush=True,
                timeout_seconds=5.0,
            )
            if not flushed:
                logger.warning("Timed out while flushing accepted conversation outcomes")
        self._context.agent_runtime.post_turn_understanding_service = None


def _load_agent_runtime_dependencies(
    context: RuntimeBootstrapContext,
) -> _AgentRuntimeDependencies:
    return _AgentRuntimeDependencies(
        config=require_initialized(context.core.config, "runtime config"),
        llm_adapter=require_initialized(context.llm.llm_adapter, "llm adapter"),
        llm_pool=require_initialized(context.llm.scenario_llm_pool, "llm pool"),
        memory=require_initialized(context.personality.self_memory, "self memory"),
        unified_memory=require_initialized(context.memory.unified_memory, "unified memory"),
        hybrid_retrieval_service=require_initialized(
            context.memory.hybrid_retrieval_service,
            "hybrid retrieval service",
        ),
        memory_integration=require_initialized(
            context.memory.memory_integration,
            "memory integration",
        ),
        runtime_trace_store=require_initialized(
            context.runtime_trace.store,
            "runtime trace store",
        ),
        chat_store=require_initialized(context.chat.store, "chat store"),
        message_bus=require_initialized(context.message_bus.message_bus, "message bus"),
        runtime_command_queue=require_initialized(
            context.runtime_commands.runtime_command_queue,
            "runtime command queue",
        ),
        sensor_hub=require_initialized(context.agent_runtime.sensor_hub, "sensor hub"),
        event_emitter=require_initialized(
            context.agent_runtime.event_emitter,
            "event emitter",
        ),
        plugin_manager=require_initialized(
            context.plugins.plugin_manager,
            "plugin manager",
        ),
        sensor_registry=require_initialized(
            context.plugins.sensor_registry,
            "sensor registry",
        ),
        skill_runner=context.skills.skill_runner,
    )


class AgentScheduleRegistrationModule(LifecycleModule):
    """Register agent-owned scheduler target handlers."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_agent_schedule_registration",
            dependencies=("runtime_agent_core", "runtime_scheduler"),
        )
        self._context = context
        self._contrib: UserAgentTaskScheduleContributor | None = None
        self._background_retention_contrib = None

    async def init(self) -> None:
        if self._context.runtime_commands.full_clear_recovery_pending:
            logger.warning("Agent schedule registration held for full-clear recovery")
            return
        scheduler_service = require_initialized(
            self._context.scheduler.scheduler_service, "scheduler service"
        )
        background_task_manager = require_initialized(
            self._context.agent_runtime.background_task_manager,
            "background task manager",
        )
        background_task_retention_schedule = require_initialized(
            self._context.agent_runtime.background_task_retention_schedule,
            "background task retention schedule",
        )
        self._contrib = UserAgentTaskScheduleContributor(background_task_manager)
        await self._contrib.register_schedules(scheduler_service)
        self._background_retention_contrib = background_task_retention_schedule
        await self._background_retention_contrib.register_schedules(scheduler_service)
        logger.info("Agent schedules registered")

    async def shutdown(self) -> None:
        if self._contrib is not None and self._context.scheduler.scheduler_service is not None:
            await self._contrib.unregister_schedules(self._context.scheduler.scheduler_service)
        if (
            self._background_retention_contrib is not None
            and self._context.scheduler.scheduler_service is not None
        ):
            await self._background_retention_contrib.unregister_schedules(
                self._context.scheduler.scheduler_service
            )
        self._contrib = None
        self._background_retention_contrib = None
