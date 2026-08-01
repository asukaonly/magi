"""Scheduler engine lifecycle module (L1 infrastructure)."""

from __future__ import annotations

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..core.logger import get_logger
from .service import SchedulerService

logger = get_logger(__name__)


class SchedulerModule(LifecycleModule):
    """Initialize the scheduler engine only."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_scheduler",
            dependencies=("runtime_core_dependencies",),
        )
        self._context = context

    async def init(self) -> None:
        runtime_paths = require_initialized(self._context.core.runtime_paths, "runtime paths")

        scheduler_service = SchedulerService(
            db_path=runtime_paths.scheduler_db_path,
            runtime_dir=runtime_paths.base_dir,
        )

        await scheduler_service.start(paused=True)

        self._context.scheduler.scheduler_service = scheduler_service
        logger.info("Scheduler service prepared in paused state")

    async def shutdown(self) -> None:
        if self._context.scheduler.scheduler_service is not None:
            await self._context.scheduler.scheduler_service.stop()
        self._context.scheduler.scheduler_service = None


class SchedulerActivationModule(LifecycleModule):
    """Start schedule execution after every startup contributor is registered."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_scheduler_activation",
            dependencies=(
                "runtime_agent_schedule_registration",
                "runtime_sensor_scheduler",
                "runtime_l1_maintenance_scheduler",
                "runtime_l2_maintenance_scheduler",
                "runtime_l2_consolidation_scheduler",
                "runtime_l2_derive_scheduler",
                "runtime_l3_summary_scheduler",
                "runtime_l3_maintenance_scheduler",
                "runtime_l4_maintenance_scheduler",
                "runtime_timeline_schedulers",
                "runtime_operational_gc_scheduler",
                "runtime_outreach",
            ),
        )
        self._context = context

    async def init(self) -> None:
        scheduler_service = require_initialized(
            self._context.scheduler.scheduler_service,
            "scheduler service",
        )
        if self._context.runtime_commands.full_clear_recovery_pending:
            logger.warning(
                "Scheduler remains paused until desktop full-clear recovery restarts runtime"
            )
            return
        scheduler_service.activate()
        logger.info("Scheduler service activated")
