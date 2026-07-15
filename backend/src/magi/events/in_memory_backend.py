"""In-process message bus backend with an in-memory work queue."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Callable, Dict, List, Optional

from .backend import MessageBusBackend
from .events import Event, REQUIRE_SUBSCRIBER_DELIVERY_METADATA_KEY

logger = logging.getLogger(__name__)


@dataclass
class InMemoryBackendStats:
    """Runtime statistics for the in-process message bus."""

    published_count: int = 0
    dropped_count: int = 0
    processed_count: int = 0
    error_count: int = 0
    handler_error_count: int = 0
    handler_timeout_count: int = 0
    broadcast_parallelism: int = 0


class InMemoryMessageBusBackend(MessageBusBackend):
    """In-process message bus with local async dispatch and no durable storage."""

    def __init__(
        self,
        *,
        max_queue_size: int = 1000,
        num_workers: int = 4,
        broadcast_max_concurrency: int = 8,
        handler_timeout_seconds: float = 2.0,
    ) -> None:
        super().__init__()
        self.max_queue_size = max_queue_size
        self.num_workers = num_workers
        self.broadcast_max_concurrency = broadcast_max_concurrency
        self.handler_timeout_seconds = handler_timeout_seconds

        self._subscriptions: Dict[str, List[Dict[str, object]]] = defaultdict(list)
        self._subscription_index: Dict[str, Dict[str, object]] = {}
        self._handler_pending: Dict[Callable, int] = defaultdict(int)
        self._workers: List[asyncio.Task] = []
        self._running = False
        self._queue: asyncio.Queue[Event] | None = None
        self._broadcast_semaphore: asyncio.Semaphore | None = None
        self._active_dispatches = 0
        self._stats = InMemoryBackendStats(broadcast_parallelism=broadcast_max_concurrency)

    async def _publish_bound(self, event: Event) -> bool:
        """Publish an event to the local in-process queue."""
        if not self._running or self._queue is None:
            logger.warning("Dropping event because message bus is not running", extra={"event_type": event.type})
            self._stats.dropped_count += 1
            return False

        if self._requires_subscriber_delivery(event) and not self._matching_subscriptions(event):
            logger.warning(
                "Dropping critical event because this runtime has no local subscribers",
                extra={
                    "event_type": event.type,
                    "event_source": event.source,
                    "correlation_id": event.correlation_id,
                },
            )
            self._stats.dropped_count += 1
            return False

        if self._queue.full():
            logger.warning("Dropping event because in-memory message bus is full", extra={"event_type": event.type})
            self._stats.dropped_count += 1
            return False

        await self._queue.put(event)
        self._stats.published_count += 1
        return True

    async def subscribe(
        self,
        event_type: str,
        handler: Callable,
        propagation_mode: str = "broadcast",
        filter_func: Optional[Callable[[Event], bool]] = None,
    ) -> str:
        """Register a local subscriber for one event type."""
        subscription_id = f"{event_type}_{id(handler)}_{asyncio.get_running_loop().time()}"
        subscription = {
            "id": subscription_id,
            "event_type": event_type,
            "handler": handler,
            "mode": propagation_mode,
            "filter_func": filter_func,
        }
        self._subscriptions[event_type].append(subscription)
        self._subscription_index[subscription_id] = subscription
        return subscription_id

    async def unsubscribe(self, subscription_id: str) -> bool:
        """Remove a local subscription."""
        subscription = self._subscription_index.pop(subscription_id, None)
        if subscription is None:
            return False

        event_type = str(subscription["event_type"])
        self._subscriptions[event_type] = [
            item for item in self._subscriptions[event_type] if item["id"] != subscription_id
        ]
        return True

    async def start(self):
        """Start worker tasks for local dispatch."""
        if self._running:
            return

        self._queue = asyncio.Queue(maxsize=self.max_queue_size)
        self._broadcast_semaphore = asyncio.Semaphore(self.broadcast_max_concurrency)
        self._running = True
        self._workers = [asyncio.create_task(self._worker(index)) for index in range(self.num_workers)]

    async def stop(self):
        """Stop worker tasks after in-flight dispatch completes."""
        if not self._running:
            return

        self._running = False
        timeout_seconds = 30.0
        deadline = asyncio.get_running_loop().time() + timeout_seconds

        while asyncio.get_running_loop().time() < deadline:
            queue_length = self._queue.qsize() if self._queue is not None else 0
            if queue_length == 0 and self._active_dispatches == 0:
                break
            await asyncio.sleep(0.05)

        for worker in self._workers:
            worker.cancel()

        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers = []

    async def get_stats(self) -> dict:
        """Return message bus statistics."""
        queue_length = self._queue.qsize() if self._queue is not None else 0
        subscriber_count = len(self._subscription_index)
        return {
            **asdict(self._stats),
            "queue_length": queue_length,
            "subscriber_count": subscriber_count,
            "worker_count": self.num_workers,
            "max_queue_size": self.max_queue_size,
            "broadcast_max_concurrency": self.broadcast_max_concurrency,
            "handler_timeout_seconds": self.handler_timeout_seconds,
            "active_dispatches": self._active_dispatches,
            "running": self._running,
        }

    async def _worker(self, worker_id: int) -> None:
        del worker_id
        while self._running or (self._queue is not None and not self._queue.empty()):
            try:
                if self._queue is None:
                    return
                event = await asyncio.wait_for(self._queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                raise

            self._active_dispatches += 1
            try:
                processed = await self._process_event(event)
                if processed:
                    self._stats.processed_count += 1
                else:
                    self._stats.error_count += 1
            finally:
                self._active_dispatches = max(0, self._active_dispatches - 1)
                self._queue.task_done()

    async def _process_event(self, event: Event) -> bool:
        subscriptions = self._matching_subscriptions(event)
        if not subscriptions:
            return not self._requires_subscriber_delivery(event)

        broadcast_subscriptions = [item for item in subscriptions if item["mode"] == "broadcast"]
        competing_subscriptions = [item for item in subscriptions if item["mode"] == "competing"]

        all_success = True

        if broadcast_subscriptions:
            results = await asyncio.gather(
                *(self._handle_event_with_timeout(subscription, event) for subscription in broadcast_subscriptions),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, Exception) or result is False:
                    all_success = False

        if competing_subscriptions:
            subscription = min(
                competing_subscriptions,
                key=lambda item: self._handler_pending[item["handler"]],
            )
            result = await self._handle_event_with_timeout(subscription, event)
            if result is False:
                all_success = False

        return all_success

    async def _handle_event_with_timeout(self, subscription: Dict[str, object], event: Event) -> bool:
        handler = subscription["handler"]
        semaphore = self._broadcast_semaphore

        async def _run_handler() -> bool:
            self._handler_pending[handler] += 1
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
                return True
            finally:
                self._handler_pending[handler] = max(0, self._handler_pending[handler] - 1)

        try:
            if semaphore is None:
                return await asyncio.wait_for(_run_handler(), timeout=self.handler_timeout_seconds)
            async with semaphore:
                return await asyncio.wait_for(_run_handler(), timeout=self.handler_timeout_seconds)
        except asyncio.TimeoutError:
            self._stats.handler_timeout_count += 1
            logger.warning("Message bus handler timed out", extra={"event_type": event.type})
            return False
        except Exception as exc:
            self._stats.handler_error_count += 1
            logger.warning(
                "Message bus handler failed",
                extra={"event_type": event.type, "error": str(exc)},
            )
            return False

    def _matching_subscriptions(self, event: Event) -> List[Dict[str, object]]:
        subscriptions = list(self._subscriptions.get(event.type, []))
        if not subscriptions:
            return []

        matches: List[Dict[str, object]] = []
        for subscription in subscriptions:
            filter_func = subscription.get("filter_func")
            if filter_func is None:
                matches.append(subscription)
                continue

            try:
                if filter_func(event):
                    matches.append(subscription)
            except Exception as exc:
                self._stats.error_count += 1
                logger.warning(
                    "Message bus filter failed",
                    extra={"event_type": event.type, "error": str(exc)},
                )
        return matches

    @staticmethod
    def _requires_subscriber_delivery(event: Event) -> bool:
        return bool(event.metadata.get(REQUIRE_SUBSCRIBER_DELIVERY_METADATA_KEY))
