"""Scheduler engine lifecycle module (L1 infrastructure)."""

from __future__ import annotations

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..core.logger import get_logger
from ..core.runtime.action_scheduler_contrib import ActionSchedulerContrib
from ..agent.scheduler_contrib import AgentSchedulerContrib
from ..plugins import get_action_registry, get_plugin_manager, get_sensor_registry
from . import SchedulerBootstrap, SchedulerService, set_scheduler_runtime
from ..timeline.scheduler_contrib import TimelineSchedulerContrib, set_timeline_scheduler_contrib

logger = get_logger(__name__)


class SchedulerModule(LifecycleModule):
    """Initialize runtime scheduler and coordinate schedule contributors."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_scheduler",
            dependencies=(
                "runtime_agent_core",
                "runtime_timeline",
                "runtime_plugin_system",
                "runtime_configuration",
                "runtime_core_dependencies",
            ),
        )
        self._context = context
        self._agent_contrib: AgentSchedulerContrib | None = None
        self._action_contrib: ActionSchedulerContrib | None = None

    async def init(self) -> None:
        runtime_paths = require_initialized(self._context.core.runtime_paths, "runtime paths")
        task_agent_manager = require_initialized(self._context.agent_runtime.task_agent_manager, "task agent manager")
        action_executor = require_initialized(self._context.agent_runtime.action_executor, "action executor")
        timeline_service = require_initialized(self._context.timeline.timeline_service, "timeline service")

        scheduler_service = SchedulerService(
            db_path=runtime_paths.scheduler_db_path,
            runtime_dir=runtime_paths.base_dir,
        )

        # Timeline layer contributor
        timeline_contrib = TimelineSchedulerContrib(
            scheduler_service=scheduler_service,
            sensor_registry=get_sensor_registry(),
            plugin_manager=get_plugin_manager(),
            timeline_service=timeline_service,
            runtime_paths=runtime_paths,
            get_config=lambda: self._context.core.config,
        )
        await timeline_contrib.register_schedules(scheduler_service)

        # Agent layer contributor (AGENT_TASK handler)
        self._agent_contrib = AgentSchedulerContrib(
            scheduler_service=scheduler_service,
            task_agent_manager=task_agent_manager,
        )
        await self._agent_contrib.register_schedules(scheduler_service)

        # Action executor contributor (ACTION_DISPATCH handler)
        self._action_contrib = ActionSchedulerContrib(
            scheduler_service=scheduler_service,
            action_registry=get_action_registry(),
            action_executor=action_executor,
        )
        await self._action_contrib.register_schedules(scheduler_service)

        # Legacy bootstrap kept for backward compatibility
        scheduler_bootstrap = SchedulerBootstrap(
            scheduler_service=scheduler_service,
            action_registry=get_action_registry(),
            runtime_paths=runtime_paths,
            task_agent_manager=task_agent_manager,
            action_executor=action_executor,
        )

        await scheduler_service.start()
        set_scheduler_runtime(scheduler_service, scheduler_bootstrap)
        set_timeline_scheduler_contrib(timeline_contrib)

        self._context.scheduler.scheduler_service = scheduler_service
        self._context.scheduler.scheduler_bootstrap = scheduler_bootstrap
        logger.info("Scheduler service started with contributors: timeline, agent, action")

    async def shutdown(self) -> None:
        if self._context.scheduler.scheduler_service is not None:
            await self._context.scheduler.scheduler_service.stop()
        self._context.scheduler.scheduler_service = None
        self._context.scheduler.scheduler_bootstrap = None
        set_scheduler_runtime(None, None)
        set_timeline_scheduler_contrib(None)
