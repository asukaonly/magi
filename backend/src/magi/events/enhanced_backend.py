"""
Enhanced event system features

Implementation:
- Bounded priority queue (backpressure)
- Dual propagation pattern support
- Load-balanced dispatching
- Event filter mechanism
- Error isolation
"""
import asyncio
import heapq
import time
from typing import Callable, Dict, List, Optional, Set
from collections import defaultdict
from enum import Enum
from .events import Event, EventLevel
from .backend import MessageBusBackend


class PropagationMode(Enum):
    """Propagation mode"""
    BROADCAST = "broadcast"      # broadcast: all subscribers receive
    COMPETING = "competing"      # competing: only one subscriber receives (lowest load)
    round_RObin = "round_robin"  # round-robin: distribute to subscribers in turn


class DropPolicy(Enum):
    """Drop policy"""
    reject = "reject"                    # reject new event
    oldEST = "oldest"                    # drop oldest event
    LOWEST_PRIORITY = "lowest_priority" # drop lowest priority event


class BoundedpriorityQueue:
    """
    Bounded priority queue

    Features:
    - Backpressure mechanism
    - Multiple drop policies
    - Priority guarantee
    """

    def __init__(
        self,
        max_size: int = 1000,
        drop_policy: DropPolicy = DropPolicy.LOWEST_PRIORITY,
    ):
        """
        Initialize bounded priority queue

        Args:
            max_size: maximum queue length
            drop_policy: drop policy
        """
        self.max_size = max_size
        self.drop_policy = drop_policy

        # Priority queue
        # Elements: (-priority, timestamp, event)
        self._queue: List[tuple] = []
        self._lock = asyncio.Lock()
        self._counter = 0

        # Statistics
        self._stats = {
            "enqueued": 0,
            "dequeued": 0,
            "dropped": 0,
            "rejected": 0,
        }

    async def enqueue(self, event: Event) -> bool:
        """
        Enqueue (with backpressure)

        Args:
            event: Event

        Returns:
            Whether enqueue was successful
        """
        async with self._lock:
            # Check if the queue is full
            if len(self._queue) >= self.max_size:
                return await self._handle_queue_full(event)

            # Enqueue
            priority = -event.level.value
            timestamp = time.time()
            heapq.heappush(self._queue, (priority, self._counter, event))
            self._counter += 1

            self._stats["enqueued"] += 1
            return True

    async def dequeue(self, timeout: float = 1.0) -> Optional[Event]:
        """
        Dequeue

        Args:
            timeout: timeout duration

        Returns:
            Event or None
        """
        try:
            async with self._lock:
                if not self._queue:
                    return None

                _, _, event = heapq.heappop(self._queue)
                self._stats["dequeued"] += 1
                return event

        except asyncio.CancelledError:
            raise  # Re-raise to allow proper cancellation
        except Exception:
            return None

    async def _handle_queue_full(self, event: Event) -> bool:
        """
        Handle queue full condition

        Args:
            event: new event

        Returns:
            Whether enqueue was successful
        """
        if self.drop_policy == DropPolicy.reject:
            self._stats["rejected"] += 1
            return False

        elif self.drop_policy == DropPolicy.OLDEST:
            # Drop the oldest
            if self._queue:
                heapq.heappop(self._queue)
                self._stats["dropped"] += 1

            # Then enqueue the new event
            priority = -event.level.value
            heapq.heappush(self._queue, (priority, self._counter, event))
            self._counter += 1
            self._stats["enqueued"] += 1
            return True

        elif self.drop_policy == DropPolicy.LOWEST_PRIORITY:
            # Compare new event with the lowest priority in the queue
            if self._queue:
                lowest_priority = -self._queue[0][0]
                new_priority = -event.level.value

                if new_priority > lowest_priority:
                    # New event has lower priority, drop it
                    self._stats["rejected"] += 1
                    return False
                else:
                    # New event has higher or equal priority, drop the lowest priority event
                    heapq.heappop(self._queue)
                    self._stats["dropped"] += 1

            # Enqueue new event
            priority = -event.level.value
            heapq.heappush(self._queue, (priority, self._counter, event))
            self._counter += 1
            self._stats["enqueued"] += 1
            return True

        return False

    def size(self) -> int:
        """Get queue size"""
        return len(self._queue)

    def is_empty(self) -> bool:
        """Check if empty"""
        return len(self._queue) == 0

    def is_full(self) -> bool:
        """Check if full"""
        return len(self._queue) >= self.max_size

    def get_stats(self) -> dict:
        """Get statistics"""
        return {
            **self._stats,
            "current_size": len(self._queue),
            "max_size": self.max_size,
            "utilization": len(self._queue) / self.max_size,
        }


