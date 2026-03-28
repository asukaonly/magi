"""SQLite-backed runtime command queue."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterable

import aiosqlite

from ..core.sqlite import sqlite_connection_async
from .contracts import (
    RefreshLLMConfigCommand,
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

    def __init__(self, *, db_path: str = "~/.magi/data/message_queue.db", poll_interval_seconds: float = 0.1) -> None:
        self.db_path = str(Path(db_path).expanduser())
        self.poll_interval_seconds = poll_interval_seconds
        self._started = False

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

    async def enqueue_sensor_sync(self, command: SensorSyncCommand) -> int:
        return await self._enqueue_command(
            command_type=RuntimeCommandType.SENSOR_SYNC,
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
        async with sqlite_connection_async(self.db_path) as db:
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
        async with sqlite_connection_async(self.db_path) as db:
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
        async with sqlite_connection_async(self.db_path) as db:
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
            pending_count = await self._count_by_status(db, STATUS_PENDING)
            claimed_count = await self._count_by_status(db, STATUS_CLAIMED)
            completed_count = await self._count_by_status(db, STATUS_COMPLETED)
            failed_count = await self._count_by_status(db, STATUS_FAILED)
        return {
            "pending_count": pending_count,
            "claimed_count": claimed_count,
            "completed_count": completed_count,
            "failed_count": failed_count,
        }

    async def _initialize(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with sqlite_connection_async(self.db_path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS runtime_commands (
                    command_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    command_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    claimed_by TEXT,
                    claimed_at REAL,
                    last_error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_runtime_commands_status_created
                    ON runtime_commands(status, created_at ASC);
                CREATE INDEX IF NOT EXISTS idx_runtime_commands_type_status_created
                    ON runtime_commands(command_type, status, created_at ASC);
                """
            )
            await db.commit()

    async def _update_status(self, *, command_id: int, status: str, clear_claim: bool) -> None:
        await self._initialize()
        async with sqlite_connection_async(self.db_path) as db:
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

    @staticmethod
    async def _count_by_status(db: aiosqlite.Connection, status: str) -> int:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM runtime_commands WHERE status = ?",
            (status,),
        )
        row = await cursor.fetchone()
        return int(row[0] or 0)
