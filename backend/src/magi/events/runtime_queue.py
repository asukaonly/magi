"""SQLite-backed runtime command queue."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Iterable

from ..core.operation_barrier import AsyncOperationBarrier
from ..core.sqlite import sqlite_connection_async
from .contracts import (
    RefreshChannelsCommand,
    RefreshLLMConfigCommand,
    SensorStateFlushCommand,
    RuntimeCommandType,
    RuntimeQueuedCommand,
    SensorSyncCommand,
    UserMessageCommand,
)

STATUS_PENDING = "pending"
STATUS_CLAIMED = "claimed"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

_USER_MESSAGE_CLEAR_STATE_ID = 1
DEFAULT_CLAIM_LEASE_SECONDS = 60.0


class SQLiteRuntimeCommandQueue:
    """Persisted queue shared by API ingress and the lifecycle-owned runtime worker."""

    def __init__(
        self,
        *,
        db_path: str = "~/.magi/runtime/message_queue.db",
        poll_interval_seconds: float = 0.1,
        claim_lease_seconds: float = DEFAULT_CLAIM_LEASE_SECONDS,
    ) -> None:
        self.db_path = str(Path(db_path).expanduser())
        self.poll_interval_seconds = poll_interval_seconds
        self.claim_lease_seconds = max(0.001, float(claim_lease_seconds))
        self._started = False
        # Serialize this instance's writes. Producer (enqueue) and consumer
        # (claim_next, run at a tight poll interval) share one instance in-process,
        # so without this they issue concurrent write transactions to the same
        # SQLite file. WAL + busy_timeout cover cross-process access, but in-process
        # concurrent writers can still intermittently raise "database is locked"
        # under load (CI). An asyncio.Lock makes in-process writes strictly serial.
        self._write_lock = asyncio.Lock()
        self._user_message_barrier = AsyncOperationBarrier()
        self._user_message_generation: int | None = None
        self._user_message_generation_load_lock = asyncio.Lock()
        self._user_message_clear_owner: asyncio.Task[object] | None = None

    async def start(self) -> None:
        if self._started:
            return
        await self._initialize()
        await self._recover_claimed_commands_after_restart()
        await self._ensure_user_message_generation_loaded()
        self._started = True

    async def stop(self) -> None:
        self._started = False

    async def enqueue_user_message(self, command: UserMessageCommand) -> int:
        async with self.user_message_operation():
            await self._ensure_user_message_generation_loaded()
            return await self._enqueue_command(
                command_type=RuntimeCommandType.USER_MESSAGE,
                payload=command.to_payload(),
                correlation_id=command.correlation_id,
                created_at=command.created_at,
                user_message_generation=self.current_user_message_generation(),
            )

    async def enqueue_refresh_llm_config(self, command: RefreshLLMConfigCommand) -> int:
        return await self._enqueue_command(
            command_type=RuntimeCommandType.REFRESH_LLM_CONFIG,
            payload=command.to_payload(),
            correlation_id=command.correlation_id,
            created_at=command.created_at,
        )

    async def enqueue_refresh_channels(self, command: RefreshChannelsCommand) -> int:
        return await self._enqueue_command(
            command_type=RuntimeCommandType.REFRESH_CHANNELS,
            payload=command.to_payload(),
            correlation_id=command.correlation_id,
            created_at=command.created_at,
        )

    async def enqueue_sensor_sync(self, command: SensorSyncCommand) -> int:
        return await self._enqueue_command(
            command_type=RuntimeCommandType.SENSOR_SYNC,
            payload=command.to_payload(),
            correlation_id=command.correlation_id,
            created_at=command.created_at,
        )

    async def enqueue_sensor_state_flush(self, command: SensorStateFlushCommand) -> int:
        return await self._enqueue_command(
            command_type=RuntimeCommandType.SENSOR_STATE_FLUSH,
            payload=command.to_payload(),
            correlation_id=command.correlation_id,
            created_at=command.created_at,
        )

    async def _enqueue_command(
        self,
        *,
        command_type: RuntimeCommandType,
        payload: dict[str, object],
        correlation_id: str,
        created_at: float,
        user_message_generation: int = 0,
    ) -> int:
        await self._initialize()
        payload_json = json.dumps(payload, ensure_ascii=False)
        async with self._write_lock, sqlite_connection_async(self.db_path) as db:
            if command_type is RuntimeCommandType.USER_MESSAGE:
                return await self._enqueue_user_message_once(
                    db,
                    payload=payload,
                    payload_json=payload_json,
                    correlation_id=correlation_id,
                    created_at=created_at,
                    user_message_generation=user_message_generation,
                )
            cursor = await db.execute(
                """
                INSERT INTO runtime_commands (
                    command_type,
                    payload_json,
                    correlation_id,
                    status,
                    retry_count,
                    user_message_generation,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    command_type.value,
                    payload_json,
                    correlation_id,
                    STATUS_PENDING,
                    int(user_message_generation),
                    float(created_at),
                    float(created_at),
                ),
            )
            command_id = int(cursor.lastrowid or 0)
            await db.commit()
            return command_id

    async def _enqueue_user_message_once(
        self,
        db,
        *,
        payload: dict[str, object],
        payload_json: str,
        correlation_id: str,
        created_at: float,
        user_message_generation: int,
    ) -> int:
        payload_fingerprint = _payload_fingerprint(payload)
        await db.execute("BEGIN IMMEDIATE")
        try:
            cursor = await db.execute(
                """
                SELECT receipt.payload_fingerprint,
                       receipt.first_command_id,
                       receipt.delivery_status,
                       command.status
                FROM runtime_user_message_idempotency AS receipt
                LEFT JOIN runtime_commands AS command
                  ON command.command_id = receipt.first_command_id
                WHERE receipt.correlation_id = ?
                """,
                (correlation_id,),
            )
            existing = await cursor.fetchone()
            if existing is not None:
                if str(existing[0]) != payload_fingerprint:
                    raise ValueError("User-message correlation id was reused for different input")
                receipt_status = str(existing[2] or "open")
                command_status = str(existing[3] or "")
                if receipt_status == "completed" or command_status == STATUS_COMPLETED:
                    if receipt_status != "completed":
                        await db.execute(
                            """
                            UPDATE runtime_user_message_idempotency
                            SET delivery_status = 'completed'
                            WHERE correlation_id = ?
                            """,
                            (correlation_id,),
                        )
                    await db.commit()
                    return int(existing[1])
                if receipt_status not in {"failed"} and command_status in {
                    STATUS_PENDING,
                    STATUS_CLAIMED,
                }:
                    await db.commit()
                    return int(existing[1])

                command_id = await self._insert_user_message_command_row(
                    db,
                    payload_json=payload_json,
                    correlation_id=correlation_id,
                    created_at=created_at,
                    user_message_generation=user_message_generation,
                )
                await db.execute(
                    """
                    UPDATE runtime_user_message_idempotency
                    SET first_command_id = ?,
                        delivery_status = 'open',
                        created_at = ?
                    WHERE correlation_id = ?
                    """,
                    (command_id, float(created_at), correlation_id),
                )
                await db.commit()
                return command_id

            command_id = await self._insert_user_message_command_row(
                db,
                payload_json=payload_json,
                correlation_id=correlation_id,
                created_at=created_at,
                user_message_generation=user_message_generation,
            )
            await db.execute(
                """
                INSERT INTO runtime_user_message_idempotency (
                    correlation_id,
                    payload_fingerprint,
                    first_command_id,
                    delivery_status,
                    created_at
                ) VALUES (?, ?, ?, 'open', ?)
                """,
                (
                    correlation_id,
                    payload_fingerprint,
                    command_id,
                    float(created_at),
                ),
            )
            await db.commit()
            return command_id
        except BaseException:
            await db.rollback()
            raise

    @staticmethod
    async def _insert_user_message_command_row(
        db,
        *,
        payload_json: str,
        correlation_id: str,
        created_at: float,
        user_message_generation: int,
    ) -> int:
        cursor = await db.execute(
            """
            INSERT INTO runtime_commands (
                command_type,
                payload_json,
                correlation_id,
                status,
                retry_count,
                user_message_generation,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, 0, ?, ?, ?)
            """,
            (
                RuntimeCommandType.USER_MESSAGE.value,
                payload_json,
                correlation_id,
                STATUS_PENDING,
                int(user_message_generation),
                float(created_at),
                float(created_at),
            ),
        )
        return int(cursor.lastrowid or 0)

    async def claim_next(
        self,
        *,
        consumer_name: str,
        command_types: Iterable[RuntimeCommandType],
    ) -> RuntimeQueuedCommand | None:
        await self._initialize()
        allowed_types = tuple(command_type.value for command_type in command_types)
        if not allowed_types:
            return None

        placeholders = ", ".join("?" for _ in allowed_types)
        now = time.time()
        async with self._write_lock, sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                await db.execute(
                    """
                    UPDATE runtime_commands
                    SET status = ?,
                        retry_count = retry_count + 1,
                        claimed_by = NULL,
                        claimed_at = NULL,
                        last_error = 'CLAIM_LEASE_EXPIRED',
                        updated_at = ?
                    WHERE status = ?
                      AND (claimed_at IS NULL OR claimed_at < ?)
                    """,
                    (
                        STATUS_PENDING,
                        now,
                        STATUS_CLAIMED,
                        now - self.claim_lease_seconds,
                    ),
                )
                cursor = await db.execute(
                    f"""
                    UPDATE runtime_commands
                    SET status = ?, claimed_by = ?, claimed_at = ?, updated_at = ?
                    WHERE command_id = (
                        SELECT command_id
                        FROM runtime_commands
                        WHERE status = ?
                          AND command_type IN ({placeholders})
                        ORDER BY created_at ASC
                        LIMIT 1
                    )
                    RETURNING command_id, command_type, payload_json, correlation_id,
                              retry_count, user_message_generation
                    """,
                    (
                        STATUS_CLAIMED,
                        consumer_name,
                        now,
                        now,
                        STATUS_PENDING,
                        *allowed_types,
                    ),
                )
                row = await cursor.fetchone()
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

        if row is None:
            return None

        payload = json.loads(str(row[2]))
        if not isinstance(payload, dict):
            payload = {}
        return RuntimeQueuedCommand(
            command_id=int(row[0]),
            command_type=RuntimeCommandType(str(row[1])),
            payload=payload,
            correlation_id=str(row[3]),
            retry_count=int(row[4] or 0),
            user_message_generation=int(row[5] or 0),
        )

    @asynccontextmanager
    async def user_message_operation(self) -> AsyncIterator[None]:
        """Protect one end-to-end user-message ingress or dispatch operation."""
        async with self._user_message_barrier.operation():
            yield

    @asynccontextmanager
    async def user_message_clear_boundary(self) -> AsyncIterator[None]:
        """Block new user-message work while a destructive clear is in progress."""
        async with self._user_message_barrier.exclusive():
            task = asyncio.current_task()
            if task is None:
                raise RuntimeError("User-message clear boundary requires an asyncio task")
            self._user_message_clear_owner = task
            try:
                yield
            finally:
                self._user_message_clear_owner = None

    def current_user_message_generation(self) -> int:
        """Return the durable generation loaded for this queue instance."""
        if self._user_message_generation is None:
            raise RuntimeError("Runtime user-message generation is not initialized")
        return int(self._user_message_generation)

    async def advance_user_message_generation_and_purge(self) -> tuple[int, int]:
        """Advance the clear generation and remove every older user-message payload."""
        task = asyncio.current_task()
        if task is None or task is not self._user_message_clear_owner:
            raise RuntimeError("User-message generation can only advance inside its clear boundary")
        await self._ensure_user_message_generation_loaded()
        now = time.time()
        async with self._write_lock, sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                await db.execute(
                    """
                    UPDATE runtime_user_message_clear_state
                    SET generation = generation + 1, updated_at = ?
                    WHERE singleton_id = ?
                    """,
                    (now, _USER_MESSAGE_CLEAR_STATE_ID),
                )
                async with db.execute(
                    """
                    SELECT generation
                    FROM runtime_user_message_clear_state
                    WHERE singleton_id = ?
                    """,
                    (_USER_MESSAGE_CLEAR_STATE_ID,),
                ) as cursor:
                    row = await cursor.fetchone()
                if row is None:
                    raise RuntimeError("Runtime user-message clear state is missing")
                next_generation = int(row[0])
                cursor = await db.execute(
                    """
                    DELETE FROM runtime_commands
                    WHERE command_type = ?
                    """,
                    (RuntimeCommandType.USER_MESSAGE.value,),
                )
                purged_count = int(cursor.rowcount or 0)
                await db.execute("DELETE FROM runtime_user_message_idempotency")
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        self._user_message_generation = next_generation
        return next_generation, purged_count

    async def ack(self, command_id: int) -> None:
        await self._update_status(command_id=command_id, status=STATUS_COMPLETED, clear_claim=True)

    async def requeue(self, command_id: int, *, error_text: str | None = None) -> None:
        await self._initialize()
        async with self._write_lock, sqlite_connection_async(self.db_path) as db:
            await db.execute(
                """
                UPDATE runtime_commands
                SET status = ?,
                    retry_count = retry_count + 1,
                    last_error = ?,
                    claimed_by = NULL,
                    claimed_at = NULL,
                    updated_at = ?
                WHERE command_id = ?
                """,
                (STATUS_PENDING, error_text, time.time(), command_id),
            )
            await db.execute(
                """
                UPDATE runtime_user_message_idempotency
                SET delivery_status = 'open'
                WHERE first_command_id = ?
                """,
                (command_id,),
            )
            await db.commit()

    async def get_stats(self) -> dict[str, int]:
        await self._initialize()
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT
                    SUM(CASE WHEN status = ? THEN 1 ELSE 0 END),
                    SUM(CASE WHEN status = ? THEN 1 ELSE 0 END),
                    SUM(CASE WHEN status = ? THEN 1 ELSE 0 END),
                    SUM(CASE WHEN status = ? THEN 1 ELSE 0 END)
                FROM runtime_commands
                """,
                (STATUS_PENDING, STATUS_CLAIMED, STATUS_COMPLETED, STATUS_FAILED),
            )
            row = await cursor.fetchone()
        counts = row or (0, 0, 0, 0)
        return {
            "pending_count": int(counts[0] or 0),
            "claimed_count": int(counts[1] or 0),
            "completed_count": int(counts[2] or 0),
            "failed_count": int(counts[3] or 0),
        }

    async def _initialize(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    async def _recover_claimed_commands_after_restart(self) -> int:
        """Return prior-process claims to pending before this worker starts."""
        now = time.time()
        async with self._write_lock, sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    """
                    UPDATE runtime_commands
                    SET status = ?,
                        retry_count = retry_count + 1,
                        claimed_by = NULL,
                        claimed_at = NULL,
                        last_error = 'PROCESS_RESTART_RECOVERY',
                        updated_at = ?
                    WHERE status = ?
                    """,
                    (STATUS_PENDING, now, STATUS_CLAIMED),
                )
                recovered = int(cursor.rowcount or 0)
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return recovered

    async def _ensure_user_message_generation_loaded(self) -> None:
        if self._user_message_generation is not None:
            return
        async with self._user_message_generation_load_lock:
            if self._user_message_generation is not None:
                return
            async with sqlite_connection_async(self.db_path) as db:
                async with db.execute(
                    """
                    SELECT generation
                    FROM runtime_user_message_clear_state
                    WHERE singleton_id = ?
                    """,
                    (_USER_MESSAGE_CLEAR_STATE_ID,),
                ) as cursor:
                    row = await cursor.fetchone()
            if row is None:
                raise RuntimeError("Runtime user-message clear state is missing")
            self._user_message_generation = int(row[0])

    async def _update_status(self, *, command_id: int, status: str, clear_claim: bool) -> None:
        await self._initialize()
        async with self._write_lock, sqlite_connection_async(self.db_path) as db:
            await db.execute(
                """
                UPDATE runtime_commands
                SET status = ?,
                    claimed_by = CASE WHEN ? THEN NULL ELSE claimed_by END,
                    claimed_at = CASE WHEN ? THEN NULL ELSE claimed_at END,
                    updated_at = ?
                WHERE command_id = ?
                """,
                (status, int(clear_claim), int(clear_claim), time.time(), command_id),
            )
            if status == STATUS_COMPLETED:
                await db.execute(
                    """
                    UPDATE runtime_user_message_idempotency
                    SET delivery_status = 'completed'
                    WHERE first_command_id = ?
                    """,
                    (command_id,),
                )
            await db.commit()


def _payload_fingerprint(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
