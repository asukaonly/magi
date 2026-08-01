"""Runtime trace subscriber lifecycle module."""

from __future__ import annotations

from typing import Any

from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..bootstrap.lifecycle import LifecycleModule
from ..core.logger import get_logger

logger = get_logger(__name__)


class RuntimeTraceSubscriberModule(LifecycleModule):
    """Wire RuntimeTraceSubscriber to the runtime event bus."""

    def __init__(self, context: RuntimeBootstrapContext) -> None:
        super().__init__(
            name="runtime_trace_subscriber",
            dependencies=("runtime_message_bus", "runtime_trace", "runtime_memory"),
        )
        self._context = context
        self._subscriber: Any = None

    async def init(self) -> None:
        from .subscribers.runtime_trace_subscriber import RuntimeTraceSubscriber

        bus = require_initialized(self._context.message_bus.message_bus, "message bus")
        store = require_initialized(self._context.runtime_trace.store, "runtime trace store")
        memory = require_initialized(self._context.memory.unified_memory, "unified memory")
        self._subscriber = RuntimeTraceSubscriber(
            event_bus=bus,
            trace_store=store,
            memory_epoch_getter=memory.memory_operation_epoch,
        )
        await self._subscriber.start()
        self._context.runtime_trace.subscriber = self._subscriber
        logger.info("RuntimeTraceSubscriber started")

    async def shutdown(self) -> None:
        # Drain producer-side first to ensure events reach the bus
        try:
            from magi.events.tracing import drain_pending

            await drain_pending()
        except Exception:
            logger.exception("drain_pending failed during shutdown")
        if self._subscriber is not None:
            await self._subscriber.stop()
            self._subscriber = None
        self._context.runtime_trace.subscriber = None
