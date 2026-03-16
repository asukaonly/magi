"""L10 Context Layer lifecycle module."""

from __future__ import annotations

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..core.logger import get_logger
from .scenario_prompts import ScenarioPromptsStore, initialize_default_prompts

logger = get_logger(__name__)


class ContextModule(LifecycleModule):
    """Initialize scenario prompts store and load default prompts (L10)."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_context",
            dependencies=("runtime_personality", "runtime_core_dependencies"),
        )
        self._context = context

    async def init(self) -> None:
        runtime_paths = require_initialized(self._context.core.runtime_paths, "runtime paths")

        self._context.context.scenario_prompts_store = ScenarioPromptsStore(
            db_path=str(runtime_paths.scenario_prompts_db_path)
        )
        await self._context.context.scenario_prompts_store.init()
        await initialize_default_prompts(
            self._context.context.scenario_prompts_store,
            persona_name=self._context.core.current_personality,
        )

    async def shutdown(self) -> None:
        self._context.context.scenario_prompts_store = None
