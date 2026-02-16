"""
Message Bus - Memory Backend Implementation
Memory queue based on asyncio.priorityQueue
"""
import asyncio
import heapq
import time
from typing import Callable, Dict, List, Optional, Set
from collections import defaultdict
from .backend import MessageBusBackend
from .events import event


class MemoryMessageBackend(MessageBusBackend):
    """
    Memory-based message queue backend

    Features:
    - Uses asyncio.priorityQueue for priority queue implementation
    - Fully async event processing, notttn-blocking publisher
    - Worker pool for concurrent event processing
    - error isolation: single handler failure does not affect others

    Limitations:
    - No persistence, unprocessed messages are lost after Agent restart
    """

    def __init__(
        self,
        max_queue_size: int = 1000,
        num_workers: int = 4,
        drop_policy: str = "lowest_priority",
    ):
        """
        initialize memory message backend

        Args:
            max_queue_size: Maximum queue length
            num_workers: Number of worker threads
            drop_policy: Drop policy when queue is full (oldest/lowest_priority/reject)
        """
        self.max_queue_size = max_queue_size
        self.num_workers = num_workers
        self.drop_policy = drop_policy

        # priority queue (using heapq)
        # Element format: (-priority, timestamp, event)
        # Note: lower priority value means higher priority, so we use negative sign
        self._queue: List[tuple] = []
        self._queue_lock = asyncio.Lock()

        # Subscription info
        # {event_type: [{subscription_id, handler, mode, filter_func}]}
        self._subscriptions: Dict[str, List[Dict]] = defaultdict(list)
        self._subscription_index: Dict[str, Dict] = {}  # {subscription_id: subscription_info}

        # Pending count (for load balancing)
        self._handler_pending: Dict[Callable, int] = defaultdict(int)

        # Worker management
        self._workers: List[asyncio.Task] = []
        self._running = False
        self._counter = 0  # Used to ensure uniqueness of queue elements

        # Statistics
        self._stats = {
            "published_count": 0,
            "dropped_count": 0,
            "processed_count": 0,
            "error_count": 0,
        }

    async def publish(self, event: event) -> bool:
        """
        Publish event to queue

        Args:
            event: event to publish

        Returns:
            bool: Whether the event was successfully published
        """
        async with self._queue_lock:
            # Check if queue is full
            if len(self._queue) >= self.max_queue_size:
                # Handle according to policy
                if self.drop_policy == "reject":
                    self._stats["dropped_count"] += 1
                    return False
                elif self.drop_policy == "oldest":
                    # Drop the oldest (queue head)
                    heapq.heappop(self._queue)
                    self._stats["dropped_count"] += 1
                elif self.drop_policy == "lowest_priority":
                    # Compare new event with lowest priority in queue
                    if self._queue:
                        lowest_priority = -self._queue[0][0]
                        if event.level.value > lowest_priority:
                            heapq.heappop(self._queue)
                            self._stats["dropped_count"] += 1
                        else:
                            # New event has lower priority, reject
                            self._stats["dropped_count"] += 1
                            return False

            # Add to priority queue
            # (-priority, counter, event) - counter ensures FIFO
            priority = -event.level.value
            self._counter += 1
            heapq.heappush(self._queue, (priority, self._counter, event))
            self._stats["published_count"] += 1
            return True

    async def subscribe(
        self,
        event_type: str,
        handler: Callable,
        propagation_mode: str = "broadcast",
        filter_func: Optional[Callable[[event], bool]] = None,
    ) -> str:
        """
        Subscribe to event

        Args:
            event_type: event type
            handler: Handler function
            propagation_mode: propagation mode (broadcast/competing)
            filter_func: Filter function

        Returns:
            str: Subscription id
        """
        subscription_id = f"{event_type}_{id(handler)}_{time.time()}"

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
        """
        Unsubscribe from event

        Args:
            subscription_id: Subscription id

        Returns:
            bool: Whether unsubscription was successful
        """
        if subscription_id not in self._subscription_index:
            return False

        subscription = self._subscription_index[subscription_id]
        event_type = subscription["event_type"]

        # Remove from subscription list
        self._subscriptions[event_type] = [
            s for s in self._subscriptions[event_type] if s["id"] != subscription_id
        ]

        del self._subscription_index[subscription_id]
        return True

    async def start(self):
        """Start message bus (start worker pool)"""
        if self._running:
            return

        self._running = True
        self._workers = [
            asyncio.create_task(self._worker(i)) for i in range(self.num_workers)
        ]

    async def stop(self):
        """Stop message bus (graceful shutdown)"""
        if not self._running:
            return

        self._running = False

        # Wait for queue to be processed or timeout
        timeout = 30  # seconds
        start_time = time.time()

        while self._queue and (time.time() - start_time) < timeout:
            await asyncio.sleep(0.1)

        # Cancel all workers
        for worker in self._workers:
            worker.cancel()

        # Wait for workers to finish
        await asyncio.gather(*self._workers, return_exceptions=True)

    async def _worker(self, worker_id: int):
        """
        Worker thread: fetch events from queue and process them

        Args:
            worker_id: Worker id
        """
        while self._running:
            try:
                # Get event from queue
                event = await self._get_next_event()

                if event is None:
                    await asyncio.sleep(0.1)
                    continue

                # process event
                await self._process_event(event)

            except asyncio.Cancellederror:
                break
            except Exception as e:
                self._stats["error_count"] += 1

    async def _get_next_event(self) -> Optional[event]:
        """Get next event from queue"""
        async with self._queue_lock:
            if not self._queue:
                return None

            _, _, event = heapq.heappop(self._queue)
            return event

    async def _process_event(self, event: event):
        """
        process event (dispatch to subscribers)

        Args:
            event: event to process
        """
        subscriptions = self._subscriptions.get(event.type, [])

        if not subscriptions:
            return

        # Handle according to propagation mode
        broadcast_subscriptions = [s for s in subscriptions if s["mode"] == "broadcast"]
        competing_subscriptions = [s for s in subscriptions if s["mode"] == "competing"]

        # broadcast mode: all subscribers receive the event
        for subscription in broadcast_subscriptions:
            await self._handle_event(subscription, event)

        # competing mode: only one subscriber receives the event (the one with lowest load)
        if competing_subscriptions:
            # Select handler with lowest pending count
            subscription = min(
                competing_subscriptions, key=lambda s: self._handler_pending[s["handler"]]
            )
            await self._handle_event(subscription, event)

    async def _handle_event(self, subscription: Dict, event: event):
        """
        Call single handler to process event

        Args:
            subscription: Subscription info
            event: event
        """
        # Check filter function
        if subscription["filter_func"]:
            try:
                if not subscription["filter_func"](event):
                    return
            except Exception:
                # Filter function error, default to not filtering
                pass

        handler = subscription["handler"]

        # Increment pending count
        self._handler_pending[handler] += 1

        try:
            # Call handler
            if asyncio.iscoroutinefunction(handler):
                await handler(event)
            else:
                handler(event)

            self._stats["processed_count"] += 1

        except Exception as e:
            # error isolation: single handler failure does not affect others
            self._stats["error_count"] += 1

        finally:
            # Decrement pending count
            self._handler_pending[handler] -= 1

    async def get_stats(self) -> dict:
        """
        Get statistics

        Returns:
            dict: Statistics info
        """
        return {
            **self._stats,
            "queue_size": len(self._queue),
            "max_queue_size": self.max_queue_size,
            "subscription_count": len(self._subscription_index),
            "worker_count": self.num_workers,
            "running": self._running,
        }
