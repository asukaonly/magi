"""SQLite-backed runtime command queue."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

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

FULL_CLEAR_SENSITIVE_COMMAND_TYPES = frozenset(
    {
        RuntimeCommandType.USER_MESSAGE,
        RuntimeCommandType.SENSOR_SYNC,
        RuntimeCommandType.SENSOR_STATE_FLUSH,
    }
)


class UserMessageScopeBlockedError(RuntimeError):
    """Raised when ingress targets a durably deleted chat scope."""


class StaleUserMessageDeliveryAttemptError(RuntimeError):
    """Raised when enqueue targets an attempt older than the current receipt."""


class InvalidExternalUserMessageMetadataError(ValueError):
    """Raised when a channel event lacks one valid clear-boundary proof."""


class StaleExternalUserMessageError(RuntimeError):
    """Raised when a channel event belongs to an earlier clear boundary."""


class UserMessageScheduleOutcome(str, Enum):
    """Result of scheduling one explicit logical-turn delivery attempt."""

    SCHEDULED = "scheduled"
    EXISTING = "existing"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class UserMessageScheduleResult:
    """Attempt-aware durable scheduling result for one logical user turn."""

    outcome: UserMessageScheduleOutcome
    command_id: int | None
    current_attempt_no: int


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
        self._full_clear_command_barrier = AsyncOperationBarrier()
        self._user_message_destructive_lock = asyncio.Lock()
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
        result = await self.schedule_user_message(command)
        if result.outcome is UserMessageScheduleOutcome.STALE:
            raise StaleUserMessageDeliveryAttemptError(
                "User-message delivery attempt is older than the current attempt"
            )
        if result.command_id is None:
            raise RuntimeError("User-message scheduling did not return a command ID")
        return result.command_id

    async def schedule_user_message(
        self,
        command: UserMessageCommand,
    ) -> UserMessageScheduleResult:
        """Schedule exactly the requested delivery attempt for one logical turn."""
        attempt_no = _normalize_delivery_attempt_no(command.delivery_attempt_no)
        correlation_id = str(command.correlation_id or "").strip()
        if not correlation_id:
            raise ValueError("User-message correlation ID is required")
        if command.runtime_command_id is not None:
            raise ValueError("A new user-message schedule cannot carry a runtime command ID")
        async with self.user_message_operation():
            await self._ensure_user_message_generation_loaded()
            await self._initialize()
            payload = command.to_payload()
            payload_json = json.dumps(payload, ensure_ascii=False)
            async with self._write_lock, sqlite_connection_async(self.db_path) as db:
                return await self._schedule_user_message_once(
                    db,
                    payload=payload,
                    payload_json=payload_json,
                    correlation_id=correlation_id,
                    delivery_attempt_no=attempt_no,
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
    ) -> int:
        if command_type is RuntimeCommandType.USER_MESSAGE:
            raise ValueError("User messages must use the attempt-aware scheduling API")
        if command_type in FULL_CLEAR_SENSITIVE_COMMAND_TYPES:
            async with self.clear_sensitive_command_operation():
                await self._ensure_user_message_generation_loaded()
                return await self._insert_command(
                    command_type=command_type,
                    payload=payload,
                    correlation_id=correlation_id,
                    created_at=created_at,
                    user_message_generation=self.current_user_message_generation(),
                )
        return await self._insert_command(
            command_type=command_type,
            payload=payload,
            correlation_id=correlation_id,
            created_at=created_at,
            user_message_generation=0,
        )

    async def _insert_command(
        self,
        *,
        command_type: RuntimeCommandType,
        payload: dict[str, object],
        correlation_id: str,
        created_at: float,
        user_message_generation: int,
    ) -> int:
        await self._initialize()
        payload_json = json.dumps(payload, ensure_ascii=False)
        async with self._write_lock, sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO runtime_commands (
                    command_type,
                    payload_json,
                    correlation_id,
                    status,
                    retry_count,
                    user_message_generation,
                    delivery_attempt_no,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, 0, ?, 0, ?, ?)
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

    async def _schedule_user_message_once(
        self,
        db,
        *,
        payload: dict[str, object],
        payload_json: str,
        correlation_id: str,
        delivery_attempt_no: int,
        created_at: float,
        user_message_generation: int,
    ) -> UserMessageScheduleResult:
        payload_fingerprint = _payload_fingerprint(payload)
        await db.execute("BEGIN IMMEDIATE")
        try:
            if await _user_message_scope_is_blocked(
                db,
                user_id=str(payload.get("user_id") or ""),
                session_id=str(payload.get("session_id") or ""),
                turn_id=str(payload.get("turn_id") or ""),
                message_id=_message_id_from_correlation_id(correlation_id),
            ):
                raise UserMessageScopeBlockedError(
                    "User-message scope was deleted before runtime enqueue"
                )
            cursor = await db.execute(
                """
                SELECT payload_fingerprint,
                       current_attempt_no,
                       current_command_id
                FROM runtime_user_message_idempotency
                WHERE correlation_id = ?
                """,
                (correlation_id,),
            )
            existing = await cursor.fetchone()
            if existing is not None:
                if str(existing[0]) != payload_fingerprint:
                    raise ValueError(
                        "User-message correlation id was reused for different input"
                    )
                current_attempt_no = int(existing[1])
                current_command_id = int(existing[2])
                if delivery_attempt_no < current_attempt_no:
                    await db.commit()
                    return UserMessageScheduleResult(
                        outcome=UserMessageScheduleOutcome.STALE,
                        command_id=current_command_id,
                        current_attempt_no=current_attempt_no,
                    )
                if delivery_attempt_no == current_attempt_no:
                    await db.commit()
                    return UserMessageScheduleResult(
                        outcome=UserMessageScheduleOutcome.EXISTING,
                        command_id=current_command_id,
                        current_attempt_no=current_attempt_no,
                    )

                command_id = await self._insert_user_message_command_row(
                    db,
                    payload_json=payload_json,
                    correlation_id=correlation_id,
                    delivery_attempt_no=delivery_attempt_no,
                    created_at=created_at,
                    user_message_generation=user_message_generation,
                )
                await db.execute(
                    """
                    UPDATE runtime_commands
                    SET status = ?,
                        claimed_by = NULL,
                        claimed_at = NULL,
                        last_error = 'SUPERSEDED_BY_NEW_DELIVERY_ATTEMPT',
                        updated_at = ?
                    WHERE command_id = ?
                      AND status != ?
                    """,
                    (
                        STATUS_COMPLETED,
                        time.time(),
                        current_command_id,
                        STATUS_COMPLETED,
                    ),
                )
                await db.execute(
                    """
                    UPDATE runtime_user_message_idempotency
                    SET current_attempt_no = ?,
                        current_command_id = ?,
                        delivery_status = 'open',
                        created_at = ?
                    WHERE correlation_id = ?
                    """,
                    (
                        delivery_attempt_no,
                        command_id,
                        float(created_at),
                        correlation_id,
                    ),
                )
                await db.commit()
                return UserMessageScheduleResult(
                    outcome=UserMessageScheduleOutcome.SCHEDULED,
                    command_id=command_id,
                    current_attempt_no=delivery_attempt_no,
                )

            command_id = await self._insert_user_message_command_row(
                db,
                payload_json=payload_json,
                correlation_id=correlation_id,
                delivery_attempt_no=delivery_attempt_no,
                created_at=created_at,
                user_message_generation=user_message_generation,
            )
            await db.execute(
                """
                INSERT INTO runtime_user_message_idempotency (
                    correlation_id,
                    payload_fingerprint,
                    current_attempt_no,
                    current_command_id,
                    delivery_status,
                    created_at
                ) VALUES (?, ?, ?, ?, 'open', ?)
                """,
                (
                    correlation_id,
                    payload_fingerprint,
                    delivery_attempt_no,
                    command_id,
                    float(created_at),
                ),
            )
            await db.commit()
            return UserMessageScheduleResult(
                outcome=UserMessageScheduleOutcome.SCHEDULED,
                command_id=command_id,
                current_attempt_no=delivery_attempt_no,
            )
        except BaseException:
            await db.rollback()
            raise

    @staticmethod
    async def _insert_user_message_command_row(
        db,
        *,
        payload_json: str,
        correlation_id: str,
        delivery_attempt_no: int,
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
                delivery_attempt_no,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?)
            """,
            (
                RuntimeCommandType.USER_MESSAGE.value,
                payload_json,
                correlation_id,
                STATUS_PENDING,
                int(user_message_generation),
                int(delivery_attempt_no),
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
                              retry_count, user_message_generation, delivery_attempt_no
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
            delivery_attempt_no=int(row[6] or 0),
        )

    @asynccontextmanager
    async def user_message_operation(self) -> AsyncIterator[None]:
        """Protect one end-to-end user-message ingress or dispatch operation."""
        async with self._user_message_barrier.operation():
            yield

    @asynccontextmanager
    async def clear_sensitive_command_operation(self) -> AsyncIterator[None]:
        """Protect work whose payload must not cross a full-clear boundary."""
        async with self._full_clear_command_barrier.operation():
            yield

    @asynccontextmanager
    async def user_message_destructive_operation(self) -> AsyncIterator[None]:
        """Serialize destructive chat and full-memory operations."""

        async with self._user_message_destructive_lock:
            yield

    @asynccontextmanager
    async def user_message_global_clear_boundary(self) -> AsyncIterator[None]:
        """Serialize and quiesce every clear-sensitive runtime path."""

        async with self.user_message_destructive_operation():
            async with self._full_clear_command_barrier.exclusive():
                async with self.user_message_clear_boundary():
                    initial_generation, _ = await self._load_user_message_clear_state()
                    try:
                        yield
                    finally:
                        current_generation, _ = await self._load_user_message_clear_state()
                        if current_generation != initial_generation:
                            await self.seal_external_user_message_clear_cutoff()

    @asynccontextmanager
    async def user_message_clear_boundary(self) -> AsyncIterator[None]:
        """Block user-message work during a destructive chat operation."""
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

    async def read_current_clear_generation(self) -> int:
        """Read the current user-message generation from durable storage."""

        generation, _ = await self._load_user_message_clear_state()
        return generation

    async def capture_external_user_message_context(
        self,
        *,
        provider_occurred_at_ms: object | None = None,
        cursor_clear_generation: object | None = None,
    ) -> int:
        """Capture the current clear generation for one external event.

        Exactly one proof is required. Provider-time channels are checked
        against the durable clear cutoff. Cursor channels are admitted only
        when their durably persisted clear generation exactly matches the host.
        """

        normalized_occurred_at_ms, normalized_cursor_generation = (
            _normalize_external_user_message_evidence(
                provider_occurred_at_ms=provider_occurred_at_ms,
                cursor_clear_generation=cursor_clear_generation,
            )
        )
        async with self.user_message_operation():
            generation, cleared_at_ms = await self._load_user_message_clear_state()
            _validate_external_user_message_boundary(
                provider_occurred_at_ms=normalized_occurred_at_ms,
                cursor_clear_generation=normalized_cursor_generation,
                captured_generation=generation,
                current_generation=generation,
                cleared_at_ms=cleared_at_ms,
            )
            return generation

    @asynccontextmanager
    async def external_user_message_operation(
        self,
        *,
        provider_occurred_at_ms: object | None = None,
        cursor_clear_generation: object | None = None,
        captured_generation: int,
    ) -> AsyncIterator[None]:
        """Validate and protect one channel-side inbound state mutation."""

        normalized_occurred_at_ms, normalized_cursor_generation = (
            _normalize_external_user_message_evidence(
                provider_occurred_at_ms=provider_occurred_at_ms,
                cursor_clear_generation=cursor_clear_generation,
            )
        )
        normalized_generation = _normalize_external_clear_generation(
            captured_generation
        )
        async with self.user_message_operation():
            current_generation, cleared_at_ms = (
                await self._load_user_message_clear_state()
            )
            _validate_external_user_message_boundary(
                provider_occurred_at_ms=normalized_occurred_at_ms,
                cursor_clear_generation=normalized_cursor_generation,
                captured_generation=normalized_generation,
                current_generation=current_generation,
                cleared_at_ms=cleared_at_ms,
            )
            yield

    async def is_user_message_scope_blocked(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None = None,
        message_id: str | None = None,
        correlation_id: str | None = None,
    ) -> bool:
        """Return whether a session or exact user turn has been deleted."""
        normalized_message_id = str(message_id or "").strip() or _message_id_from_correlation_id(
            correlation_id
        )
        await self._initialize()
        async with sqlite_connection_async(self.db_path) as db:
            return await _user_message_scope_is_blocked(
                db,
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
                message_id=normalized_message_id,
            )

    async def is_user_message_command_blocked(self, command: RuntimeQueuedCommand) -> bool:
        """Return whether one claimed command crossed a deletion barrier."""
        if command.command_type is not RuntimeCommandType.USER_MESSAGE:
            return False
        return await self.is_user_message_scope_blocked(
            user_id=str(command.payload.get("user_id") or ""),
            session_id=str(command.payload.get("session_id") or ""),
            turn_id=str(command.payload.get("turn_id") or ""),
            correlation_id=command.correlation_id,
        )

    async def block_user_message_scope_and_purge(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str | None = None,
        message_id: str | None = None,
        reason: str,
    ) -> int:
        """Persist one exact deletion barrier and remove matching queue payloads."""
        task = asyncio.current_task()
        if task is None or task is not self._user_message_clear_owner:
            raise RuntimeError("User-message scope deletion requires the clear boundary")
        normalized_user_id = str(user_id or "").strip()
        normalized_session_id = str(session_id or "").strip()
        normalized_turn_id = str(turn_id or "").strip()
        normalized_message_id = str(message_id or "").strip()
        normalized_reason = str(reason or "").strip()
        if not normalized_user_id or not normalized_session_id or not normalized_reason:
            raise ValueError("User ID, session ID, and deletion reason are required")

        scopes = (
            [("session", normalized_session_id)]
            if not normalized_turn_id and not normalized_message_id
            else [
                *([("turn", normalized_turn_id)] if normalized_turn_id else []),
                *([("message", normalized_message_id)] if normalized_message_id else []),
            ]
        )
        now = time.time()
        await self._initialize()
        async with self._write_lock, sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                await db.executemany(
                    """
                    INSERT OR IGNORE INTO runtime_user_message_scope_blocks (
                        scope_kind, user_id, session_id, scope_value, reason, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            scope_kind,
                            normalized_user_id,
                            normalized_session_id,
                            scope_value,
                            normalized_reason,
                            now,
                        )
                        for scope_kind, scope_value in scopes
                    ],
                )
                command_ids = await _matching_user_message_command_ids(
                    db,
                    user_id=normalized_user_id,
                    session_id=normalized_session_id,
                    turn_id=normalized_turn_id,
                    message_id=normalized_message_id,
                )
                if command_ids:
                    placeholders = ", ".join("?" for _ in command_ids)
                    await db.execute(
                        f"DELETE FROM runtime_user_message_idempotency "
                        f"WHERE current_command_id IN ({placeholders})",
                        command_ids,
                    )
                    await db.execute(
                        f"DELETE FROM runtime_commands WHERE command_id IN ({placeholders})",
                        command_ids,
                    )
                if normalized_message_id:
                    await db.execute(
                        "DELETE FROM runtime_user_message_idempotency WHERE correlation_id = ?",
                        (f"user_message:{normalized_message_id}",),
                    )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        return len(command_ids)

    async def advance_user_message_generation_and_purge(self) -> tuple[int, int]:
        """Advance the clear generation and remove every older sensitive command."""

        task = asyncio.current_task()
        if task is None or task is not self._user_message_clear_owner:
            raise RuntimeError("User-message generation can only advance inside its clear boundary")
        await self._ensure_user_message_generation_loaded()
        now = time.time()
        async with self._write_lock, sqlite_connection_async(self.db_path) as db:
            await db.execute("PRAGMA secure_delete=ON")
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
                    WHERE command_type IN (?, ?, ?)
                    """,
                    tuple(
                        command_type.value
                        for command_type in FULL_CLEAR_SENSITIVE_COMMAND_TYPES
                    ),
                )
                purged_count = int(cursor.rowcount or 0)
                await db.execute("DELETE FROM runtime_user_message_idempotency")
                await db.execute("DELETE FROM runtime_user_message_scope_blocks")
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
            await db.execute("VACUUM")
            checkpoint_cursor = await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            checkpoint = await checkpoint_cursor.fetchone()
            if checkpoint is not None and int(checkpoint[0] or 0) != 0:
                raise RuntimeError("Runtime clear could not truncate the WAL")
        self._user_message_generation = next_generation
        return next_generation, purged_count

    async def seal_external_user_message_clear_cutoff(self) -> int:
        """Move the provider-event cutoff to the end of a completed clear.

        The generation advances at clear admission so already captured work
        becomes stale immediately. This second timestamp update rejects provider
        events that occurred while the clear held the exclusive boundary.
        """

        task = asyncio.current_task()
        if task is None or task is not self._user_message_clear_owner:
            raise RuntimeError(
                "External user-message cutoff can only seal inside the clear boundary"
            )
        now = time.time()
        async with self._write_lock, sqlite_connection_async(self.db_path) as db:
            await db.execute(
                """
                UPDATE runtime_user_message_clear_state
                SET updated_at = ?
                WHERE singleton_id = ?
                """,
                (now, _USER_MESSAGE_CLEAR_STATE_ID),
            )
            await db.commit()
        return int(now * 1000)

    async def ack(self, command_id: int) -> None:
        await self._update_status(command_id=command_id, status=STATUS_COMPLETED, clear_claim=True)

    async def requeue(self, command_id: int, *, error_text: str | None = None) -> None:
        await self._initialize()
        async with self._write_lock, sqlite_connection_async(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    """
                    SELECT command_type, correlation_id
                    FROM runtime_commands
                    WHERE command_id = ?
                    """,
                    (command_id,),
                )
                row = await cursor.fetchone()
                if row is None:
                    await db.commit()
                    return
                is_user_message = str(row[0]) == RuntimeCommandType.USER_MESSAGE.value
                is_current_delivery = True
                if is_user_message:
                    cursor = await db.execute(
                        """
                        SELECT 1
                        FROM runtime_user_message_idempotency
                        WHERE correlation_id = ?
                          AND current_command_id = ?
                        """,
                        (str(row[1]), command_id),
                    )
                    is_current_delivery = await cursor.fetchone() is not None
                if is_user_message and not is_current_delivery:
                    await db.execute(
                        """
                        UPDATE runtime_commands
                        SET status = ?,
                            last_error = 'STALE_DELIVERY_ATTEMPT',
                            claimed_by = NULL,
                            claimed_at = NULL,
                            updated_at = ?
                        WHERE command_id = ?
                        """,
                        (STATUS_COMPLETED, time.time(), command_id),
                    )
                    await db.commit()
                    return
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
                    WHERE current_command_id = ?
                    """,
                    (command_id,),
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

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

    async def _load_user_message_clear_state(self) -> tuple[int, int]:
        """Read the generation and clear timestamp from durable storage."""

        await self._initialize()
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                """
                SELECT generation, updated_at
                FROM runtime_user_message_clear_state
                WHERE singleton_id = ?
                """,
                (_USER_MESSAGE_CLEAR_STATE_ID,),
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("Runtime user-message clear state is missing")
        return int(row[0]), int(float(row[1]) * 1000)

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
                    WHERE current_command_id = ?
                    """,
                    (command_id,),
                )
            await db.commit()


