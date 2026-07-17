"""SQLite write helpers for L4 execution trace persistence."""

from __future__ import annotations

import time
import uuid
from typing import Any

from ....core.sqlite import sqlite_connection_async
from ...event_contracts import MemoryEvent
from ..source_event_governance import active_skill_predicate, skill_accepts_source_event
from ..storage.schema import EXECUTION_TRACES_TABLE, MAX_TRACES_PER_SKILL


async def insert_execution_trace(
    *,
    db_path: str,
    skill_id: str,
    event: MemoryEvent,
    identity: dict[str, Any],
) -> None:
    trace_id = f"trace_{uuid.uuid4().hex}"
    now = time.time()
    async with sqlite_connection_async(db_path) as db:
        await db.execute("BEGIN IMMEDIATE")
        try:
            if not await skill_accepts_source_event(
                db,
                event_id=event.event_id,
                turn_id=event.turn_id,
            ):
                await db.rollback()
                return
            async with db.execute(
                f"""
                SELECT 1
                FROM procedural_skills AS skills
                WHERE skills.skill_id = ? AND {active_skill_predicate("skills")}
                """,
                (skill_id,),
            ) as cursor:
                active = await cursor.fetchone()
            if active is None:
                await db.rollback()
                return
            await db.execute(
                f"""
                INSERT INTO {EXECUTION_TRACES_TABLE}(
                    trace_id, skill_id, event_id, turn_id, success, duration_ms,
                    error_summary, input_summary, output_summary, task_context,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace_id,
                    skill_id,
                    event.event_id,
                    event.turn_id,
                    1 if identity["success"] else 0,
                    identity["duration_ms"],
                    identity.get("error_summary"),
                    identity.get("input_summary"),
                    identity.get("output_summary"),
                    identity.get("task_context"),
                    now,
                ),
            )
            await db.commit()
        except BaseException:
            await db.rollback()
            raise
    await prune_old_traces(db_path=db_path, skill_id=skill_id)


async def prune_old_traces(*, db_path: str, skill_id: str) -> None:
    async with sqlite_connection_async(db_path) as db:
        await db.execute(
            f"""
            DELETE FROM {EXECUTION_TRACES_TABLE}
            WHERE skill_id = ? AND trace_id NOT IN (
                SELECT trace_id FROM {EXECUTION_TRACES_TABLE}
                WHERE skill_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            )
            """,
            (skill_id, skill_id, MAX_TRACES_PER_SKILL),
        )
        await db.commit()
