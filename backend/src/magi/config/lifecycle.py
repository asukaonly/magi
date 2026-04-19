"""L2 Configuration lifecycle module."""

from __future__ import annotations

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext
from ..core.logger import get_logger
from . import get_config

logger = get_logger(__name__)


class ConfigurationModule(LifecycleModule):
    """Load runtime configuration (L2)."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_configuration",
            dependencies=("runtime_core_dependencies",),
        )
        self._context = context

    async def init(self) -> None:
        self._context.core.config = get_config()
        # Set a preliminary personality name from config.  PersonalityModule
        # will override this with the registry-resolved active persona later.
        self._context.core.current_personality = (
            self._context.core.config.agent.personality.name or "default"
        )
