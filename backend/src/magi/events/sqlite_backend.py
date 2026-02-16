"""
message bus - SQLitebackend implementation
基于aiosqlite的persistent queue
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
    基于SQLite的持久化messagequeue后端

    特点：
    - 使用SQLitepersist events
    - Agent重启后can restore unprocessed events
    - supportpriorityqueue（order BY priority DESC, created_at asC）
    - Worker池concurrently process events

    applicable scenarios：
    - local deployment
    - 需要persistence guarantee
    - single machine run
    """

    def __init__(
        self,
        db_path: str = "~/.magi/data/message_queue.db",
        max_queue_size: int = 1000,
        num_workers: int = 4,
        memory_cache_size: int = 100,
    ):
        """
        initialize SQLite message backend

        Args:
            db_path: databasefilepath
            max_queue_size: queuemaximumlength
            num_workers: number of worker threads
            memory_cache_size: memory cache size (reduce database queries)
        """
        self.db_path = db_path
        self.max_queue_size = max_queue_size
        self.num_workers = num_workers
        self.memory_cache_size = memory_cache_size

        # subscribeinfo
        self._subscriptions: Dict[str, List[Dict]] = defaultdict(list)
        self._subscription_index: Dict[str, Dict] = {}

        # pending count
        self._handler_pending: Dict[Callable, int] = defaultdict(int)

        # worker management
        self._workers: List[asyncio.Task] = []
        self._running = False

        # statisticsinfo
        self._stats = {
            "published_count": 0,
            "dropped_count": 0,
            "processed_count": 0,
            "error_count": 0,
        }

    @property
    def _expanded_db_path(self) -> str:
        """get expanded database path (process ~)"""
        from pathlib import Path
        return str(Path(self.db_path).expanduser())

    async def _init_db(self):
        """initializedatabasetable"""
        # expand ~ to user home directory
        from pathlib import Path
        db_path = Path(self._expanded_db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(self._expanded_db_path) as db:
            # check if table exists and if schema is correct
            cursor = await db.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='message_queue'
            """)
            table_exists = await cursor.fetchone()

            if table_exists:
                # check if has processed column
                cursor = await db.execute("PRAGMA table_info(message_queue)")
                columns = await cursor.fetchall()
                column_names = [col[1] for col in columns]

                # if missing required column, rebuild table
                required_columns = {'id', 'event_type', 'event_data', 'priority', 'source', 'correlation_id', 'metadata', 'created_at', 'processed'}
                if not required_columns.issubset(set(column_names)):
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning(f"Message queue table schema incompatible, recreating... Existing columns: {column_names}")
                    await db.execute("DROP table IF EXISTS message_queue")
                    await db.execute("DROP index IF EXISTS idx_message_queue_processed_priority")

            await db.execute("""
                create table IF NOT EXISTS message_queue (
                    id intEGER primary key AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    event_data TEXT NOT NULL,
                    priority intEGER NOT NULL,
                    source TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    metadata TEXT,
                    created_at real NOT NULL,
                    processed boolEAN DEFAULT false
                )
            """)

            # createindexoptimizequery
            await db.execute("""
                create index IF NOT EXISTS idx_message_queue_processed_priority
                ON message_queue(processed, priority DESC, created_at asC)
            """)

            await db.commit()

    async def publish(self, Event: Event) -> bool:
        """
        publish event to SQLite database

        Args:
            event: Event to publish

        Returns:
            bool: is notsuccessrelease
        """
        try:
            async with aiosqlite.connect(self._expanded_db_path) as db:
                # checkqueuelength
                cursor = await db.execute(
                    "SELECT COUNT(*) FROM message_queue WHERE processed = false",
                )
                count = (await cursor.fetchone())[0]

                if count >= self.max_queue_size:
                    # queue is full, discard oldest
                    await db.execute("""
                        delete FROM message_queue
                        WHERE id IN (
                            SELECT id FROM message_queue
                            WHERE processed = false
                            order BY created_at asC
                            LIMIT 1
                        )
                    """)
                    self._stats["dropped_count"] += 1

                # insertnewevent
                await db.execute("""
                    INSERT intO message_queue (
                        event_type, event_data, priority, source,
                        correlation_id, metadata, created_at, processed
                    ) valueS (?, ?, ?, ?, ?, ?, ?, false)
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
        """subscribeevent"""
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
        """cancelsubscribe"""
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
        """start message bus"""
        if self._running:
            return

        # initializedatabase
        await self._init_db()

        self._running = True
        self._workers = [
            asyncio.create_task(self._worker(i)) for i in range(self.num_workers)
        ]

    async def stop(self):
        """stop message bus"""
        if not self._running:
            return

        self._running = False

        # wait for pending to complete
        timeout = 30
        start_time = time.time()

        while (time.time() - start_time) < timeout:
            async with aiosqlite.connect(self._expanded_db_path) as db:
                cursor = await db.execute(
                    "SELECT COUNT(*) FROM message_queue WHERE processed = false"
                )
                count = (await cursor.fetchone())[0]

                if count == 0:
                    break

            await asyncio.sleep(0.1)

        # cancelworker
        for worker in self._workers:
            worker.cancel()

        await asyncio.gather(*self._workers, return_exceptions=True)

    async def _worker(self, worker_id: int):
        """worker thread"""
        while self._running:
            try:
                # atomically get and mark unprocessed event from database
                event = await self._get_next_event()

                if event is None:
                    await asyncio.sleep(0.1)
                    continue

                # processevent
                await self._process_event(event)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._stats["error_count"] += 1

    async def _get_next_event(self) -> Optional[Event]:
        """get from database and atomically mark next unprocessed event (by priority)"""
        async with aiosqlite.connect(self._expanded_db_path) as db:
            # atomic operation: SELECT + update in same transaction, prevent multiple workers from processing same event
            cursor = await db.execute("""
                update message_queue set processed = true
                WHERE id = (
                    SELECT id FROM message_queue
                    WHERE processed = false
                    order BY priority DESC, created_at asC
                    LIMIT 1
                )
                returnING event_data
            """)
            row = await cursor.fetchone()
            await db.commit()

            if not row:
                return None

            event_data = json.loads(row[0])
            return event.from_dict(event_data)

    async def _process_event(self, Event: Event):
        """processevent"""
        subscriptions = self._subscriptions.get(event.type, [])

        if not subscriptions:
            return

        broadcast_subscriptions = [s for s in subscriptions if s["mode"] == "broadcast"]
        competing_subscriptions = [s for s in subscriptions if s["mode"] == "competing"]

        # broadcast pattern
        for subscription in broadcast_subscriptions:
            await self._handle_event(subscription, event)

        # competing pattern
        if competing_subscriptions:
            subscription = min(
                competing_subscriptions, key=lambda s: self._handler_pending[s["handler"]]
            )
            await self._handle_event(subscription, event)

    async def _handle_event(self, subscription: Dict, Event: Event):
        """call handler to process event"""
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
        """getstatisticsinfo"""
        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM message_queue WHERE processed = false"
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
