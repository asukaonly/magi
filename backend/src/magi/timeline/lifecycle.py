"""L12 Timeline Domain lifecycle module."""

from __future__ import annotations

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..core.logger import get_logger
from .service import TimelineService

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
