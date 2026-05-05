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
            dependencies=("runtime_message_bus", "runtime_trace"),
        )
        self._context = context
        self._subscriber: Any = None

    async def init(self) -> None:
        from .subscribers.runtime_trace_subscriber import RuntimeTraceSubscriber

        bus = require_initialized(
            self._context.message_bus.message_bus, "message bus"
        )
        store = require_initialized(
            self._context.runtime_trace.store, "runtime trace store"
        )
        self._subscriber = RuntimeTraceSubscriber(event_bus=bus, trace_store=store)
        await self._subscriber.start()
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
