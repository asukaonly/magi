"""
事件系统增强功能

实现：
- BoundedPriorityQueue（背压机制）
- 双传播模式完善
- 负载均衡调度
- 事件过滤机制
- 错误隔离
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
    """传播模式"""
    BROADCAST = "broadcast"      # 广播：所有订阅者都收到
    COMPETING = "competing"      # 竞争：只有一个订阅者收到（负载最低的）
    ROUND_ROBIN = "round_robin"  # 轮询：依次分发给订阅者


class DropPolicy(Enum):
    """丢弃策略"""
    REJECT = "reject"                    # 拒绝新事件
    OLDEST = "oldest"                    # 丢弃最旧事件
    LOWEST_PRIORITY = "lowest_priority" # 丢弃最低优先级事件


class BoundedPriorityQueue:
    """
    有界优先级队列

    特性：
    - 背压机制（Backpressure）
    - 多种丢弃策略
    - 优先级保证
    """

    def __init__(
        self,
        max_size: int = 1000,
        drop_policy: DropPolicy = DropPolicy.LOWEST_PRIORITY,
    ):
        """
        初始化有界优先级队列

        Args:
            max_size: 队列最大长度
            drop_policy: 丢弃策略
        """
        self.max_size = max_size
        self.drop_policy = drop_policy

        # 优先级队列
        # 元素：(-priority, timestamp, event)
        self._queue: List[tuple] = []
        self._lock = asyncio.Lock()
        self._counter = 0

        # 统计
        self._stats = {
            "enqueued": 0,
            "dequeued": 0,
            "dropped": 0,
            "rejected": 0,
        }

    async def enqueue(self, event: Event) -> bool:
        """
        入队（带背压）

        Args:
            event: 事件

        Returns:
            是否成功入队
        """
        async with self._lock:
            # 检查队列是否已满
            if len(self._queue) >= self.max_size:
                return await self._handle_queue_full(event)

            # 入队
            priority = -event.level.value
            timestamp = time.time()
            heapq.heappush(self._queue, (priority, self._counter, event))
            self._counter += 1

            self._stats["enqueued"] += 1
            return True

    async def dequeue(self, timeout: float = 1.0) -> Optional[Event]:
        """
        出队

        Args:
            timeout: 超时时间

        Returns:
            事件或None
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
        处理队列满的情况

        Args:
            event: 新事件

        Returns:
            是否成功入队
        """
        if self.drop_policy == DropPolicy.REJECT:
            self._stats["rejected"] += 1
            return False

        elif self.drop_policy == DropPolicy.OLDEST:
            # 丢弃最旧的
            if self._queue:
                heapq.heappop(self._queue)
                self._stats["dropped"] += 1

            # 然后入队新事件
            priority = -event.level.value
            heapq.heappush(self._queue, (priority, self._counter, event))
            self._counter += 1
            self._stats["enqueued"] += 1
            return True

        elif self.drop_policy == DropPolicy.LOWEST_PRIORITY:
            # 比较新事件和队列中最低优先级
            if self._queue:
                lowest_priority = -self._queue[0][0]
                new_priority = -event.level.value

                if new_priority > lowest_priority:
                    # 新事件优先级更低，丢弃新事件
                    self._stats["rejected"] += 1
                    return False
                else:
                    # 新事件优先级更高或相等，丢弃最低优先级事件
                    heapq.heappop(self._queue)
                    self._stats["dropped"] += 1

            # 入队新事件
            priority = -event.level.value
            heapq.heappush(self._queue, (priority, self._counter, event))
            self._counter += 1
            self._stats["enqueued"] += 1
            return True

        return False

    def size(self) -> int:
        """获取队列大小"""
        return len(self._queue)

    def is_empty(self) -> bool:
        """是否为空"""
        return len(self._queue) == 0

    def is_full(self) -> bool:
        """是否已满"""
        return len(self._queue) >= self.max_size

    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            **self._stats,
            "current_size": len(self._queue),
            "max_size": self.max_size,
            "utilization": len(self._queue) / self.max_size,
        }


class LoadAwareDispatcher:
    """
    负载感知的调度器

    根据handler的pending数量进行负载均衡
    """

    def __init__(self):
        """初始化调度器"""
        # Handler的pending计数
        self._handler_pending: Dict[Callable, int] = defaultdict(int)

        # Round-robin索引
        self._round_robin_index: Dict[str, int] = {}

    def select_cometing_handler(
        self,
        subscriptions: List[Dict],
        event_type: str,
    ) -> Optional[Dict]:
        """
        选择竞争模式的handler（负载最低的）

        Args:
            subscriptions: 订阅列表
            event_type: 事件类型

        Returns:
            选中的订阅或None
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
        选择轮询模式的handler

        Args:
            subscriptions: 订阅列表
            event_type: 事件类型

        Returns:
            选中的订阅或None
        """
        if not subscriptions:
            return None

        # 获取或初始化索引
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
        """获取pending计数"""
        return self._handler_pending.get(handler, 0)

    def get_all_pending(self) -> Dict[Callable, int]:
        """获取所有handler的pending计数"""
        return self._handler_pending.copy()


class EnhancedMemoryMessageBackend(MessageBusBackend):
    """
    增强的内存消息后端

    完整实现：
    - 双传播模式（BROADCAST/COMPETING/ROUND_ROBIN）
    - 背压机制（BoundedPriorityQueue）
    - 负载均衡调度（LoadAwareDispatcher）
    - 事件过滤机制
    - 错误隔离
    - 优雅启停
    """

    def __init__(
        self,
        max_queue_size: int = 1000,
        num_workers: int = 4,
        drop_policy: DropPolicy = DropPolicy.LOWEST_PRIORITY,
    ):
        """
        初始化增强的消息后端

        Args:
            max_queue_size: 队列最大长度
            num_workers: Worker数量
            drop_policy: 丢弃策略
        """
        # 使用有界优先级队列
        self._queue = BoundedPriorityQueue(
            max_size=max_queue_size,
            drop_policy=drop_policy,
        )

        # 负载均衡调度器
        self._dispatcher = LoadAwareDispatcher()

        # 订阅信息
        # {event_type: [subscription]}
        self._subscriptions: Dict[str, List[Dict]] = defaultdict(list)
        self._subscription_index: Dict[str, Dict] = {}

        # Worker管理
        self._workers: List[asyncio.Task] = []
        self._running = False
        self._shutdown_requested = False

        # 统计信息
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
        发布事件

        Args:
            event: 事件

        Returns:
            是否成功发布
        """
        # 检查是否正在关闭
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
        propagation_mode: PropagationMode = PropagationMode.BROADCAST,
        filter_func: Optional[Callable[[Event], bool]] = None,
    ) -> str:
        """
        订阅事件

        Args:
            event_type: 事件类型
            handler: 处理函数
            propagation_mode: 传播模式
            filter_func: 过滤函数

        Returns:
            订阅ID
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
        取消订阅

        Args:
            subscription_id: 订阅ID

        Returns:
            是否成功
        """
        if subscription_id not in self._subscription_index:
            return False

        subscription = self._subscription_index[subscription_id]
        event_type = subscription["event_type"]

        # 从订阅列表中移除
        self._subscriptions[event_type] = [
            s for s in self._subscriptions[event_type] if s["id"] != subscription_id
        ]

        del self._subscription_index[subscription_id]
        return True

    async def start(self):
        """启动消息总线"""
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
        """停止消息总线（优雅关闭）"""
        if not self._running:
            return

        # 请求关闭
        self._shutdown_requested = True

        # 等待队列清空或超时
        timeout = 30  # 秒
        start_time = time.time()

        while not self._queue.is_empty() and (time.time() - start_time) < timeout:
            await asyncio.sleep(0.1)

        # 停止worker
        self._running = False

        for worker in self._workers:
            worker.cancel()

        # 等待worker结束
        await asyncio.gather(*self._workers, return_exceptions=True)

    async def _worker(self, worker_id: int):
        """
        Worker处理事件

        Args:
            worker_id: Worker ID
        """
        while self._running:
            try:
                # 从队列获取事件
                event = await self._queue.dequeue()

                if event is None:
                    # 队列为空，短暂休眠后重试
                    await asyncio.sleep(0.01)
                    continue

                # 处理事件
                await self._process_event(event)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._stats["error_count"] += 1

    async def _process_event(self, event: Event):
        """
        处理事件（根据传播模式分发）

        Args:
            event: 事件
        """
        subscriptions = self._subscriptions.get(event.type, [])

        if not subscriptions:
            return

        # 按传播模式分组
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

        # 广播模式：所有订阅者都收到
        for sub in broadcast_subs:
            await self._handle_event(sub, event)
            self._stats["broadcast_count"] += 1

        # 竞争模式：负载最低的订阅者收到
        if competing_subs:
            selected = self._dispatcher.select_cometing_handler(
                competing_subs,
                event.type
            )
            if selected:
                await self._handle_event(selected, event)
                self._stats["competing_count"] += 1

        # 轮询模式：依次分发
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
        调用handler处理事件（带错误隔离）

        Args:
            subscription: 订阅信息
            event: 事件
        """
        # 检查过滤函数
        filter_func = subscription.get("filter_func")
        if filter_func:
            try:
                if not filter_func(event):
                    return  # 被过滤
            except Exception:
                # 过滤函数出错，默认不过滤
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
            # 错误隔离：单个handler失败不影响其他
            self._stats["error_count"] += 1

        finally:
            # 减少pending计数
            self._dispatcher.decrement_pending(handler)

    def get_stats(self) -> dict:
        """
        获取统计信息

        Returns:
            统计信息
        """
        return {
            **self._stats,
            "queue_stats": self._queue.get_stats(),
            "subscription_count": len(self._subscription_index),
            "worker_count": len(self._workers),
            "running": self._running,
            "pending_stats": self._dispatcher.get_all_pending(),
        }
