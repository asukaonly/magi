"""SQLite write helpers for L4 procedural skill records."""
from __future__ import annotations

import json
from typing import Any

import aiosqlite

from ..hybrid_retrieval.fts_utils import tokenize_for_fts
from .procedural_memory_updates import NewSkillRecordState, UpdatedSkillRecordState


async def insert_new_skill_record(
    db: aiosqlite.Connection,
    *,
    skill_id: str,
    skill_name: str,
    skill_category: str,
    skill_type: str,
    record_state: NewSkillRecordState,
    optimized_prompt: str | None,
    event_id: str,
    event_timestamp: float,
    now: float,
) -> None:
    await db.execute(
        """
        INSERT INTO procedural_skills(
            skill_id, skill_name, skill_category, skill_type, proficiency,
            total_attempts, success_count, failure_count, success_rate,
            avg_execution_time_ms, min_execution_time_ms, max_execution_time_ms, p95_execution_time_ms,
            circuit_breaker_state, circuit_breaker_opened_at, circuit_breaker_failure_count,
            circuit_breaker_success_count, optimized_prompt, optimized_params, optimization_score,
            context_affinity, source_event_ids, last_used_at, last_success_at, last_failure_at,
            embedding_chunk_count, last_embedded_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            skill_id,
            skill_name,
            skill_category,
            skill_type,
            record_state.success_rate,
            record_state.total_attempts,
            record_state.success_count,
            record_state.failure_count,
            record_state.success_rate,
            record_state.avg_duration_ms,
            record_state.min_duration_ms,
            record_state.max_duration_ms,
            record_state.max_duration_ms,
            record_state.breaker_state,
            record_state.breaker_opened_at,
            record_state.failure_streak,
            record_state.recovery_count,
            optimized_prompt,
            json.dumps({}, ensure_ascii=False),
            None,
            json.dumps({}, ensure_ascii=False),
            json.dumps([event_id], ensure_ascii=False),
            event_timestamp,
            event_timestamp if record_state.success_count else None,
            event_timestamp if record_state.failure_count else None,
            0,
            None,
            now,
            now,
        ),
    )


async def update_skill_record(
    db: aiosqlite.Connection,
    *,
    skill_id: str,
    record_state: UpdatedSkillRecordState,
    optimized_prompt: str | None,
    event_timestamp: float,
    now: float,
) -> None:
    await db.execute(
        """
        UPDATE procedural_skills
        SET proficiency = ?, total_attempts = ?, success_count = ?, failure_count = ?, success_rate = ?,
            avg_execution_time_ms = ?, min_execution_time_ms = ?, max_execution_time_ms = ?, p95_execution_time_ms = ?,
            circuit_breaker_state = ?, circuit_breaker_opened_at = ?, circuit_breaker_failure_count = ?,
            circuit_breaker_success_count = ?, optimized_prompt = COALESCE(?, optimized_prompt),
            source_event_ids = ?, last_used_at = ?, last_success_at = ?, last_failure_at = ?, updated_at = ?,
            pending_trace_count = COALESCE(pending_trace_count, 0) + 1
        WHERE skill_id = ?
        """,
        (
            record_state.success_rate,
            record_state.total_attempts,
            record_state.success_count,
            record_state.failure_count,
            record_state.success_rate,
            record_state.avg_duration_ms,
            record_state.min_duration_ms,
            record_state.max_duration_ms,
            record_state.max_duration_ms,
            record_state.breaker_state,
            record_state.breaker_opened_at,
            record_state.failure_streak,
            record_state.recovery_count,
            optimized_prompt,
            json.dumps(record_state.source_event_ids[-100:], ensure_ascii=False),
            event_timestamp,
            record_state.last_success_at,
            record_state.last_failure_at,
            now,
            skill_id,
        ),
    )


async def sync_skill_fts(
    db: aiosqlite.Connection,
    *,
    skill_id: str,
    skill_name: str,
    skill_category: str,
    optimized_prompt: Any,
    replace_existing: bool,
) -> None:
    fts_text = tokenize_for_fts(f"{skill_name} {skill_category} {optimized_prompt or ''}")
    if replace_existing:
        await db.execute("DELETE FROM l4_skills_fts WHERE skill_id = ?", (skill_id,))
        await db.execute(
            "INSERT INTO l4_skills_fts(skill_id, content) VALUES (?, ?)",
            (skill_id, fts_text),
        )
        return
    await db.execute(
        "INSERT OR REPLACE INTO l4_skills_fts(skill_id, content) VALUES (?, ?)",
        (skill_id, fts_text),
    )
