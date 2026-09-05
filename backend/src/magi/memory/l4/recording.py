"""Event recording and strategy-learning operations for L4 procedural memory."""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from ..event_contracts import MemoryEvent
from ..source_event_governance import govern_source_events_by_time_range
from .learning.updates import (
    UpdatedSkillRecordState,
    build_new_skill_record_state,
    build_updated_skill_record_state,
)
from .source_event_governance import (
    active_skill_predicate,
    link_skill_source_event,
    skill_accepts_source_event,
)
from .storage.records import (
    insert_new_skill_record,
    sync_skill_fts,
    update_skill_record,
)
from .storage.serialization import adaptive_extraction_threshold, extract_skill_identity
from .strategy_extraction import ExtractedStrategy, L4StrategyExtractor
from .strategy_operations import (
    enrich_with_recovery,
    get_duration_baseline,
    maybe_extract_strategy,
    persist_strategy,
    stratified_traces,
)
from .traces.store import insert_execution_trace
from .table_names import SKILL_EVENT_LINKS_TABLE


class L4ProceduralRecordingMixin:
    """Record normalized memory events into procedural skill state."""

    db_path: str
    breaker_failure_threshold: int
    breaker_recovery_successes: int
    _strategy_extraction_threshold: int
    _strategy_extractor: L4StrategyExtractor | None

    async def initialize(self) -> None:
        raise NotImplementedError

    async def _schedule_skill_embedding(
        self,
        *,
        skill_id: str,
        skill_name: str,
        skill_category: str,
        optimized_prompt: Optional[str],
    ) -> None:
        raise NotImplementedError

    async def record_memory_event(self, event: MemoryEvent) -> Optional[str]:
        """Update procedural memory based on a normalized event."""
        identity = self._extract_skill_identity(event)
        if identity is None:
            return None

        await self.initialize()
        await self.retire_governed_skill_identity(
            skill_name=str(identity["skill_name"]),
            skill_category=str(identity["skill_category"]),
        )
        now = time.time()

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                time_range_decision = await govern_source_events_by_time_range(
                    db,
                    event_ids=(event.event_id, event.turn_id),
                    observed_from=float(event.timestamp),
                )
                if time_range_decision.blocks_derivations:
                    await db.commit()
                    return None
                if not await skill_accepts_source_event(
                    db,
                    event_id=event.event_id,
                    turn_id=event.turn_id,
                ):
                    await db.rollback()
                    return None
                existing = await self._fetch_skill_record(
                    db,
                    skill_name=identity["skill_name"],
                    skill_category=identity["skill_category"],
                )

                if existing is not None:
                    async with db.execute(
                        f"SELECT 1 FROM {SKILL_EVENT_LINKS_TABLE} WHERE skill_id = ? AND event_id = ?",
                        (existing["skill_id"], event.event_id),
                    ) as cursor:
                        duplicate = await cursor.fetchone()
                    if duplicate is not None:
                        await db.commit()
                        return None if existing["deleted_at"] is not None else str(existing["skill_id"])
                if existing is None:
                    return await self._record_new_skill_event(
                        db,
                        event=event,
                        identity=identity,
                        now=now,
                    )

                return await self._record_existing_skill_event(
                    db,
                    existing=existing,
                    event=event,
                    identity=identity,
                    now=now,
                )
            except BaseException:
                await db.rollback()
                raise

    async def _fetch_skill_record(
        self,
        db: aiosqlite.Connection,
        *,
        skill_name: str,
        skill_category: str,
    ) -> aiosqlite.Row | None:
        async with db.execute(
            f"""
            SELECT *
            FROM procedural_skills AS skills
            WHERE skills.skill_name = ? AND skills.skill_category = ?
              AND {active_skill_predicate("skills", include_inactive=True)}
            """,
            (skill_name, skill_category),
        ) as cursor:
            return await cursor.fetchone()

    async def _record_new_skill_event(
        self,
        db: aiosqlite.Connection,
        *,
        event: MemoryEvent,
        identity: Dict[str, Any],
        now: float,
    ) -> str:
        skill_id = f"skill_{uuid.uuid4().hex}"
        skill_name: str = identity["skill_name"]
        skill_category: str = identity["skill_category"]
        optimized_prompt: Optional[str] = identity["optimized_prompt"]
        record_state = build_new_skill_record_state(
            success=identity["success"],
            duration_ms=identity["duration_ms"],
            event_timestamp=float(event.timestamp),
            breaker_failure_threshold=self.breaker_failure_threshold,
        )
        await insert_new_skill_record(
            db,
            skill_id=skill_id,
            skill_name=skill_name,
            skill_category=skill_category,
            skill_type=identity["skill_type"],
            record_state=record_state,
            optimized_prompt=optimized_prompt,
            event_id=event.event_id,
            event_timestamp=float(event.timestamp),
            now=now,
        )
        await link_skill_source_event(
            db,
            skill_id=skill_id,
            event_id=event.event_id,
            created_at=now,
        )
        if event.turn_id:
            await link_skill_source_event(
                db,
                skill_id=skill_id,
                event_id=event.turn_id,
                created_at=now,
            )
        await insert_execution_trace(db, skill_id=skill_id, event=event, identity=identity)
        await db.commit()
        await self._sync_skill_indexes(
            db,
            skill_id=skill_id,
            skill_name=skill_name,
            skill_category=skill_category,
            optimized_prompt=optimized_prompt,
            replace_existing=False,
        )
        return skill_id

    async def _record_existing_skill_event(
        self,
        db: aiosqlite.Connection,
        *,
        existing: aiosqlite.Row,
        event: MemoryEvent,
        identity: Dict[str, Any],
        now: float,
    ) -> str:
        record_state = build_updated_skill_record_state(
            existing=existing,
            success=identity["success"],
            duration_ms=identity["duration_ms"],
            event_id=event.event_id,
            event_timestamp=float(event.timestamp),
            breaker_failure_threshold=self.breaker_failure_threshold,
            breaker_recovery_successes=self.breaker_recovery_successes,
        )

        skill_id = str(existing["skill_id"])
        skill_name: str = identity["skill_name"]
        skill_category: str = identity["skill_category"]
        optimized_prompt: Optional[str] = identity["optimized_prompt"]
        effective_prompt = optimized_prompt or existing["optimized_prompt"]
        await update_skill_record(
            db,
            skill_id=skill_id,
            record_state=record_state,
            optimized_prompt=optimized_prompt,
            event_timestamp=float(event.timestamp),
            now=now,
        )
        await link_skill_source_event(
            db,
            skill_id=skill_id,
            event_id=event.event_id,
            created_at=now,
        )
        if event.turn_id:
            await link_skill_source_event(
                db,
                skill_id=skill_id,
                event_id=event.turn_id,
                created_at=now,
            )
        await insert_execution_trace(db, skill_id=skill_id, event=event, identity=identity)
        await db.commit()
        await self._sync_skill_indexes(
            db,
            skill_id=skill_id,
            skill_name=skill_name,
            skill_category=skill_category,
            optimized_prompt=effective_prompt,
            replace_existing=True,
        )
        await self._maybe_extract_updated_strategy(
            skill_id=skill_id,
            skill_name=skill_name,
            skill_category=skill_category,
            record_state=record_state,
        )
        return skill_id

    async def _sync_skill_indexes(
        self,
        db: aiosqlite.Connection,
        *,
        skill_id: str,
        skill_name: str,
        skill_category: str,
        optimized_prompt: Optional[str],
        replace_existing: bool,
    ) -> None:
        await db.execute("BEGIN IMMEDIATE")
        await sync_skill_fts(
            db,
            skill_id=skill_id,
            skill_name=skill_name,
            skill_category=skill_category,
            optimized_prompt=optimized_prompt,
            replace_existing=replace_existing,
        )
        await db.commit()
        await self._schedule_skill_embedding(
            skill_id=skill_id,
            skill_name=skill_name,
            skill_category=skill_category,
            optimized_prompt=optimized_prompt,
        )

    async def _maybe_extract_updated_strategy(
        self,
        *,
        skill_id: str,
        skill_name: str,
        skill_category: str,
        record_state: UpdatedSkillRecordState,
    ) -> None:
        adaptive_threshold = self._adaptive_extraction_threshold(
            self._strategy_extraction_threshold,
            record_state.total_attempts,
        )
        if (
            record_state.pending_trace_count < adaptive_threshold
            and not record_state.breaker_just_opened
        ):
            return
        await self._maybe_extract_strategy(
            skill_id=skill_id,
            skill_name=skill_name,
            skill_category=skill_category,
            total_attempts=record_state.total_attempts,
            success_rate=record_state.success_rate,
        )

    @staticmethod
    def _adaptive_extraction_threshold(
        base_threshold: int,
        total_attempts: int,
    ) -> int:
        """Scale extraction threshold with usage volume."""
        return adaptive_extraction_threshold(base_threshold, total_attempts)

    async def _stratified_traces(
        self,
        skill_id: str,
        *,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Return a diverse sample of traces for strategy extraction."""
        await self.initialize()
        return await stratified_traces(db_path=self.db_path, skill_id=skill_id, limit=limit)

    def _extract_skill_identity(
        self,
        event: MemoryEvent,
    ) -> Optional[Dict[str, Any]]:
        return extract_skill_identity(event)

    async def _maybe_extract_strategy(
        self,
        *,
        skill_id: str,
        skill_name: str,
        skill_category: str,
        total_attempts: int,
        success_rate: float,
    ) -> None:
        """Conditionally run LLM strategy extraction and persist the result."""
        await maybe_extract_strategy(
            db_path=self.db_path,
            strategy_extractor=self._strategy_extractor,
            skill_id=skill_id,
            skill_name=skill_name,
            skill_category=skill_category,
            total_attempts=total_attempts,
            success_rate=success_rate,
        )

    async def _get_duration_baseline(self, skill_id: str) -> Dict[str, float]:
        """Return avg and p95 execution times for a skill."""
        return await get_duration_baseline(db_path=self.db_path, skill_id=skill_id)

    async def _enrich_with_recovery(
        self,
        traces: List[Dict[str, Any]],
        current_skill_id: str,
    ) -> None:
        """Annotate failure traces with same-turn successful recovery by other tools."""
        await enrich_with_recovery(
            db_path=self.db_path,
            traces=traces,
            current_skill_id=current_skill_id,
        )

    async def _persist_strategy(
        self,
        *,
        skill_id: str,
        strategy: ExtractedStrategy,
    ) -> None:
        """Write extracted strategy to the procedural_skills row and reset pending count."""
        await persist_strategy(db_path=self.db_path, skill_id=skill_id, strategy=strategy)


__all__ = ["L4ProceduralRecordingMixin"]
