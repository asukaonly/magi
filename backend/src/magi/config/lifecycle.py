"""L2 Configuration lifecycle module."""

from __future__ import annotations

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
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
        runtime_paths = require_initialized(self._context.core.runtime_paths, "runtime paths")
        current_file = runtime_paths.personalities_dir / "current"
        current_personality = self._context.core.config.agent.personality.name or "default"
        if current_file.exists():
            try:
                persisted_name = current_file.read_text(encoding="utf-8").strip()
                if persisted_name:
                    current_personality = persisted_name
            except Exception as exc:
                logger.warning("Failed to read current personality selection: %s", exc)
        self._context.core.current_personality = current_personality
