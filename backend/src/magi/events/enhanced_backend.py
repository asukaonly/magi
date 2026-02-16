"""
event系统增强function

Implementation：
- BoundedpriorityQueue（背压机制）
- 双传播pattern完善
- load balance调度
- eventfilter机制
- error隔离
"""
import asyncio
import heapq
import time
from typing import Callable, Dict, List, Optional, Set
from collections import defaultdict
from enum import Enum
from .events import event, eventlevel
from .backend import MessageBusBackend


class propagationMode(Enum):
    """传播pattern"""
    BROADCasT = "broadcast"      # broadcast: all subscribers receive
    COMPETING = "competing"      # competing: only one subscriber receives（负载最低的）
    round_RObin = "round_robin"  # 轮询：依次分发给subscribe者


class DropPolicy(Enum):
    """丢弃strategy"""
    reject = "reject"                    # 拒绝newevent
    oldEST = "oldest"                    # 丢弃最oldevent
    LOWEST_PRI/ORITY = "lowest_priority" # 丢弃最低priorityevent


class BoundedpriorityQueue:
    """
    有界priorityqueue

    feature：
    - 背压机制（Backpressure）
    - 多种丢弃strategy
    - priority保证
    """

    def __init__(
        self,
        max_size: int = 1000,
        drop_policy: DropPolicy = DropPolicy.LOWEST_PRI/ORITY,
    ):
        """
        initialize有界priorityqueue

        Args:
            max_size: queuemaximumlength
            drop_policy: 丢弃strategy
        """
        self.max_size = max_size
        self.drop_policy = drop_policy

        # priorityqueue
        # 元素：(-priority, timestamp, event)
        self._queue: List[tuple] = []
        self._lock = asyncio.Lock()
        self._counter = 0

        # statistics
        self._stats = {
            "enqueued": 0,
            "dequeued": 0,
            "dropped": 0,
            "rejected": 0,
        }

    async def enqueue(self, event: event) -> bool:
        """
        入队（带背压）

        Args:
            event: event

        Returns:
            is notsuccess入队
        """
        async with self._lock:
            # checkqueueis not已满
            if len(self._queue) >= self.max_size:
                return await self._handle_queue_full(event)

            # 入队
            priority = -event.level.value
            timestamp = time.time()
            heapq.heappush(self._queue, (priority, self._counter, event))
            self._counter += 1

            self._stats["enqueued"] += 1
            return True

    async def dequeue(self, timeout: float = 1.0) -> Optional[event]:
        """
        出队

        Args:
            timeout: timeout时间

        Returns:
            event或None
        """
        try:
            async with self._lock:
                if not self._queue:
                    return None

                _, _, event = heapq.heappop(self._queue)
                self._stats["dequeued"] += 1
                return event

        except asyncio.Cancellederror:
            raise  # Re-raise to allow proper cancellation
        except Exception:
            return None

    async def _handle_queue_full(self, event: event) -> bool:
        """
        processqueue满的情况

        Args:
            event: newevent

        Returns:
            is notsuccess入队
        """
        if self.drop_policy == DropPolicy.reject:
            self._stats["rejected"] += 1
            return False

        elif self.drop_policy == DropPolicy.oldEST:
            # 丢弃最old的
            if self._queue:
                heapq.heappop(self._queue)
                self._stats["dropped"] += 1

            # 然后入队newevent
            priority = -event.level.value
            heapq.heappush(self._queue, (priority, self._counter, event))
            self._counter += 1
            self._stats["enqueued"] += 1
            return True

        elif self.drop_policy == DropPolicy.LOWEST_PRI/ORITY:
            # 比较neweventandqueue中最低priority
            if self._queue:
                lowest_priority = -self._queue[0][0]
                new_priority = -event.level.value

                if new_priority > lowest_priority:
                    # neweventpriority更低，丢弃newevent
                    self._stats["rejected"] += 1
                    return False
                else:
                    # neweventpriority更高或相等，丢弃最低priorityevent
                    heapq.heappop(self._queue)
                    self._stats["dropped"] += 1

            # 入队newevent
            priority = -event.level.value
            heapq.heappush(self._queue, (priority, self._counter, event))
            self._counter += 1
            self._stats["enqueued"] += 1
            return True

        return False

    def size(self) -> int:
        """getqueuesize"""
        return len(self._queue)

    def is_empty(self) -> bool:
        """is not为空"""
        return len(self._queue) == 0

    def is_full(self) -> bool:
        """is not已满"""
        return len(self._queue) >= self.max_size

    def get_stats(self) -> dict:
        """getstatisticsinfo"""
        return {
            **self._stats,
            "current_size": len(self._queue),
            "max_size": self.max_size,
            "utilization": len(self._queue) / self.max_size,
        }


