"""L5 LLM Runtime lifecycle module."""

from __future__ import annotations

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..core.logger import get_logger
from . import LLMScenario, ScenarioLLMPool, get_llm_usage_store
from .factory import create_core_llm_adapter, create_scenario_llm_pool, is_llm_selection_pending

logger = get_logger(__name__)


class RuntimeInitializationDeferred(Exception):
    """Raised when runtime initialization should be deferred (usually onboarding stage)."""

    def __init__(self, *, pending_selection: bool, cause: Exception | None = None) -> None:
        self.pending_selection = pending_selection
        self.cause = cause
        message = "runtime_llm_selection_pending" if pending_selection else "runtime_llm_configuration_invalid"
        super().__init__(message)


class LLMRuntimeModule(LifecycleModule):
    """Initialize scenario-based LLM pool and core adapter (L5)."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_llm",
            dependencies=("runtime_plugin_system", "runtime_configuration"),
        )
        self._context = context

    async def init(self) -> None:
        config = require_initialized(self._context.core.config, "runtime config")
        try:
            self._context.llm.scenario_llm_pool = create_scenario_llm_pool(config)
            self._context.llm.scenario_llm_pool.get(LLMScenario.CONTEXT_DECIDER)
            self._context.llm.llm_adapter = create_core_llm_adapter(self._context.llm.scenario_llm_pool)
        except Exception as exc:
            raise RuntimeInitializationDeferred(
                pending_selection=is_llm_selection_pending(config),
                cause=exc,
            ) from exc

    async def shutdown(self) -> None:
        self._context.llm.scenario_llm_pool = None
        self._context.llm.llm_adapter = None
