"""L5 LLM Runtime lifecycle module."""

from __future__ import annotations

from ..bootstrap.lifecycle import LifecycleInitDeferred, LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..core.logger import get_logger
from .factory import create_core_llm_adapter, create_scenario_llm_pool, is_llm_selection_pending

logger = get_logger(__name__)


class RuntimeInitializationDeferred(LifecycleInitDeferred):
    """Raised when runtime initialization should be deferred (usually onboarding stage)."""

    def __init__(self, *, pending_selection: bool, cause: Exception | None = None) -> None:
        self.pending_selection = pending_selection
        self.cause = cause
        message = (
            "runtime_llm_selection_pending"
            if pending_selection
            else "runtime_llm_configuration_invalid"
        )
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
        if self._context.runtime_commands.full_clear_recovery_pending:
            logger.warning("LLM runtime held for full-clear recovery")
            return
        config = require_initialized(self._context.core.config, "runtime config")
        try:
            self._context.llm.scenario_llm_pool = create_scenario_llm_pool(
                config, provider_registry=self._context.plugins.provider_registry,
            )
            self._context.llm.llm_adapter = create_core_llm_adapter(
                self._context.llm.scenario_llm_pool
            )
        except Exception as exc:
            raise RuntimeInitializationDeferred(
                pending_selection=is_llm_selection_pending(config),
                cause=exc,
            ) from exc

    async def shutdown(self) -> None:
        self._context.llm.scenario_llm_pool = None
        self._context.llm.llm_adapter = None


class LLMUsageSubscriberModule(LifecycleModule):
    """Subscribe LLMUsageSubscriber to the runtime event bus.

    Wires the SpanCompleted(node_type='llm_call') consumer that projects
    into the llm_usage table. The legacy LLM_CALL_COMPLETED self-subscription
    in LLMUsageStore was removed in phase 5.
    """

    def __init__(self, context: RuntimeBootstrapContext) -> None:
        super().__init__(
            name="runtime_llm_usage_subscriber",
            dependencies=("runtime_message_bus", "runtime_memory"),
        )
        self._context = context
        self._subscriber = None

    async def init(self) -> None:
        if self._context.runtime_commands.full_clear_recovery_pending:
            logger.warning("LLM usage subscriber held for full-clear recovery")
            return
        from .subscribers.llm_usage_subscriber import LLMUsageSubscriber

        bus = require_initialized(self._context.message_bus.message_bus, "message bus")
        store = self._context.llm.llm_usage_store
        if store is None:
            logger.warning("LLMUsageStore not initialized; LLMUsageSubscriber idle")
            return
        memory = require_initialized(
            self._context.memory.unified_memory,
            "unified memory",
        )
        self._subscriber = LLMUsageSubscriber(
            event_bus=bus,
            llm_usage_store=store,
            memory_epoch_getter=memory.memory_operation_epoch,
        )
        await self._subscriber.start()
        self._context.llm.llm_usage_subscriber = self._subscriber
        logger.info("LLMUsageSubscriber started")

    async def shutdown(self) -> None:
        if self._subscriber is not None:
            await self._subscriber.stop()
            self._subscriber = None
        self._context.llm.llm_usage_subscriber = None