class LoadAwareDispatcher:
    """
    Load-aware dispatcher

    Performs load balancing based on handler pending counts
    """

    def __init__(self):
        """Initialize dispatcher"""
        # Handler pending counts
        self._handler_pending: Dict[Callable, int] = defaultdict(int)

        # Round-robin index
        self._round_robin_index: Dict[str, int] = {}

    def select_cometing_handler(
        self,
        subscriptions: List[Dict],
        event_type: str,
    ) -> Optional[Dict]:
        """
        Select handler for competing mode (lowest load)

        Args:
            subscriptions: subscription list
            event_type: event type

        Returns:
            Selected subscription or None
        """
        if not subscriptions:
            return None

        # Select the handler with the fewest pending tasks
        selected = min(
            subscriptions,
            key=lambda s: self._handler_pending[s["handler"]]
        )

        return selected

    def select_round_robin_handler(
        self,
        subscriptions: List[Dict],
        event_type: str,
    ) -> Optional[Dict]:
        """
        Select handler for round-robin mode

        Args:
            subscriptions: subscription list
            event_type: event type

        Returns:
            Selected subscription or None
        """
        if not subscriptions:
            return None

        # Get or initialize index
        index = self._round_robin_index.get(event_type, 0)
        total = len(subscriptions)

        selected = subscriptions[index % total]
        self._round_robin_index[event_type] = (index + 1) % total

        return selected

    def increment_pending(self, handler: Callable):
        """Increment pending count"""
        self._handler_pending[handler] += 1

    def decrement_pending(self, handler: Callable):
        """Decrement pending count"""
        self._handler_pending[handler] -= 1
        if self._handler_pending[handler] < 0:
            self._handler_pending[handler] = 0

    def get_pending_count(self, handler: Callable) -> int:
        """Get pending count"""
        return self._handler_pending.get(handler, 0)

    def get_all_pending(self) -> Dict[Callable, int]:
        """Get pending counts for all handlers"""
        return self._handler_pending.copy()


