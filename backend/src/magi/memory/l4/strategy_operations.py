"""Strategy extraction operations for L4 procedural memory."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from .source_event_governance import active_skill_predicate
from .storage.schema import EXECUTION_TRACES_TABLE
from .storage.records import sync_skill_fts
from .strategy_extraction import ExtractedStrategy, L4StrategyExtractor
from .traces.analysis import (
    apply_recovery_annotations,
    duration_baseline_from_row,
    failure_turn_ids,
    merge_stratified_trace_rows,
    recovery_map_from_rows,
)

logger = logging.getLogger(__name__)


async def stratified_traces(
    *,
    db_path: str,
    skill_id: str,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Return a diverse sample of recent failure, success, and mixed traces."""
    bucket_size = max(1, limit // 3)

    async with sqlite_connection_async(db_path) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute(
            f"""
            SELECT traces.*
            FROM {EXECUTION_TRACES_TABLE} AS traces
            JOIN procedural_skills AS skills ON skills.skill_id = traces.skill_id
            WHERE traces.skill_id = ? AND traces.success = 0
              AND {active_skill_predicate("skills")}
              AND traces.strategy_processed_at IS NULL
            ORDER BY traces.created_at DESC LIMIT ?
            """,
            (skill_id, bucket_size),
        ) as cursor:
            failures = await cursor.fetchall()

        async with db.execute(
            f"""
            SELECT traces.*
            FROM {EXECUTION_TRACES_TABLE} AS traces
            JOIN procedural_skills AS skills ON skills.skill_id = traces.skill_id
            WHERE traces.skill_id = ? AND traces.success = 1
              AND {active_skill_predicate("skills")}
              AND traces.strategy_processed_at IS NULL
            ORDER BY traces.created_at DESC LIMIT ?
            """,
            (skill_id, bucket_size),
        ) as cursor:
            successes = await cursor.fetchall()

        async with db.execute(
            f"""
            SELECT traces.*
            FROM {EXECUTION_TRACES_TABLE} AS traces
            JOIN procedural_skills AS skills ON skills.skill_id = traces.skill_id
            WHERE traces.skill_id = ?
              AND {active_skill_predicate("skills")}
              AND traces.strategy_processed_at IS NULL
            ORDER BY traces.created_at DESC LIMIT ?
            """,
            (skill_id, limit),
        ) as cursor:
            recent = await cursor.fetchall()

    return merge_stratified_trace_rows(
        failures=failures,
        successes=successes,
        recent=recent,
        limit=limit,
    )


async def maybe_extract_strategy(
    *,
    db_path: str,
    strategy_extractor: L4StrategyExtractor | None,
    skill_id: str,
    skill_name: str,
    skill_category: str,
    total_attempts: int,
    success_rate: float,
) -> bool:
    """Conditionally run LLM strategy extraction and persist the result."""
    if strategy_extractor is None:
        return False
    async with sqlite_connection_async(db_path) as db:
        async with db.execute("SELECT strategy_revision FROM procedural_skills WHERE skill_id = ?", (skill_id,)) as cursor:
            snapshot = await cursor.fetchone()
    if snapshot is None:
        return False
    traces = await stratified_traces(db_path=db_path, skill_id=skill_id, limit=20)
    if not traces:
        return False

    duration_baseline = await get_duration_baseline(db_path=db_path, skill_id=skill_id)
    await enrich_with_recovery(db_path=db_path, traces=traces, current_skill_id=skill_id)

    strategy = await strategy_extractor.extract_strategy(
        skill_name=skill_name,
        skill_category=skill_category,
        total_attempts=total_attempts,
        success_rate=success_rate,
        traces=traces,
        duration_baseline=duration_baseline,
    )
    if strategy is None:
        return False
    return await persist_strategy(
        db_path=db_path, skill_id=skill_id, strategy=strategy,
        expected_revision=int(snapshot[0]),
        covered_trace_ids=[str(trace["trace_id"]) for trace in traces],
    )


async def get_duration_baseline(*, db_path: str, skill_id: str) -> Dict[str, float]:
    """Return avg and p95 execution times for a skill."""
    async with sqlite_connection_async(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"""
            SELECT skills.avg_execution_time_ms, skills.p95_execution_time_ms
            FROM procedural_skills AS skills
            WHERE skills.skill_id = ? AND {active_skill_predicate("skills")}
            """,
            (skill_id,),
        ) as cursor:
            row = await cursor.fetchone()
    if row is None:
        return {}
    return duration_baseline_from_row(row)


async def enrich_with_recovery(
    *,
    db_path: str,
    traces: List[Dict[str, Any]],
    current_skill_id: str,
) -> None:
    """Annotate failure traces with same-turn successful recovery by other tools."""
    unique_turn_ids = failure_turn_ids(traces)
    if not unique_turn_ids:
        return

    placeholders = ", ".join("?" for _ in unique_turn_ids)
    async with sqlite_connection_async(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"""
            SELECT t.turn_id, t.created_at, t.output_summary,
                   s.skill_name
            FROM {EXECUTION_TRACES_TABLE} t
            JOIN procedural_skills s ON t.skill_id = s.skill_id
            WHERE t.turn_id IN ({placeholders})
              AND t.skill_id != ?
              AND t.success = 1
              AND {active_skill_predicate("s")}
            ORDER BY t.turn_id, t.created_at ASC
            """,
            (*unique_turn_ids, current_skill_id),
        ) as cursor:
            rows = await cursor.fetchall()

    apply_recovery_annotations(traces, recovery_map_from_rows(rows))


async def persist_strategy(
    *,
    db_path: str,
    skill_id: str,
    strategy: ExtractedStrategy,
    expected_revision: int | None = None,
    covered_trace_ids: list[str] | None = None,
) -> bool:
    """Publish one strategy and mark only its sampled traces as consumed."""
    now = time.time()
    strategy_json = strategy.to_json()
    async with sqlite_connection_async(db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("BEGIN IMMEDIATE")
        async with db.execute(
            f"SELECT * FROM procedural_skills AS skills WHERE skill_id = ? AND {active_skill_predicate('skills')}",
            (skill_id,),
        ) as cursor:
            current = await cursor.fetchone()
        if current is None or (expected_revision is not None and int(current["strategy_revision"]) != expected_revision):
            await db.rollback()
            return False
        trace_ids = list(dict.fromkeys(covered_trace_ids or []))
        if trace_ids:
            await db.execute(
                f"UPDATE {EXECUTION_TRACES_TABLE} SET strategy_processed_at = ? WHERE skill_id = ? AND strategy_processed_at IS NULL AND trace_id IN (SELECT value FROM json_each(?))",
                (now, skill_id, json.dumps(trace_ids)),
            )
        await db.execute(
            f"""
            UPDATE procedural_skills SET optimized_prompt = ?, context_affinity = ?,
                optimization_score = ?, strategy_revision = strategy_revision + 1,
                embedding_status = CASE WHEN embedding_status = 'disabled' THEN 'disabled' ELSE 'pending' END,
                pending_trace_count = (SELECT COUNT(*) FROM {EXECUTION_TRACES_TABLE} WHERE skill_id = ? AND strategy_processed_at IS NULL),
                updated_at = ? WHERE skill_id = ?
            """,
            (strategy_json, json.dumps(strategy.context_preferences, ensure_ascii=False), strategy.confidence, skill_id, now, skill_id),
        )
        await sync_skill_fts(
            db, skill_id=skill_id, skill_name=str(current["skill_name"]),
            skill_category=str(current["skill_category"]), optimized_prompt=strategy_json,
            replace_existing=True,
        )
        await db.commit()
    logger.info("L4 strategy persisted for skill %s (confidence=%.2f)", skill_id, strategy.confidence)
    return True
