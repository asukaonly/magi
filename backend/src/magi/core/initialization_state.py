"""Durable state for versioned and content-addressed startup work."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import os
from pathlib import Path
import time
from typing import TypeVar
import uuid

from .sqlite import sqlite_connection_async, sqlite_transaction_async


_RESULT = TypeVar("_RESULT")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS initialization_steps (
    step_id               TEXT PRIMARY KEY,
    completed_revision    TEXT,
    completed_fingerprint TEXT,
    status                TEXT NOT NULL,
    attempt_revision      TEXT NOT NULL,
    attempt_fingerprint   TEXT,
    attempt_count         INTEGER NOT NULL DEFAULT 0,
    owner_token           TEXT,
    owner_pid             INTEGER,
    started_at            REAL,
    completed_at          REAL,
    updated_at            REAL NOT NULL,
    last_error            TEXT,
    CHECK (status IN ('running', 'completed', 'failed'))
);
"""


class InitializationStepBusyError(RuntimeError):
    """Raised when another live process owns the same initialization step."""


@dataclass(frozen=True, slots=True)
class InitializationStepRecord:
    """Persisted completion and latest-attempt state for one startup step."""

    step_id: str
    completed_revision: str | None
    completed_fingerprint: str | None
    status: str
    attempt_revision: str
    attempt_fingerprint: str | None
    attempt_count: int
    owner_pid: int | None
    started_at: float | None
    completed_at: float | None
    updated_at: float
    last_error: str | None


class InitializationStateStore:
    """Coordinate durable startup work without rewriting unchanged state."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path).expanduser()
        self._owner_token = f"{os.getpid()}:{uuid.uuid4()}"

    @property
    def db_path(self) -> Path:
        return self._db_path

    async def initialize(self) -> None:
        async with sqlite_connection_async(self._db_path) as db:
            await db.executescript(_SCHEMA)
            await db.commit()

    async def get_step(self, step_id: str) -> InitializationStepRecord | None:
        async with sqlite_connection_async(self._db_path) as db:
            cursor = await db.execute(
                """
                SELECT step_id, completed_revision, completed_fingerprint,
                       status, attempt_revision, attempt_fingerprint,
                       attempt_count, owner_pid, started_at, completed_at,
                       updated_at, last_error
                FROM initialization_steps
                WHERE step_id = ?
                """,
                (step_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return InitializationStepRecord(
            step_id=str(row["step_id"]),
            completed_revision=row["completed_revision"],
            completed_fingerprint=row["completed_fingerprint"],
            status=str(row["status"]),
            attempt_revision=str(row["attempt_revision"]),
            attempt_fingerprint=row["attempt_fingerprint"],
            attempt_count=int(row["attempt_count"]),
            owner_pid=int(row["owner_pid"]) if row["owner_pid"] is not None else None,
            started_at=float(row["started_at"]) if row["started_at"] is not None else None,
            completed_at=float(row["completed_at"]) if row["completed_at"] is not None else None,
            updated_at=float(row["updated_at"]),
            last_error=row["last_error"],
        )

    async def run_step(
        self,
        *,
        step_id: str,
        revision: str,
        fingerprint: str | None,
        operation: Callable[[], Awaitable[_RESULT]],
        force: bool = False,
    ) -> tuple[bool, _RESULT | None]:
        """Run one step when its completed revision or fingerprint is stale."""
        normalized_step_id = step_id.strip()
        normalized_revision = revision.strip()
        if not normalized_step_id:
            raise ValueError("step_id is required")
        if not normalized_revision:
            raise ValueError("revision is required")

        claimed = await self._claim_step(
            step_id=normalized_step_id,
            revision=normalized_revision,
            fingerprint=fingerprint,
            force=force,
        )
        if not claimed:
            return False, None

        try:
            result = await operation()
        except Exception as exc:
            await self._record_failure(normalized_step_id, exc)
            raise

        await self._record_success(
            step_id=normalized_step_id,
            revision=normalized_revision,
            fingerprint=fingerprint,
        )
        return True, result

    async def _claim_step(
        self,
        *,
        step_id: str,
        revision: str,
        fingerprint: str | None,
        force: bool,
    ) -> bool:
        now = time.time()
        async with sqlite_transaction_async(self._db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """
                SELECT completed_revision, completed_fingerprint, status,
                       owner_token, owner_pid
                FROM initialization_steps
                WHERE step_id = ?
                """,
                (step_id,),
            )
            row = await cursor.fetchone()
            if row is not None:
                completed_matches = (
                    row["completed_revision"] == revision
                    and row["completed_fingerprint"] == fingerprint
                )
                if completed_matches and not force:
                    return False
                if (
                    row["status"] == "running"
                    and row["owner_token"] != self._owner_token
                    and _process_is_alive(row["owner_pid"])
                ):
                    raise InitializationStepBusyError(
                        f"Initialization step is owned by another live process: {step_id}"
                    )

            await db.execute(
                """
                INSERT INTO initialization_steps (
                    step_id, status, attempt_revision, attempt_fingerprint,
                    attempt_count, owner_token, owner_pid, started_at,
                    updated_at, last_error
                )
                VALUES (?, 'running', ?, ?, 1, ?, ?, ?, ?, NULL)
                ON CONFLICT(step_id) DO UPDATE SET
                    status = 'running',
                    attempt_revision = excluded.attempt_revision,
                    attempt_fingerprint = excluded.attempt_fingerprint,
                    attempt_count = initialization_steps.attempt_count + 1,
                    owner_token = excluded.owner_token,
                    owner_pid = excluded.owner_pid,
                    started_at = excluded.started_at,
                    updated_at = excluded.updated_at,
                    last_error = NULL
                """,
                (
                    step_id,
                    revision,
                    fingerprint,
                    self._owner_token,
                    os.getpid(),
                    now,
                    now,
                ),
            )
        return True

    async def _record_success(
        self,
        *,
        step_id: str,
        revision: str,
        fingerprint: str | None,
    ) -> None:
        now = time.time()
        async with sqlite_transaction_async(self._db_path) as db:
            cursor = await db.execute(
                """
                UPDATE initialization_steps
                SET completed_revision = ?, completed_fingerprint = ?,
                    status = 'completed', completed_at = ?, updated_at = ?,
                    owner_token = NULL, owner_pid = NULL, last_error = NULL
                WHERE step_id = ? AND owner_token = ? AND status = 'running'
                """,
                (revision, fingerprint, now, now, step_id, self._owner_token),
            )
            if cursor.rowcount != 1:
                raise InitializationStepBusyError(
                    f"Initialization step ownership changed before completion: {step_id}"
                )

    async def _record_failure(self, step_id: str, exc: Exception) -> None:
        now = time.time()
        async with sqlite_transaction_async(self._db_path) as db:
            await db.execute(
                """
                UPDATE initialization_steps
                SET status = 'failed', updated_at = ?, owner_token = NULL,
                    owner_pid = NULL, last_error = ?
                WHERE step_id = ? AND owner_token = ? AND status = 'running'
                """,
                (now, f"{type(exc).__name__}: {exc}"[:4000], step_id, self._owner_token),
            )


def _process_is_alive(raw_pid: object) -> bool:
    if isinstance(raw_pid, bool) or raw_pid is None:
        return False
    try:
        if isinstance(raw_pid, int):
            pid = raw_pid
        elif isinstance(raw_pid, (str, bytes, bytearray)):
            pid = int(raw_pid)
        else:
            return False
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


__all__ = [
    "InitializationStateStore",
    "InitializationStepBusyError",
    "InitializationStepRecord",
]
