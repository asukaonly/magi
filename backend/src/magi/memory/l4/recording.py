"""Event recording and strategy-learning operations for L4 procedural memory."""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from ..event_contracts import MemoryEvent
from .learning.updates import (
    build_new_skill_record_state,
    build_updated_skill_record_state,
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
        skill_name: str = identity["skill_name"]
        skill_category: str = identity["skill_category"]
        skill_type: str = identity["skill_type"]
        success: bool = identity["success"]
        duration_ms: float = identity["duration_ms"]
        optimized_prompt: Optional[str] = identity["optimized_prompt"]
        now = time.time()

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM procedural_skills WHERE skill_name = ? AND skill_category = ?",
                (skill_name, skill_category),
            ) as cursor:
                existing = await cursor.fetchone()

            if existing is None:
                skill_id = f"skill_{uuid.uuid4().hex}"
                record_state = build_new_skill_record_state(
                    success=success,
                    duration_ms=duration_ms,
                    event_timestamp=float(event.timestamp),
                    breaker_failure_threshold=self.breaker_failure_threshold,
                )
                await insert_new_skill_record(
                    db,
                    skill_id=skill_id,
                    skill_name=skill_name,
                    skill_category=skill_category,
                    skill_type=skill_type,
                    record_state=record_state,
                    optimized_prompt=optimized_prompt,
                    event_id=event.event_id,
                    event_timestamp=float(event.timestamp),
                    now=now,
                )
                await db.commit()
                await sync_skill_fts(
                    db,
                    skill_id=skill_id,
                    skill_name=skill_name,
                    skill_category=skill_category,
                    optimized_prompt=optimized_prompt,
                    replace_existing=False,
                )
                await db.commit()
                await self._schedule_skill_embedding(
                    skill_id=skill_id,
                    skill_name=skill_name,
                    skill_category=skill_category,
                    optimized_prompt=optimized_prompt,
                )
                await insert_execution_trace(
                    db_path=self.db_path,
                    skill_id=skill_id,
                    event=event,
                    identity=identity,
                )
                return skill_id

            record_state = build_updated_skill_record_state(
                existing=existing,
                success=success,
                duration_ms=duration_ms,
                event_id=event.event_id,
                event_timestamp=float(event.timestamp),
                breaker_failure_threshold=self.breaker_failure_threshold,
                breaker_recovery_successes=self.breaker_recovery_successes,
            )

            skill_id = str(existing["skill_id"])
            await update_skill_record(
                db,
                skill_id=skill_id,
                record_state=record_state,
                optimized_prompt=optimized_prompt,
                event_timestamp=float(event.timestamp),
                now=now,
            )
            await db.commit()
            await sync_skill_fts(
                db,
                skill_id=skill_id,
                skill_name=skill_name,
                skill_category=skill_category,
                optimized_prompt=optimized_prompt or existing["optimized_prompt"],
                replace_existing=True,
            )
            await db.commit()
            await self._schedule_skill_embedding(
                skill_id=skill_id,
                skill_name=skill_name,
                skill_category=skill_category,
                optimized_prompt=optimized_prompt or existing["optimized_prompt"],
            )
            await insert_execution_trace(
                db_path=self.db_path,
                skill_id=skill_id,
                event=event,
                identity=identity,
            )
            adaptive_threshold = self._adaptive_extraction_threshold(
                self._strategy_extraction_threshold,
                record_state.total_attempts,
            )
            if record_state.pending_trace_count >= adaptive_threshold or record_state.breaker_just_opened:
                await self._maybe_extract_strategy(
                    skill_id=skill_id,
                    skill_name=skill_name,
                    skill_category=skill_category,
                    total_attempts=record_state.total_attempts,
                    success_rate=record_state.success_rate,
                )
            return skill_id

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
