"""Transactional write helpers for L4 execution trace persistence."""

from __future__ import annotations

import math
import time
import uuid
from typing import Any

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...event_contracts import MemoryEvent
from ..storage.schema import EXECUTION_TRACES_TABLE, MAX_TRACES_PER_SKILL


async def insert_execution_trace(
    db: aiosqlite.Connection,
    *,
    skill_id: str,
    event: MemoryEvent,
    identity: dict[str, Any],
) -> None:
    """Insert an execution inside the caller's fenced learning transaction."""
    trace_id = f"trace_{uuid.uuid5(uuid.NAMESPACE_URL, skill_id + ':' + event.event_id).hex}"
    await db.execute(
        f"""
        INSERT INTO {EXECUTION_TRACES_TABLE}(
            trace_id, skill_id, event_id, turn_id, success, duration_ms,
            error_summary, input_summary, output_summary, task_context, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            trace_id, skill_id, event.event_id, event.turn_id,
            1 if identity["success"] else 0, identity["duration_ms"],
            identity.get("error_summary"), identity.get("input_summary"),
            identity.get("output_summary"), identity.get("task_context"), time.time(),
        ),
    )
    await _prune_old_traces_on_connection(db, skill_id=skill_id)
    await _refresh_duration_percentile(db, skill_id=skill_id)


async def _refresh_duration_percentile(db: aiosqlite.Connection, *, skill_id: str) -> None:
    """Persist the nearest-rank P95 of the bounded retained execution window."""
    async with db.execute(
        f"SELECT duration_ms FROM {EXECUTION_TRACES_TABLE} WHERE skill_id = ? ORDER BY duration_ms",
        (skill_id,),
    ) as cursor:
        durations = [float(row[0]) for row in await cursor.fetchall() if row[0] is not None]
    percentile = durations[math.ceil(len(durations) * 0.95) - 1] if durations else None
    await db.execute(
        "UPDATE procedural_skills SET p95_execution_time_ms = ? WHERE skill_id = ?",
        (percentile, skill_id),
    )


async def _prune_old_traces_on_connection(db: aiosqlite.Connection, *, skill_id: str) -> None:
    deleted = await db.execute(
        f"""
        DELETE FROM {EXECUTION_TRACES_TABLE}
        WHERE skill_id = ? AND trace_id NOT IN (
            SELECT trace_id FROM {EXECUTION_TRACES_TABLE}
            WHERE skill_id = ? ORDER BY created_at DESC, trace_id DESC LIMIT ?
        )
        """,
        (skill_id, skill_id, MAX_TRACES_PER_SKILL),
    )
    if deleted.rowcount:
        await db.execute(
            f"UPDATE procedural_skills SET pending_trace_count = (SELECT COUNT(*) FROM {EXECUTION_TRACES_TABLE} WHERE skill_id = ? AND strategy_processed_at IS NULL) WHERE skill_id = ?",
            (skill_id, skill_id),
        )


async def prune_old_traces(*, db_path: str, skill_id: str) -> None:
    async with sqlite_connection_async(db_path) as db:
        await _prune_old_traces_on_connection(db, skill_id=skill_id)
        await _refresh_duration_percentile(db, skill_id=skill_id)
        await db.commit()