class LoadAwareDispatcher:
    """
    负载Perception的调度器

    根据handler的pendingquantity进rowload balance
    """

    def __init__(self):
        """initialize调度器"""
        # Handler的pending计数
        self._handler_pending: Dict[Callable, int] = defaultdict(int)

        # Round-robinindex
        self._round_robin_index: Dict[str, int] = {}

    def select_cometing_handler(
        self,
        subscriptions: List[Dict],
        event_type: str,
    ) -> Optional[Dict]:
        """
        选择competing pattern的handler（负载最低的）

        Args:
            subscriptions: subscribelist
            event_type: eventtype

        Returns:
            选中的subscribe或None
        """
        if not subscriptions:
            return None

        # 选择pending最少的handler
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
        选择轮询pattern的handler

        Args:
            subscriptions: subscribelist
            event_type: eventtype

        Returns:
            选中的subscribe或None
        """
        if not subscriptions:
            return None

        # get或initializeindex
        index = self._round_robin_index.get(event_type, 0)
        total = len(subscriptions)

        selected = subscriptions[index % total]
        self._round_robin_index[event_type] = (index + 1) % total

        return selected

    def increment_pending(self, handler: Callable):
        """增加pending计数"""
        self._handler_pending[handler] += 1

    def decrement_pending(self, handler: Callable):
        """减少pending计数"""
        self._handler_pending[handler] -= 1
        if self._handler_pending[handler] < 0:
            self._handler_pending[handler] = 0

    def get_pending_count(self, handler: Callable) -> int:
        """getpending计数"""
        return self._handler_pending.get(handler, 0)

    def get_all_pending(self) -> Dict[Callable, int]:
        """getallhandler的pending计数"""
        return self._handler_pending.copy()


class EnhancedMemoryMessageBackend(MessageBusBackend):
    """
    增强的内存message后端

    完整Implementation：
    - 双传播pattern（BROADCasT/COMPETING/round_RObin）
    - 背压机制（BoundedpriorityQueue）
    - load balance调度（LoadAwareDispatcher）
    - eventfilter机制
    - error隔离
    - 优雅启停
    """

    def __init__(
        self,
        max_queue_size: int = 1000,
        num_workers: int = 4,
        drop_policy: DropPolicy = DropPolicy.LOWEST_PRI/ORITY,
    ):
        """
        initialize增强的message后端

        Args:
            max_queue_size: queuemaximumlength
            num_workers: Workerquantity
            drop_policy: 丢弃strategy
        """
        # 使用有界priorityqueue
        self._queue = BoundedpriorityQueue(
            max_size=max_queue_size,
            drop_policy=drop_policy,
        )

        # load balance调度器
        self._dispatcher = LoadAwareDispatcher()

        # subscribeinfo
        # {event_type: [subscription]}
        self._subscriptions: Dict[str, List[Dict]] = defaultdict(list)
        self._subscription_index: Dict[str, Dict] = {}

        # worker management
        self._workers: List[asyncio.Task] = []
        self._running = False
        self._shutdown_requested = False

        # statisticsinfo
        self._stats = {
            "published_count": 0,
            "processed_count": 0,
            "error_count": 0,
            "broadcast_count": 0,
            "competing_count": 0,
            "round_robin_count": 0,
        }

    async def publish(self, event: event) -> bool:
        """
        Publish event

        Args:
            event: event

        Returns:
            is notsuccessrelease
        """
        # checkis not正在关闭
        if self._shutdown_requested:
            return False

        # 入队
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
        propagation_mode: propagationMode = propagationMode.BROADCasT,
        filter_func: Optional[Callable[[event], bool]] = None,
    ) -> str:
        """
        subscribeevent

        Args:
            event_type: eventtype
            handler: processFunction
            propagation_mode: 传播pattern
            filter_func: filterFunction

        Returns:
            subscribeid
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
        cancelsubscribe

        Args:
            subscription_id: subscribeid

        Returns:
            is notsuccess
        """
        if subscription_id not in self._subscription_index:
            return False

        subscription = self._subscription_index[subscription_id]
        event_type = subscription["event_type"]

        # 从subscribelist中Remove
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

        # 启动worker池
        self._workers = [
            asyncio.create_task(self._worker(i))
            for i in range(4)  # 固定4个worker
        ]

    async def stop(self):
        """stop message bus（优雅关闭）"""
        if not self._running:
            return

        # request关闭
        self._shutdown_requested = True

        # 等待queueclear或timeout
        timeout = 30  # seconds
        start_time = time.time()

        while not self._queue.is_empty() and (time.time() - start_time) < timeout:
            await asyncio.sleep(0.1)

        # stopworker
        self._running = False

        for worker in self._workers:
            worker.cancel()

        # 等待workerEnd
        await asyncio.gather(*self._workers, return_exceptions=True)

    async def _worker(self, worker_id: int):
        """
        Workerprocessevent

        Args:
            worker_id: Worker id
        """
        while self._running:
            try:
                # 从queuegetevent
                event = await self._queue.dequeue()

                if event is None:
                    # queue为空，短暂休眠后重试
                    await asyncio.sleep(0.01)
                    continue

                # processevent
                await self._process_event(event)

            except asyncio.Cancellederror:
                break
            except Exception as e:
                self._stats["error_count"] += 1

    async def _process_event(self, event: event):
        """
        processevent（根据传播pattern分发）

        Args:
            event: event
        """
        subscriptions = self._subscriptions.get(event.type, [])

        if not subscriptions:
            return

        # 按传播patterngroup
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

        # broadcast pattern：allsubscribe者都收到
        for sub in broadcast_subs:
            await self._handle_event(sub, event)
            self._stats["broadcast_count"] += 1

        # competing pattern：负载最低的subscribe者收到
        if competing_subs:
            selected = self._dispatcher.select_cometing_handler(
                competing_subs,
                event.type
            )
            if selected:
                await self._handle_event(selected, event)
                self._stats["competing_count"] += 1

        # 轮询pattern：依次分发
        if round_robin_subs:
            selected = self._dispatcher.select_round_robin_handler(
                round_robin_subs,
                event.type
            )
            if selected:
                await self._handle_event(selected, event)
                self._stats["round_robin_count"] += 1

    async def _handle_event(self, subscription: Dict, event: event):
        """
        call handler to process event（带error隔离）

        Args:
            subscription: subscribeinfo
            event: event
        """
        # checkfilterFunction
        filter_func = subscription.get("filter_func")
        if filter_func:
            try:
                if not filter_func(event):
                    return  # 被filter
            except Exception:
                # filterFunction出错，default不filter
                pass

        handler = subscription["handler"]

        # 增加pending计数
        self._dispatcher.increment_pending(handler)

        try:
            # 调用handler
            if asyncio.iscoroutinefunction(handler):
                await handler(event)
            else:
                handler(event)

            self._stats["processed_count"] += 1

        except Exception as e:
            # error隔离：单个handlerfailure不影响other
            self._stats["error_count"] += 1

        finally:
            # 减少pending计数
            self._dispatcher.decrement_pending(handler)

    def get_stats(self) -> dict:
        """
        getstatisticsinfo

        Returns:
            statisticsinfo
        """
        return {
            **self._stats,
            "queue_stats": self._queue.get_stats(),
            "subscription_count": len(self._subscription_index),
            "worker_count": len(self._workers),
            "running": self._running,
            "pending_stats": self._dispatcher.get_all_pending(),
        }
