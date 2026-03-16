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
            dependencies=(
                "runtime_core_dependencies",
            ),
        )
        self._context = context

    async def init(self) -> None:
        runtime_paths = require_initialized(self._context.core.runtime_paths, "runtime paths")

        scheduler_service = SchedulerService(
            db_path=runtime_paths.scheduler_db_path,
            runtime_dir=runtime_paths.base_dir,
        )

        await scheduler_service.start()

        self._context.scheduler.scheduler_service = scheduler_service
        logger.info("Scheduler service started")

    async def shutdown(self) -> None:
        if self._context.scheduler.scheduler_service is not None:
            await self._context.scheduler.scheduler_service.stop()
        self._context.scheduler.scheduler_service = None
