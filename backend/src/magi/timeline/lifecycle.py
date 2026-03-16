"""L12 Timeline Domain lifecycle module."""

from __future__ import annotations

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..config import get_config
from ..core.logger import get_logger
from ..plugins import get_plugin_manager, get_sensor_registry
from .service import TimelineService
from .scheduler_contrib import TimelineSchedulerContrib, set_timeline_scheduler_contrib

logger = get_logger(__name__)


class TimelineModule(LifecycleModule):
    """Initialize TimelineService and timeline scheduler contributor (L12 - Timeline layer)."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_timeline",
            dependencies=("runtime_memory", "runtime_plugin_system", "runtime_core_dependencies"),
        )
        self._context = context

    async def init(self) -> None:
        unified_memory = require_initialized(self._context.memory.unified_memory, "unified memory")

        self._context.timeline.timeline_service = TimelineService(unified_memory)
        logger.info("TimelineService initialized (L12)")

    async def shutdown(self) -> None:
        self._context.timeline.timeline_service = None


class TimelineScheduleRegistrationModule(LifecycleModule):
    """Register timeline-owned scheduled handlers after scheduler startup."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_timeline_scheduler",
            dependencies=("runtime_timeline", "runtime_plugin_system", "runtime_scheduler"),
        )
        self._context = context
        self._contrib: TimelineSchedulerContrib | None = None

    async def init(self) -> None:
        scheduler_service = require_initialized(self._context.scheduler.scheduler_service, "scheduler service")
        timeline_service = require_initialized(self._context.timeline.timeline_service, "timeline service")
        runtime_paths = require_initialized(self._context.core.runtime_paths, "runtime paths")
        self._contrib = TimelineSchedulerContrib(
            scheduler_service=scheduler_service,
            sensor_registry=get_sensor_registry(),
            plugin_manager=get_plugin_manager(),
            timeline_service=timeline_service,
            runtime_paths=runtime_paths,
            get_config=get_config,
        )
        set_timeline_scheduler_contrib(self._contrib)
        await self._contrib.register_schedules(scheduler_service)
        logger.info("Timeline schedule registration initialized (L12)")

    async def shutdown(self) -> None:
        if self._contrib is None or self._context.scheduler.scheduler_service is None:
            set_timeline_scheduler_contrib(None)
            return
        await self._contrib.unregister_schedules(self._context.scheduler.scheduler_service)
        set_timeline_scheduler_contrib(None)
        self._contrib = None

    async def queue_manual_sync(self, source_type: str):
        """Queue a manual sync using the active timeline contributor."""
        if self._contrib is None:
            raise RuntimeError("timeline scheduler contributor is not initialized")
        return await self._contrib.queue_manual_sync(source_type)