class EnhancedMemoryMessageBackend(MessageBusBackend):
    """
    Enhanced in-memory message backend

    Full implementation:
    - Dual propagation modes (BROADCAST/COMPETING/ROUND_ROBIN)
    - Backpressure mechanism (BoundedPriorityQueue)
    - Load-balanced dispatching (LoadAwareDispatcher)
    - Event filter mechanism
    - Error isolation
    - Graceful start/stop
    """

    def __init__(
        self,
        max_queue_size: int = 1000,
        num_workers: int = 4,
        drop_policy: DropPolicy = DropPolicy.LOWEST_PRIORITY,
    ):
        """
        Initialize enhanced message backend

        Args:
            max_queue_size: maximum queue length
            num_workers: number of workers
            drop_policy: drop policy
        """
        # Use bounded priority queue
        self._queue = BoundedpriorityQueue(
            max_size=max_queue_size,
            drop_policy=drop_policy,
        )

        # Load-balanced dispatcher
        self._dispatcher = LoadAwareDispatcher()

        # Subscription info
        # {event_type: [subscription]}
        self._subscriptions: Dict[str, List[Dict]] = defaultdict(list)
        self._subscription_index: Dict[str, Dict] = {}

        # worker management
        self._workers: List[asyncio.Task] = []
        self._running = False
        self._shutdown_requested = False

        # Statistics
        self._stats = {
            "published_count": 0,
            "processed_count": 0,
            "error_count": 0,
            "broadcast_count": 0,
            "competing_count": 0,
            "round_robin_count": 0,
        }

    async def publish(self, event: Event) -> bool:
        """
        Publish event

        Args:
            event: Event

        Returns:
            Whether publish was successful
        """
        # Check if shutdown is in progress
        if self._shutdown_requested:
            return False

        # Enqueue
        success = await self._queue.enqueue(event)

        if success:
            self._stats["published_count"] += 1
        else:
            self._stats["error_count"] += 1

        return success

    async def subscribe(
        self,
        event_type: str,
        handler: Callable,
        propagation_mode: PropagationMode = PropagationMode.BROADCAST,
        filter_func: Optional[Callable[[Event], bool]] = None,
    ) -> str:
        """
        Subscribe to event

        Args:
            event_type: event type
            handler: handler function
            propagation_mode: propagation mode
            filter_func: filter function

        Returns:
            subscription id
        """
        subscription_id = f"{event_type}_{id(handler)}_{time.time_ns()}"

        subscription = {
            "id": subscription_id,
            "event_type": event_type,
            "handler": handler,
            "mode": propagation_mode.value,
            "filter_func": filter_func,
        }

        self._subscriptions[event_type].append(subscription)
        self._subscription_index[subscription_id] = subscription

        return subscription_id

    async def unsubscribe(self, subscription_id: str) -> bool:
        """
        Unsubscribe

        Args:
            subscription_id: subscription id

        Returns:
            Whether successful
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
        """start message bus"""
        if self._running:
            return

        self._running = True
        self._shutdown_requested = False

        # Start worker pool
        self._workers = [
            asyncio.create_task(self._worker(i))
            for i in range(4)  # Fixed 4 workers
        ]

    async def stop(self):
        """Stop message bus (graceful shutdown)"""
        if not self._running:
            return

        # Request shutdown
        self._shutdown_requested = True

        # Wait for queue to drain or timeout
        timeout = 30  # seconds
        start_time = time.time()

        while not self._queue.is_empty() and (time.time() - start_time) < timeout:
            await asyncio.sleep(0.1)

        # Stop workers
        self._running = False

        for worker in self._workers:
            worker.cancel()

        # Wait for workers to finish
        await asyncio.gather(*self._workers, return_exceptions=True)

    async def _worker(self, worker_id: int):
        """
        Worker event processor

        Args:
            worker_id: worker id
        """
        while self._running:
            try:
                # Get event from queue
                event = await self._queue.dequeue()

                if event is None:
                    # Queue is empty, sleep briefly and retry
                    await asyncio.sleep(0.01)
                    continue

                # Process event
                await self._process_event(event)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._stats["error_count"] += 1

    async def _process_event(self, event: Event):
        """
        Process event (dispatch by propagation mode)

        Args:
            event: Event
        """
        subscriptions = self._subscriptions.get(event.type, [])

        if not subscriptions:
            return

        # Group by propagation mode
        broadcast_subs = []
        competing_subs = []
        round_robin_subs = []

        for sub in subscriptions:
            mode = sub.get("mode", "broadcast")
            if mode == "broadcast":
                broadcast_subs.append(sub)
            elif mode == "competing":
                competing_subs.append(sub)
            elif mode == "round_robin":
                round_robin_subs.append(sub)

        # Broadcast mode: all subscribers receive
        for sub in broadcast_subs:
            await self._handle_event(sub, event)
            self._stats["broadcast_count"] += 1

        # Competing mode: subscriber with lowest load receives
        if competing_subs:
            selected = self._dispatcher.select_cometing_handler(
                competing_subs,
                event.type
            )
            if selected:
                await self._handle_event(selected, event)
                self._stats["competing_count"] += 1

        # Round-robin mode: distribute in turn
        if round_robin_subs:
            selected = self._dispatcher.select_round_robin_handler(
                round_robin_subs,
                event.type
            )
            if selected:
                await self._handle_event(selected, event)
                self._stats["round_robin_count"] += 1

    async def _handle_event(self, subscription: Dict, event: Event):
        """
        Call handler to process event (with error isolation)

        Args:
            subscription: subscription info
            event: Event
        """
        # Check filter function
        filter_func = subscription.get("filter_func")
        if filter_func:
            try:
                if not filter_func(event):
                    return  # Filtered out
            except Exception:
                # Filter function error, do not filter by default
                pass

        handler = subscription["handler"]

        # Increment pending count
        self._dispatcher.increment_pending(handler)

        try:
            # Call handler
            if asyncio.iscoroutinefunction(handler):
                await handler(event)
            else:
                handler(event)

            self._stats["processed_count"] += 1

        except Exception as e:
            # Error isolation: single handler failure does not affect others
            self._stats["error_count"] += 1

        finally:
            # Decrement pending count
            self._dispatcher.decrement_pending(handler)

    def get_stats(self) -> dict:
        """
        Get statistics

        Returns:
            Statistics
        """
        return {
            **self._stats,
            "queue_stats": self._queue.get_stats(),
            "subscription_count": len(self._subscription_index),
            "worker_count": len(self._workers),
            "running": self._running,
            "pending_stats": self._dispatcher.get_all_pending(),
        }
