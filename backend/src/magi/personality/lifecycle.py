"""L8 Personality Layer lifecycle module."""

from __future__ import annotations

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..core.logger import get_logger
from .current_state import get_current_personality
from .self_memory import SelfMemory
from .other_memory import OtherMemory

logger = get_logger(__name__)


class PersonalityModule(LifecycleModule):
    """Initialize self-memory and other-memory personality stores (L8)."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_personality",
            dependencies=("runtime_memory", "runtime_configuration", "runtime_core_dependencies"),
        )
        self._context = context

    async def init(self) -> None:
        runtime_paths = require_initialized(self._context.core.runtime_paths, "runtime paths")
        try:
            self._context.core.current_personality = get_current_personality() or self._context.core.current_personality
        except Exception as exc:
            logger.warning("Failed to refresh current personality from personality state: %s", exc)

        self._context.personality.self_memory = SelfMemory(
            personality_name=self._context.core.current_personality,
            personalities_path=str(runtime_paths.personalities_dir),
        )
        await self._context.personality.self_memory.init()
        self._context.personality.other_memory = OtherMemory()

    async def shutdown(self) -> None:
        self._context.personality.self_memory = None
        self._context.personality.other_memory = None
