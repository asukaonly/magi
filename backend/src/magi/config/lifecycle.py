"""L2 Configuration lifecycle module."""

from __future__ import annotations

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext
from ..core.logger import get_logger
from . import get_config

logger = get_logger(__name__)


class ConfigurationModule(LifecycleModule):
    """Load runtime configuration and personality context (L2)."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_configuration",
            dependencies=("runtime_core_dependencies",),
        )
        self._context = context

    async def init(self) -> None:
        self._context.core.config = get_config()
        current_personality = "default"
        try:
            from ..runtime.services.personality_state import get_current_personality

            current_personality = get_current_personality() or "default"
        except Exception as exc:
            logger.warning("Failed to get current personality: %s", exc)
        self._context.core.current_personality = current_personality