def _payload_fingerprint(payload: dict[str, object]) -> str:
    stable_payload = dict(payload)
    stable_payload.pop("delivery_attempt_no", None)
    stable_payload.pop("runtime_command_id", None)
    canonical = json.dumps(
        stable_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalize_delivery_attempt_no(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("Delivery attempt number must be a non-negative integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Delivery attempt number must be a non-negative integer"
        ) from exc
    if normalized < 0:
        raise ValueError("Delivery attempt number must be a non-negative integer")
    return normalized


def _normalize_provider_occurred_at_ms(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidExternalUserMessageMetadataError(
            "Provider occurrence time must be a positive integer in epoch milliseconds"
        )
    return value


def _normalize_external_user_message_evidence(
    *,
    provider_occurred_at_ms: object | None,
    cursor_clear_generation: object | None,
) -> tuple[int | None, int | None]:
    has_provider_time = provider_occurred_at_ms is not None
    has_cursor_generation = cursor_clear_generation is not None
    if has_provider_time == has_cursor_generation:
        raise InvalidExternalUserMessageMetadataError(
            "Exactly one external message clear-boundary proof is required"
        )
    if has_provider_time:
        return _normalize_provider_occurred_at_ms(provider_occurred_at_ms), None
    return None, _normalize_external_clear_generation(cursor_clear_generation)


def _normalize_external_clear_generation(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidExternalUserMessageMetadataError(
            "Captured clear generation must be a non-negative integer"
        )
    return value


def _validate_external_user_message_boundary(
    *,
    provider_occurred_at_ms: int | None,
    cursor_clear_generation: int | None,
    captured_generation: int,
    current_generation: int,
    cleared_at_ms: int,
) -> None:
    if captured_generation != current_generation:
        raise StaleExternalUserMessageError(
            "External message crossed a destructive clear boundary"
        )
    if (
        cursor_clear_generation is not None
        and cursor_clear_generation != current_generation
    ):
        raise StaleExternalUserMessageError(
            "External message cursor did not cross the latest destructive clear"
        )
    if (
        provider_occurred_at_ms is not None
        and current_generation > 0
        and provider_occurred_at_ms <= cleared_at_ms
    ):
        raise StaleExternalUserMessageError(
            "External message occurred before the latest destructive clear"
        )


def _message_id_from_correlation_id(correlation_id: str | None) -> str:
    normalized = str(correlation_id or "").strip()
    prefix = "user_message:"
    if not normalized.startswith(prefix):
        return ""
    return normalized[len(prefix) :].strip()


async def _user_message_scope_is_blocked(
    db,
    *,
    user_id: str,
    session_id: str,
    turn_id: str | None,
    message_id: str | None,
) -> bool:
    normalized_user_id = str(user_id or "").strip()
    normalized_session_id = str(session_id or "").strip()
    normalized_turn_id = str(turn_id or "").strip()
    normalized_message_id = str(message_id or "").strip()
    if not normalized_user_id or not normalized_session_id:
        return True
    conditions = ["scope_kind = 'session'"]
    params: list[object] = [normalized_user_id, normalized_session_id]
    if normalized_turn_id:
        conditions.append("(scope_kind = 'turn' AND scope_value = ?)")
        params.append(normalized_turn_id)
    if normalized_message_id:
        conditions.append("(scope_kind = 'message' AND scope_value = ?)")
        params.append(normalized_message_id)
    cursor = await db.execute(
        f"""
        SELECT 1
        FROM runtime_user_message_scope_blocks
        WHERE user_id = ?
          AND session_id = ?
          AND ({' OR '.join(conditions)})
        LIMIT 1
        """,
        params,
    )
    return await cursor.fetchone() is not None


async def _matching_user_message_command_ids(
    db,
    *,
    user_id: str,
    session_id: str,
    turn_id: str,
    message_id: str,
) -> list[int]:
    scope_conditions: list[str] = []
    params: list[object] = [
        RuntimeCommandType.USER_MESSAGE.value,
        user_id,
        session_id,
    ]
    if turn_id:
        scope_conditions.append("json_extract(payload_json, '$.turn_id') = ?")
        params.append(turn_id)
    if message_id:
        scope_conditions.append("correlation_id = ?")
        params.append(f"user_message:{message_id}")
    scope_sql = f" AND ({' OR '.join(scope_conditions)})" if scope_conditions else ""
    cursor = await db.execute(
        f"""
        SELECT command_id
        FROM runtime_commands
        WHERE command_type = ?
          AND json_valid(payload_json)
          AND json_extract(payload_json, '$.user_id') = ?
          AND json_extract(payload_json, '$.session_id') = ?
          {scope_sql}
        ORDER BY command_id
        """,
        params,
    )
    return [int(row[0]) for row in await cursor.fetchall()]


__all__ = [
    "InvalidExternalUserMessageMetadataError",
    "SQLiteRuntimeCommandQueue",
    "StaleExternalUserMessageError",
    "StaleUserMessageDeliveryAttemptError",
    "UserMessageScopeBlockedError",
    "UserMessageScheduleOutcome",
    "UserMessageScheduleResult",
]
