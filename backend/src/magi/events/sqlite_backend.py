"""
message bus - SQLite backend implementation
Persistent queue based on aiosqlite
"""
import asyncio
import aiosqlite
import json
import time
import logging
from dataclasses import asdict, dataclass
from typing import Callable, Dict, List, Optional
from collections import defaultdict
from .backend import MessageBusBackend
from .events import Event, REQUIRE_SUBSCRIBER_DELIVERY_METADATA_KEY

logger = logging.getLogger(__name__)

# Message status constants
STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

PROCESS_OUTCOME_COMPLETED = "completed"
PROCESS_OUTCOME_FAILED = "failed"
PROCESS_OUTCOME_REQUEUE = "requeue"


@dataclass
class SQLiteBackendStats:
    published_count: int = 0
    dropped_count: int = 0
    processed_count: int = 0
    error_count: int = 0
    handler_error_count: int = 0
    handler_timeout_count: int = 0
    retry_count: int = 0
    dead_letter_count: int = 0
    broadcast_parallelism: int = 0


class SQLiteMessageBackend(MessageBusBackend):
    """
    SQLite-based persistent message queue backend

    Features:
    - Uses SQLite to persist events
    - Can restore unprocessed events after agent restart
    - Supports priority queue (ORDER BY priority DESC, created_at ASC)
    - Worker pool for concurrent event processing
    - Message retry mechanism
    """

    def __init__(
        self,
        db_path: str = "~/.magi/data/message_queue.db",
        max_queue_size: int = 1000,
        num_workers: int = 4,
        memory_cache_size: int = 100,
        broadcast_max_concurrency: int = 8,
        handler_timeout_seconds: float = 2.0,
        max_retries: int = 3,
        retry_delay_seconds: float = 1.0,
    ):
        """
        initialize SQLite message backend

        Args:
            db_path: database file path
            max_queue_size: maximum queue length
            num_workers: number of worker threads
            memory_cache_size: memory cache size (reduce database queries)
            broadcast_max_concurrency: max concurrent broadcast handlers
            handler_timeout_seconds: timeout for each handler execution
            max_retries: max retry attempts for failed messages
            retry_delay_seconds: delay before retrying failed messages
        """
        self.db_path = db_path
        self.max_queue_size = max_queue_size
        self.num_workers = num_workers
        self.memory_cache_size = memory_cache_size
        self.broadcast_max_concurrency = broadcast_max_concurrency
        self.handler_timeout_seconds = handler_timeout_seconds
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds

        # Subscription info
        self._subscriptions: Dict[str, List[Dict]] = defaultdict(list)
        self._subscription_index: Dict[str, Dict] = {}

        # pending count
        self._handler_pending: Dict[Callable, int] = defaultdict(int)

        # worker management
        self._workers: List[asyncio.Task] = []
        self._running = False

        # semaphore for broadcast concurrency
        self._broadcast_semaphore: Optional[asyncio.Semaphore] = None

        # Statistics
        self._stats = SQLiteBackendStats(broadcast_parallelism=broadcast_max_concurrency)

    @property
    def _expanded_db_path(self) -> str:
        """get expanded database path (process ~)"""
        from pathlib import Path
        return str(Path(self.db_path).expanduser())

    async def _init_db(self):
        """Initialize database tables"""
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
                # check if has required columns
                cursor = await db.execute("PRAGMA table_info(message_queue)")
                columns = await cursor.fetchall()
                column_names = [col[1] for col in columns]

                # Check for new schema with status and retry_count
                has_status = "status" in column_names
                has_retry_count = "retry_count" in column_names

                if not has_status or not has_retry_count:
                    # Migrate old schema to new schema
                    logger.info("Migrating message_queue table to new schema with retry support...")

                    # Create new table with proper schema
                    await db.execute("DROP TABLE IF EXISTS message_queue_new")
                    await db.execute("""
                        CREATE TABLE message_queue_new (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            event_type TEXT NOT NULL,
                            event_data TEXT NOT NULL,
                            priority INTEGER NOT NULL,
                            source TEXT NOT NULL,
                            correlation_id TEXT NOT NULL,
                            metadata TEXT,
                            created_at REAL NOT NULL,
                            status TEXT DEFAULT 'pending',
                            retry_count INTEGER DEFAULT 0,
                            last_error TEXT
                        )
                    """)

                    # Migrate data: processed=true -> status='completed', processed=false -> status='pending'
                    if "processed" in column_names:
                        await db.execute("""
                            INSERT INTO message_queue_new
                            (id, event_type, event_data, priority, source, correlation_id, metadata, created_at, status, retry_count)
                            SELECT id, event_type, event_data, priority, source, correlation_id, metadata, created_at,
                                   CASE WHEN processed = 1 THEN 'completed' ELSE 'pending' END,
                                   0
                            FROM message_queue
                        """)
                    else:
                        await db.execute("""
                            INSERT INTO message_queue_new
                            (id, event_type, event_data, priority, source, correlation_id, metadata, created_at, status, retry_count)
                            SELECT id, event_type, event_data, priority, source, correlation_id, metadata, created_at, 'pending', 0
                            FROM message_queue
                        """)

                    # Drop old table and rename new table
                    await db.execute("DROP TABLE message_queue")
                    await db.execute("ALTER TABLE message_queue_new RENAME TO message_queue")

                    # Drop old index if exists
                    await db.execute("DROP INDEX IF EXISTS idx_message_queue_processed_priority")

                    logger.info("Migration completed successfully")

            # Create table if not exists
            await db.execute("""
                CREATE TABLE IF NOT EXISTS message_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    event_data TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    metadata TEXT,
                    created_at REAL NOT NULL,
                    status TEXT DEFAULT 'pending',
                    retry_count INTEGER DEFAULT 0,
                    last_error TEXT
                )
            """)

            # Create indexes for efficient querying
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_message_queue_status_priority
                ON message_queue(status, priority DESC, created_at ASC)
            """)

            await db.commit()

    async def publish(self, event: Event) -> bool:
        """
        publish event to SQLite database

        Args:
            event: Event to publish

        Returns:
            bool: Whether publish was successful
        """
        try:
            async with aiosqlite.connect(self._expanded_db_path) as db:
                # checkqueuelength (only count pending messages)
                cursor = await db.execute(
                    "SELECT COUNT(*) FROM message_queue WHERE status = ?",
                    (STATUS_PENDING,),
                )
                count = (await cursor.fetchone())[0]

                if count >= self.max_queue_size:
                    # queue is full, discard oldest pending message
                    await db.execute("""
                        DELETE FROM message_queue
                        WHERE id IN (
                            SELECT id FROM message_queue
                            WHERE status = ?
                            ORDER BY created_at ASC
                            LIMIT 1
                        )
                    """, (STATUS_PENDING,))
                    self._stats.dropped_count += 1

                # Insert new event
                await db.execute("""
                    INSERT INTO message_queue (
                        event_type, event_data, priority, source,
                        correlation_id, metadata, created_at, status, retry_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                """, (
                    event.type,
                    json.dumps(event.to_dict()),
                    event.level.value,
                    event.source,
                    event.correlation_id,
                    json.dumps(event.metadata),
                    event.timestamp,
                    STATUS_PENDING,
                ))

                await db.commit()
                self._stats.published_count += 1
                return True

        except Exception as e:
            logger.error(f"Failed to publish event: {e}")
            self._stats.error_count += 1
            return False

    async def subscribe(
        self,
        event_type: str,
        handler: Callable,
        propagation_mode: str = "broadcast",
        filter_func: Optional[Callable[[Event], bool]] = None,
    ) -> str:
        """Subscribe to event"""
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
        """Unsubscribe"""
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

        # Initialize database
        await self._init_db()

        self._running = True
        self._broadcast_semaphore = asyncio.Semaphore(self.broadcast_max_concurrency)
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
                    "SELECT COUNT(*) FROM message_queue WHERE status = ?",
                    (STATUS_PENDING,),
                )
                count = (await cursor.fetchone())[0]

                if count == 0:
                    break

            await asyncio.sleep(0.1)

        # Cancel workers
        for worker in self._workers:
            worker.cancel()

        await asyncio.gather(*self._workers, return_exceptions=True)

    async def _worker(self, worker_id: int):
        """worker thread"""
        while self._running:
            try:
                # atomically get and mark unprocessed event from database
                result = await self._get_next_event()

                if result is None:
                    await asyncio.sleep(0.1)
                    continue

                event_id, event = result

                # Process event
                outcome = await self._process_event(event)

                # Update message status based on result
                if outcome == PROCESS_OUTCOME_COMPLETED:
                    await self._mark_completed(event_id)
                elif outcome == PROCESS_OUTCOME_REQUEUE:
                    await self._requeue_for_other_subscribers(event_id)
                    if self.retry_delay_seconds > 0:
                        await asyncio.sleep(self.retry_delay_seconds)
                else:
                    await self._mark_failed(event_id, "Handler failed")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}")
                self._stats.error_count += 1

    async def _get_next_event(self) -> Optional[tuple]:
        """
        Get next pending event and mark as processing.

        Returns:
            Tuple of (event_id, event) or None if no pending events
        """
        async with aiosqlite.connect(self._expanded_db_path) as db:
            # Atomic operation: SELECT + update in same transaction
            cursor = await db.execute("""
                UPDATE message_queue SET status = ?
                WHERE id = (
                    SELECT id FROM message_queue
                    WHERE status = ?
                    ORDER BY priority DESC, created_at ASC
                    LIMIT 1
                )
                RETURNING id, event_data
            """, (STATUS_PROCESSING, STATUS_PENDING))
            row = await cursor.fetchone()
            await db.commit()

            if not row:
                return None

            event_id = row[0]
            event_data = json.loads(row[1])
            return (event_id, Event.from_dict(event_data))

    async def _mark_completed(self, event_id: int) -> None:
        """Mark message as successfully completed."""
        async with aiosqlite.connect(self._expanded_db_path) as db:
            await db.execute(
                "UPDATE message_queue SET status = ? WHERE id = ?",
                (STATUS_COMPLETED, event_id),
            )
            self._stats.processed_count += 1
            await db.commit()

    async def _mark_failed(self, event_id: int, error_message: str) -> None:
        """
        Mark message as failed, with retry logic.

        If retry_count < max_retries, reset to pending for retry.
        Otherwise, mark as failed (dead letter).
        """
        async with aiosqlite.connect(self._expanded_db_path) as db:
            # Get current retry count
            cursor = await db.execute(
                "SELECT retry_count FROM message_queue WHERE id = ?",
                (event_id,),
            )
            row = await cursor.fetchone()
            if not row:
                return

            retry_count = row[0] + 1

            if retry_count < self.max_retries:
                # Reset to pending for retry
                await db.execute(
                    "UPDATE message_queue SET status = ?, retry_count = ?, last_error = ? WHERE id = ?",
                    (STATUS_PENDING, retry_count, error_message, event_id),
                )
                self._stats.retry_count += 1
                logger.info(f"Message {event_id} scheduled for retry ({retry_count}/{self.max_retries})")
            else:
                # Max retries exceeded, mark as failed
                await db.execute(
                    "UPDATE message_queue SET status = ?, retry_count = ?, last_error = ? WHERE id = ?",
                    (STATUS_FAILED, retry_count, error_message, event_id),
                )
                self._stats.dead_letter_count += 1
                logger.warning(f"Message {event_id} moved to dead letter after {retry_count} retries")

            await db.commit()

    async def _requeue_for_other_subscribers(self, event_id: int) -> None:
        """Release a critical event back to pending when this instance has no local subscribers."""
        async with aiosqlite.connect(self._expanded_db_path) as db:
            await db.execute(
                "UPDATE message_queue SET status = ?, last_error = NULL WHERE id = ?",
                (STATUS_PENDING, event_id),
            )
            await db.commit()

    async def _process_event(self, event: Event) -> str:
        """
        Process event with parallel broadcast dispatch.

        Returns:
            Processing outcome for the current worker instance.
        """
        subscriptions = self._subscriptions.get(event.type, [])

        if not subscriptions:
            if self._requires_subscriber_delivery(event):
                logger.warning(
                    "Requeueing critical event because this backend has no local subscribers",
                    extra={
                        "event_type": event.type,
                        "event_source": event.source,
                        "correlation_id": event.correlation_id,
                    },
                )
                return PROCESS_OUTCOME_REQUEUE
            return PROCESS_OUTCOME_COMPLETED

        broadcast_subscriptions = [s for s in subscriptions if s["mode"] == "broadcast"]
        competing_subscriptions = [s for s in subscriptions if s["mode"] == "competing"]

        all_success = True

        # broadcast pattern - parallel execution with semaphore
        if broadcast_subscriptions:
            tasks = [
                asyncio.create_task(self._handle_event_with_timeout(sub, event))
                for sub in broadcast_subscriptions
            ]
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                # Check if any handler failed
                for result in results:
                    if isinstance(result, Exception):
                        all_success = False
                    elif result is False:
                        all_success = False

        # competing pattern
        if competing_subscriptions:
            subscription = min(
                competing_subscriptions, key=lambda s: self._handler_pending[s["handler"]]
            )
            result = await self._handle_event_with_timeout(subscription, event)
            if result is False:
                all_success = False

        return PROCESS_OUTCOME_COMPLETED if all_success else PROCESS_OUTCOME_FAILED

    def _requires_subscriber_delivery(self, event: Event) -> bool:
        metadata = event.metadata if isinstance(event.metadata, dict) else {}
        return bool(metadata.get(REQUIRE_SUBSCRIBER_DELIVERY_METADATA_KEY))

    async def _handle_event_with_timeout(self, subscription: Dict, event: Event) -> bool:
        """
        Handle event with semaphore control and timeout for broadcast isolation.

        Returns:
            True if handler succeeded, False otherwise
        """
        async def _run_handler():
            async with self._broadcast_semaphore:
                return await self._handle_event(subscription, event)

        try:
            result = await asyncio.wait_for(_run_handler(), timeout=self.handler_timeout_seconds)
            return result if result is not None else True
        except asyncio.TimeoutError:
            self._stats.handler_timeout_count += 1
            logger.warning(f"Handler timeout for event {event.type}")
            return False
        except Exception as e:
            self._stats.handler_error_count += 1
            logger.error(f"Handler error for event {event.type}: {e}")
            return False

    async def _handle_event(self, subscription: Dict, event: Event) -> bool:
        """
        Call handler to process event.

        Returns:
            True if handler succeeded, False otherwise
        """
        if subscription["filter_func"]:
            try:
                if not subscription["filter_func"](event):
                    return True  # Filtered out = success
            except Exception:
                pass

        handler = subscription["handler"]
        self._handler_pending[handler] += 1

        try:
            if asyncio.iscoroutinefunction(handler):
                await handler(event)
            else:
                handler(event)

            return True

        except Exception as e:
            logger.error(f"Handler exception for event {event.type}: {e}")
            return False

        finally:
            self._handler_pending[handler] -= 1

    async def get_stats(self) -> dict:
        """Get statistics"""
        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM message_queue WHERE status = ?",
                (STATUS_PENDING,),
            )
            queue_size = (await cursor.fetchone())[0]

            cursor = await db.execute(
                "SELECT COUNT(*) FROM message_queue WHERE status = ?",
                (STATUS_PROCESSING,),
            )
            processing_size = (await cursor.fetchone())[0]

            cursor = await db.execute(
                "SELECT COUNT(*) FROM message_queue WHERE status = ?",
                (STATUS_FAILED,),
            )
            failed_size = (await cursor.fetchone())[0]

        return {
            **asdict(self._stats),
            "queue_size": queue_size,
            "processing_size": processing_size,
            "failed_size": failed_size,
            "max_queue_size": self.max_queue_size,
            "subscription_count": len(self._subscription_index),
            "worker_count": self.num_workers,
            "running": self._running,
            "broadcast_max_concurrency": self.broadcast_max_concurrency,
            "handler_timeout_seconds": self.handler_timeout_seconds,
            "max_retries": self.max_retries,
        }

    # =========================================================================
    # Maintenance methods (called by MaintenanceDaemon)
    # =========================================================================

    async def cleanup_old_messages(
        self,
        retain_hours: int = 24,
        batch_size: int = 1000,
    ) -> int:
        """
        Clean up old completed/failed messages.

        Args:
            retain_hours: Retain messages from last N hours
            batch_size: Maximum number of messages to delete in one batch

        Returns:
            Number of messages deleted
        """
        cutoff_time = time.time() - (retain_hours * 3600)
        deleted_count = 0

        async with aiosqlite.connect(self._expanded_db_path) as db:
            # Delete completed messages older than cutoff
            # SQLite doesn't support LIMIT in DELETE directly, use subquery
            cursor = await db.execute("""
                DELETE FROM message_queue
                WHERE rowid IN (
                    SELECT rowid FROM message_queue
                    WHERE status IN (?, ?) AND created_at < ?
                    LIMIT ?
                )
            """, (STATUS_COMPLETED, STATUS_FAILED, cutoff_time, batch_size))
            deleted_count = cursor.rowcount
            await db.commit()

        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old messages (retention: {retain_hours}h)")

        return deleted_count

    async def reset_stale_processing_messages(self, timeout_seconds: float = 300) -> int:
        """
        Reset messages stuck in 'processing' state back to 'pending'.

        This handles cases where a worker crashed while processing a message.

        Args:
            timeout_seconds: Messages in processing state longer than this are considered stale

        Returns:
            Number of messages reset
        """
        # We don't have a 'updated_at' field, so we use created_at as approximation
        # This is a best-effort recovery mechanism
        cutoff_time = time.time() - timeout_seconds

        async with aiosqlite.connect(self._expanded_db_path) as db:
            cursor = await db.execute("""
                UPDATE message_queue SET status = ?
                WHERE status = ? AND created_at < ?
            """, (STATUS_PENDING, STATUS_PROCESSING, cutoff_time))
            reset_count = cursor.rowcount
            await db.commit()

        if reset_count > 0:
            logger.warning(f"Reset {reset_count} stale processing messages to pending")

        return reset_count

    async def get_queue_health(self) -> dict:
        """Get queue health statistics."""
        async with aiosqlite.connect(self._expanded_db_path) as db:
            stats = {}

            for status in [STATUS_PENDING, STATUS_PROCESSING, STATUS_COMPLETED, STATUS_FAILED]:
                cursor = await db.execute(
                    "SELECT COUNT(*) FROM message_queue WHERE status = ?",
                    (status,),
                )
                stats[status] = (await cursor.fetchone())[0]

            # Get oldest pending message age
            cursor = await db.execute(
                "SELECT MIN(created_at) FROM message_queue WHERE status = ?",
                (STATUS_PENDING,),
            )
            oldest = await cursor.fetchone()
            if oldest and oldest[0]:
                stats["oldest_pending_age_seconds"] = time.time() - oldest[0]
            else:
                stats["oldest_pending_age_seconds"] = 0

            # Get database size
            cursor = await db.execute("SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()")
            stats["db_size_bytes"] = (await cursor.fetchone())[0]

        return stats
