"""
消息总线 - 内存后端实现
基于asyncio.PriorityQueue的内存队列
"""
import asyncio
import heapq
import time
from typing import Callable, Dict, List, Optional, Set
from collections import defaultdict
from .backend import MessageBusBackend
from .events import Event


class MemoryMessageBackend(MessageBusBackend):
    """
    基于内存的消息队列后端

    特点：
    - 使用asyncio.PriorityQueue实现优先级队列
    - 全异步事件处理，不阻塞发布者
    - Worker池并发处理事件
    - 错误隔离：单个handler失败不影响其他

    缺点：
    - 不持久化，Agent重启后未处理消息丢失
    """

    def __init__(
        self,
        max_queue_size: int = 1000,
        num_workers: int = 4,
        drop_policy: str = "lowest_priority",
    ):
        """
        初始化内存消息后端

        Args:
            max_queue_size: 队列最大长度
            num_workers: Worker线程数量
            drop_policy: 队列满时的丢弃策略（oldest/lowest_priority/reject）
        """
        self.max_queue_size = max_queue_size
        self.num_workers = num_workers
        self.drop_policy = drop_policy

        # 优先级队列（使用heapq）
        # 元素格式：(-priority, timestamp, event)
        # 注意：priority越小越优先，所以用负号
        self._queue: List[tuple] = []
        self._queue_lock = asyncio.Lock()

        # 订阅信息
        # {event_type: [{subscription_id, handler, mode, filter_func}]}
        self._subscriptions: Dict[str, List[Dict]] = defaultdict(list)
        self._subscription_index: Dict[str, Dict] = {}  # {subscription_id: subscription_info}

        # Pending计数（用于负载均衡）
        self._handler_pending: Dict[Callable, int] = defaultdict(int)

        # Worker管理
        self._workers: List[asyncio.Task] = []
        self._running = False
        self._counter = 0  # 用于保证队列元素的唯一性

        # 统计信息
        self._stats = {
            "published_count": 0,
            "dropped_count": 0,
            "processed_count": 0,
            "error_count": 0,
        }

    async def publish(self, event: Event) -> bool:
        """
        发布事件到队列

        Args:
            event: 要发布的事件

        Returns:
            bool: 是否成功发布
        """
        async with self._queue_lock:
            # 检查队列是否已满
            if len(self._queue) >= self.max_queue_size:
                # 根据策略处理
                if self.drop_policy == "reject":
                    self._stats["dropped_count"] += 1
                    return False
                elif self.drop_policy == "oldest":
                    # 丢弃最旧的（队列头部）
                    heapq.heappop(self._queue)
                    self._stats["dropped_count"] += 1
                elif self.drop_policy == "lowest_priority":
                    # 比较新事件和队列最低优先级
                    if self._queue:
                        lowest_priority = -self._queue[0][0]
                        if event.level.value > lowest_priority:
                            heapq.heappop(self._queue)
                            self._stats["dropped_count"] += 1
                        else:
                            # 新事件优先级更低，拒绝
                            self._stats["dropped_count"] += 1
                            return False

            # 添加到优先级队列
            # (-priority, counter, event) - counter保证FIFO
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
        filter_func: Optional[Callable[[Event], bool]] = None,
    ) -> str:
        """
        订阅事件

        Args:
            event_type: 事件类型
            handler: 处理函数
            propagation_mode: 传播模式（broadcast/competing）
            filter_func: 过滤函数

        Returns:
            str: 订阅ID
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
        取消订阅

        Args:
            subscription_id: 订阅ID

        Returns:
            bool: 是否成功取消
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
        """启动消息总线（启动worker池）"""
        if self._running:
            return

        self._running = True
        self._workers = [
            asyncio.create_task(self._worker(i)) for i in range(self.num_workers)
        ]

    async def stop(self):
        """停止消息总线（优雅关闭）"""
        if not self._running:
            return

        self._running = False

        # 等待队列处理完成或超时
        timeout = 30  # 秒
        start_time = time.time()

        while self._queue and (time.time() - start_time) < timeout:
            await asyncio.sleep(0.1)

        # 取消所有worker
        for worker in self._workers:
            worker.cancel()

        # 等待worker结束
        await asyncio.gather(*self._workers, return_exceptions=True)

    async def _worker(self, worker_id: int):
        """
        Worker线程：从队列中取事件并处理

        Args:
            worker_id: Worker ID
        """
        while self._running:
            try:
                # 从队列中获取事件
                event = await self._get_next_event()

                if event is None:
                    await asyncio.sleep(0.1)
                    continue

                # 处理事件
                await self._process_event(event)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._stats["error_count"] += 1

    async def _get_next_event(self) -> Optional[Event]:
        """从队列中获取下一个事件"""
        async with self._queue_lock:
            if not self._queue:
                return None

            _, _, event = heapq.heappop(self._queue)
            return event

    async def _process_event(self, event: Event):
        """
        处理事件（分发到订阅者）

        Args:
            event: 要处理的事件
        """
        subscriptions = self._subscriptions.get(event.type, [])

        if not subscriptions:
            return

        # 根据传播模式处理
        broadcast_subscriptions = [s for s in subscriptions if s["mode"] == "broadcast"]
        competing_subscriptions = [s for s in subscriptions if s["mode"] == "competing"]

        # 广播模式：所有订阅者都收到
        for subscription in broadcast_subscriptions:
            await self._handle_event(subscription, event)

        # 竞争模式：只有一个订阅者收到（负载最低的）
        if competing_subscriptions:
            # 选择pending数量最少的handler
            subscription = min(
                competing_subscriptions, key=lambda s: self._handler_pending[s["handler"]]
            )
            await self._handle_event(subscription, event)

    async def _handle_event(self, subscription: Dict, event: Event):
        """
        调用单个handler处理事件

        Args:
            subscription: 订阅信息
            event: 事件
        """
        # 检查过滤函数
        if subscription["filter_func"]:
            try:
                if not subscription["filter_func"](event):
                    return
            except Exception:
                # 过滤函数出错，默认不过滤
                pass

        handler = subscription["handler"]

        # 增加pending计数
        self._handler_pending[handler] += 1

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
            self._handler_pending[handler] -= 1

    async def get_stats(self) -> dict:
        """
        获取统计信息

        Returns:
            dict: 统计信息
        """
        return {
            **self._stats,
            "queue_size": len(self._queue),
            "max_queue_size": self.max_queue_size,
            "subscription_count": len(self._subscription_index),
            "worker_count": self.num_workers,
            "running": self._running,
        }
