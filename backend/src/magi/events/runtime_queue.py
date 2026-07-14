"""SQLite-backed runtime command queue."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Iterable

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


class SQLiteRuntimeCommandQueue:
    """Persisted command queue used between API and runtime worker processes."""

    def __init__(self, *, db_path: str = "~/.magi/runtime/message_queue.db", poll_interval_seconds: float = 0.1) -> None:
        self.db_path = str(Path(db_path).expanduser())
        self.poll_interval_seconds = poll_interval_seconds
        self._started = False
        # Serialize this instance's writes. Producer (enqueue) and consumer
        # (claim_next, run at a tight poll interval) share one instance in-process,
        # so without this they issue concurrent write transactions to the same
        # SQLite file. WAL + busy_timeout cover cross-process access, but in-process
        # concurrent writers can still intermittently raise "database is locked"
        # under load (CI). An asyncio.Lock makes in-process writes strictly serial.
        self._write_lock = asyncio.Lock()

    async def start(self) -> None:
        if self._started:
            return
        await self._initialize()
        self._started = True

    async def stop(self) -> None:
        self._started = False

    async def enqueue_user_message(self, command: UserMessageCommand) -> int:
        return await self._enqueue_command(
            command_type=RuntimeCommandType.USER_MESSAGE,
            payload=command.to_payload(),
            correlation_id=command.correlation_id,
            created_at=command.created_at,
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
        await self._initialize()
        async with self._write_lock, sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO runtime_commands (
                    command_type,
                    payload_json,
                    correlation_id,
                    status,
                    retry_count,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    command_type.value,
                    json.dumps(payload, ensure_ascii=False),
                    correlation_id,
                    STATUS_PENDING,
                    float(created_at),
                    float(created_at),
                ),
            )
            await db.commit()
            return int(cursor.lastrowid)

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
                RETURNING command_id, command_type, payload_json, correlation_id, retry_count
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
        )

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
            await db.commit()
