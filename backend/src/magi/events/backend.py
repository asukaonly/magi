"""
Message Bus - Abstract Backend Interface
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import replace
from typing import Any, Callable, Coroutine, Optional

from .events import Event, PUBLISHED_MEMORY_EPOCH_METADATA_KEY

logger = logging.getLogger(__name__)


class MessageBusBackend(ABC):
    """
    Message Bus Backend Abstract Interface

    The message bus is an in-process runtime event fan-out primitive. It is not the
    durable cross-process transport; durable commands and ingress events use dedicated
    SQLite-backed stores.
    """

    def __init__(self) -> None:
        self._memory_operation_epoch_getter: Callable[[], int] | None = None

    def publish(self, event: Event) -> Coroutine[Any, Any, bool]:
        """
        Bind publication metadata immediately and return the asynchronous delivery.

        Args:
            event: Event to publish

        Returns:
            Awaitable resolving to whether the event was successfully published
        """
        # This wrapper is intentionally synchronous. Fire-and-forget callers may
        # schedule the returned coroutine later, but the publication boundary must
        # remain the instant they hand the event to the bus.
        return self._publish_bound(self._snapshot_for_publish(event))

    def bind_memory_operation_epoch(
        self,
        getter: Callable[[], int] | None,
    ) -> None:
        """Bind the process-local memory epoch stamped on queued events."""
        if getter is not None and not callable(getter):
            raise TypeError("Memory operation epoch getter must be callable")
        self._memory_operation_epoch_getter = getter

    def _snapshot_for_publish(self, event: Event) -> Event:
        """Freeze reserved publication metadata before the caller regains control."""
        metadata = dict(event.metadata or {})
        metadata.pop(PUBLISHED_MEMORY_EPOCH_METADATA_KEY, None)
        getter = self._memory_operation_epoch_getter
        if getter is not None:
            try:
                epoch = getter()
                if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 0:
                    raise ValueError("Memory operation epoch must be a non-negative integer")
                metadata[PUBLISHED_MEMORY_EPOCH_METADATA_KEY] = epoch
            except Exception:
                logger.exception(
                    "Failed to capture memory operation epoch for queued event",
                    extra={"event_type": event.type},
                )
        return replace(event, metadata=metadata)

    @abstractmethod
    async def _publish_bound(self, event: Event) -> bool:
        """Deliver an event whose publication metadata has already been bound."""
        pass

    @abstractmethod
    async def subscribe(
        self,
        event_type: str,
        handler: Callable,
        propagation_mode: str = "broadcast",
        filter_func: Optional[Callable[[Event], bool]] = None,
    ) -> str:
        """
        Subscribe to event

        Args:
            event_type: event type (e.g. "AgentStarted")
            handler: event handler function (async def handler(event: Event))
            propagation_mode: propagation mode ("broadcast" | "competing")
            filter_func: event filter function (only process when returns True)

        Returns:
            str: Subscription id
        """
        pass

    @abstractmethod
    async def unsubscribe(self, subscription_id: str) -> bool:
        """
        Unsubscribe from event

        Args:
            subscription_id: Subscription id

        Returns:
            bool: Whether unsubscription was successful
        """
        pass

    @abstractmethod
    async def start(self):
        """Start message bus"""
        pass

    @abstractmethod
    async def stop(self):
        """Stop message bus (graceful shutdown)"""
        pass

    @abstractmethod
    async def get_stats(self) -> dict:
        """
        Get message bus statistics

        Returns:
            dict: Statistics info (queue length, dropped event count, subscriber count, etc.)
        """
        pass
