"""
消息总线 - SQLite后端实现
基于aiosqlite的持久化队列
"""
import asyncio
import aiosqlite
import json
import time
from typing import Callable, Dict, List, Optional
from collections import defaultdict
from .backend import MessageBusBackend
from .events import Event


class SQLiteMessageBackend(MessageBusBackend):
    """
    基于SQLite的持久化消息队列后端

    特点：
    - 使用SQLite持久化事件
    - Agent重启后可恢复未处理事件
    - 支持优先级队列（ORDER BY priority DESC, created_at ASC）
    - Worker池并发处理事件

    适用场景：
    - 本地部署
    - 需要持久化保证
    - 单机运行
    """

    def __init__(
        self,
        db_path: str = "./data/magi_events.db",
        max_queue_size: int = 1000,
        num_workers: int = 4,
        memory_cache_size: int = 100,
    ):
        """
        初始化SQLite消息后端

        Args:
            db_path: 数据库文件路径
            max_queue_size: 队列最大长度
            num_workers: Worker线程数量
            memory_cache_size: 内存缓存大小（减少数据库查询）
        """
        self.db_path = db_path
        self.max_queue_size = max_queue_size
        self.num_workers = num_workers
        self.memory_cache_size = memory_cache_size

        # 订阅信息
        self._subscriptions: Dict[str, List[Dict]] = defaultdict(list)
        self._subscription_index: Dict[str, Dict] = {}

        # Pending计数
        self._handler_pending: Dict[Callable, int] = defaultdict(int)

        # Worker管理
        self._workers: List[asyncio.Task] = []
        self._running = False

        # 统计信息
        self._stats = {
            "published_count": 0,
            "dropped_count": 0,
            "processed_count": 0,
            "error_count": 0,
        }

    async def _init_db(self):
        """初始化数据库表"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    event_data TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    metadata TEXT,
                    created_at REAL NOT NULL,
                    processed BOOLEAN DEFAULT FALSE
                )
            """)

            # 创建索引优化查询
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_processed_priority
                ON events(processed, priority DESC, created_at ASC)
            """)

            await db.commit()

    async def publish(self, event: Event) -> bool:
        """
        发布事件到SQLite数据库

        Args:
            event: 要发布的事件

        Returns:
            bool: 是否成功发布
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # 检查队列长度
                cursor = await db.execute(
                    "SELECT COUNT(*) FROM events WHERE processed = FALSE",
                )
                count = (await cursor.fetchone())[0]

                if count >= self.max_queue_size:
                    # 队列已满，丢弃最旧的
                    await db.execute("""
                        DELETE FROM events
                        WHERE id IN (
                            SELECT id FROM events
                            WHERE processed = FALSE
                            ORDER BY created_at ASC
                            LIMIT 1
                        )
                    """)
                    self._stats["dropped_count"] += 1

                # 插入新事件
                await db.execute("""
                    INSERT INTO events (
                        event_type, event_data, priority, source,
                        correlation_id, metadata, created_at, processed
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, FALSE)
                """, (
                    event.type,
                    json.dumps(event.to_dict()),
                    event.level.value,
                    event.source,
                    event.correlation_id,
                    json.dumps(event.metadata),
                    event.timestamp,
                ))

                await db.commit()
                self._stats["published_count"] += 1
                return True

        except Exception as e:
            self._stats["error_count"] += 1
            return False

    async def subscribe(
        self,
        event_type: str,
        handler: Callable,
        propagation_mode: str = "broadcast",
        filter_func: Optional[Callable[[Event], bool]] = None,
    ) -> str:
        """订阅事件"""
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
        """取消订阅"""
        if subscription_id not in self._subscription_index:
            return False

        subscription = self._subscription_index[subscription_id]
        event_type = subscription["event_type"]

        self._subscriptions[event_type] = [
            s for s in self._subscriptions[event_type] if s["id"] != subscription_id
        ]

        del self._subscription_index[subscription_id]
        return True

    async def start(self):
        """启动消息总线"""
        if self._running:
            return

        # 初始化数据库
        await self._init_db()

        self._running = True
        self._workers = [
            asyncio.create_task(self._worker(i)) for i in range(self.num_workers)
        ]

    async def stop(self):
        """停止消息总线"""
        if not self._running:
            return

        self._running = False

        # 等待处理完成
        timeout = 30
        start_time = time.time()

        while (time.time() - start_time) < timeout:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    "SELECT COUNT(*) FROM events WHERE processed = FALSE"
                )
                count = (await cursor.fetchone())[0]

                if count == 0:
                    break

            await asyncio.sleep(0.1)

        # 取消worker
        for worker in self._workers:
            worker.cancel()

        await asyncio.gather(*self._workers, return_exceptions=True)

    async def _worker(self, worker_id: int):
        """Worker线程"""
        while self._running:
            try:
                # 从数据库获取未处理事件
                event = await self._get_next_event()

                if event is None:
                    await asyncio.sleep(0.1)
                    continue

                # 处理事件
                await self._process_event(event)

                # 标记为已处理
                await self._mark_event_processed(event.correlation_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._stats["error_count"] += 1

    async def _get_next_event(self) -> Optional[Event]:
        """从数据库获取下一个未处理事件（按优先级）"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                SELECT event_data FROM events
                WHERE processed = FALSE
                ORDER BY priority DESC, created_at ASC
                LIMIT 1
            """)
            row = await cursor.fetchone()

            if not row:
                return None

            event_data = json.loads(row[0])
            return Event.from_dict(event_data)

    async def _mark_event_processed(self, correlation_id: str):
        """标记事件为已处理"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE events SET processed = TRUE WHERE correlation_id = ?",
                (correlation_id,)
            )
            await db.commit()

    async def _process_event(self, event: Event):
        """处理事件"""
        subscriptions = self._subscriptions.get(event.type, [])

        if not subscriptions:
            return

        broadcast_subscriptions = [s for s in subscriptions if s["mode"] == "broadcast"]
        competing_subscriptions = [s for s in subscriptions if s["mode"] == "competing"]

        # 广播模式
        for subscription in broadcast_subscriptions:
            await self._handle_event(subscription, event)

        # 竞争模式
        if competing_subscriptions:
            subscription = min(
                competing_subscriptions, key=lambda s: self._handler_pending[s["handler"]]
            )
            await self._handle_event(subscription, event)

    async def _handle_event(self, subscription: Dict, event: Event):
        """调用handler处理事件"""
        if subscription["filter_func"]:
            try:
                if not subscription["filter_func"](event):
                    return
            except Exception:
                pass

        handler = subscription["handler"]
        self._handler_pending[handler] += 1

        try:
            if asyncio.iscoroutinefunction(handler):
                await handler(event)
            else:
                handler(event)

            self._stats["processed_count"] += 1

        except Exception:
            self._stats["error_count"] += 1

        finally:
            self._handler_pending[handler] -= 1

    async def get_stats(self) -> dict:
        """获取统计信息"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM events WHERE processed = FALSE"
            )
            queue_size = (await cursor.fetchone())[0]

        return {
            **self._stats,
            "queue_size": queue_size,
            "max_queue_size": self.max_queue_size,
            "subscription_count": len(self._subscription_index),
            "worker_count": self.num_workers,
            "running": self._running,
        }
