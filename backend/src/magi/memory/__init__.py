"""Unified entrypoints for the rewritten L0-L4 memory system."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

from ..events.events import Event, EventLevel
from .adaptive_profile_updater import AdaptiveProfileUpdater
from .event_contracts import MemoryEvent, normalize_runtime_event
from .l0_working_memory import L0WorkingMemoryStore
from .l1_event_store import L1EventStore
from .l2_cognition_store import L2CognitionStore
from .l3_summary_store import L3SummaryStore
from .l4_procedural_memory import L4ProceduralMemoryStore
from .other_memory import OtherMemory
from .prompt_context_assembler import PromptContextAssembler, PromptContextRenderer
from .prompt_context_schema import (
    IdentityConstraintContext,
    ProfileMemoryContext,
    PromptAssemblyContext,
    RetrievalMemoryContext,
    RuntimeSystemContext,
    SelfMemoryContext,
    ToolCatalogContext,
)
from .self_memory import SelfMemory

logger = logging.getLogger(__name__)


class UnifiedMemoryStore:
    """Coordinates the lifecycle-based L0-L4 memory stores."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        persist_dir: Optional[str] = None,
        *,
        enable_l0: bool = True,
        enable_l1: bool = True,
        enable_l2: bool = True,
        enable_l3: bool = True,
        enable_l4: bool = True,
        l0_checkpoint_interval_seconds: int = 30,
        session_timeout_seconds: int = 3600,
    ) -> None:
        from ..utils.runtime import get_runtime_paths

        runtime_paths = get_runtime_paths()
        events_db = str((Path(db_path).expanduser() if db_path else runtime_paths.events_db_path))
        memories_dir = Path(persist_dir).expanduser() if persist_dir else runtime_paths.memories_dir
        memories_dir.mkdir(parents=True, exist_ok=True)

        self.l0: Optional[L0WorkingMemoryStore] = None
        self.l1: Optional[L1EventStore] = None
        self.l2: Optional[L2CognitionStore] = None
        self.l3: Optional[L3SummaryStore] = None
        self.l4: Optional[L4ProceduralMemoryStore] = None

        if enable_l0:
            self.l0 = L0WorkingMemoryStore(
                checkpoint_db_path=str(memories_dir / "l0_working_context.db"),
                checkpoint_interval_seconds=l0_checkpoint_interval_seconds,
                session_timeout_seconds=session_timeout_seconds,
                restore_on_restart=True,
            )
        if enable_l1:
            self.l1 = L1EventStore(db_path=events_db)
        if enable_l2:
            self.l2 = L2CognitionStore(db_path=str(memories_dir / "l2_cognition.db"))
        if enable_l3:
            self.l3 = L3SummaryStore(db_path=str(memories_dir / "l3_reflections.db"))
        if enable_l4:
            self.l4 = L4ProceduralMemoryStore(db_path=str(memories_dir / "l4_procedural.db"))

        self._initialized = False
        self._write_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize enabled stores."""
        if self._initialized:
            return

        for store in (self.l0, self.l1, self.l2, self.l3, self.l4):
            if store is None:
                continue
            await store.initialize()

        self._initialized = True
        logger.info("Unified memory store initialized")

    async def ingest_event(self, event: Dict[str, Any] | Event | MemoryEvent) -> Dict[str, Any]:
        """Ingest an event through the new L0-L4 pipeline."""
        memory_event = self._normalize_event(event)
        l2_result = {"relation_count": 0, "assertion_count": 0}
        l4_skill_id: Optional[str] = None

        async with self._write_lock:
            if self.l0 is not None:
                await self.l0.capture_event(memory_event)

            if self.l1 is not None and memory_event.ingest_target != "l0_only":
                await self.l1.store(memory_event)
                if self.l2 is not None:
                    l2_result = await self.l2.apply_memory_event(memory_event)
                if self.l4 is not None:
                    l4_skill_id = await self.l4.record_memory_event(memory_event)

        return {
            "event_id": memory_event.event_id,
            "ingest_target": memory_event.ingest_target,
            "l1_written": bool(self.l1 is not None and memory_event.ingest_target != "l0_only"),
            "l2_relation_count": int(l2_result["relation_count"]),
            "l2_assertion_count": int(l2_result["assertion_count"]),
            "l4_skill_id": l4_skill_id,
        }

    async def store_event(self, event: Dict[str, Any] | Event | MemoryEvent) -> str:
        """Compatibility helper for callers that only need the event id."""
        result = await self.ingest_event(event)
        return str(result["event_id"])

    async def add_event(self, event: Dict[str, Any] | Event | MemoryEvent) -> str:
        """Store an event in the unified pipeline."""
        return await self.store_event(event)

    async def generate_summary(
        self,
        period_type: str = "day",
        *,
        period_start: Optional[float] = None,
        period_end: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Generate a temporal L3 summary for a time window."""
        if self.l1 is None or self.l3 is None:
            return None

        now = time.time()
        if period_end is None:
            period_end = now
        if period_start is None:
            period_start = period_end - self._period_seconds(period_type)
        return await self.l3.generate_temporal_summary(
            l1_store=self.l1,
            summary_category=period_type,
            period_start=period_start,
            period_end=period_end,
        )

    async def search(self, query: str, *, search_type: str = "detail", limit: int = 10) -> list[dict[str, Any]]:
        """Perform a simple layer-aware search without the retrieval router."""
        if search_type in {"detail", "hybrid", "keyword"} and self.l1 is not None:
            events = await self.l1.query_events(limit=200)
            return [event for event in events if query.lower() in event["raw_content"].lower()][:limit]
        if search_type == "summary" and self.l3 is not None:
            return await self.l3.search_summaries(query=query, limit=limit)
        if search_type in {"experience", "strategy"} and self.l4 is not None:
            return await self.l4.query_strategies(query=query, limit=limit)
        if search_type == "graph" and self.l2 is not None:
            return await self.l2.get_relationships(limit=limit)
        return []

    async def get_statistics(self) -> Dict[str, Any]:
        """Return per-layer statistics."""
        stats: Dict[str, Any] = {}
        if self.l0 is not None:
            stats["l0"] = {"checkpoint_db_path": self.l0.checkpoint_db_path}
        if self.l1 is not None:
            stats["l1"] = {
                "db_path": self.l1.db_path,
                "event_count": await self.l1.count_events(),
            }
        if self.l2 is not None:
            stats["l2"] = self.l2.get_statistics()
        if self.l3 is not None:
            stats["l3"] = self.l3.get_statistics() if hasattr(self.l3, "get_statistics") else {"db_path": self.l3.db_path}
        if self.l4 is not None:
            stats["l4"] = self.l4.get_statistics()
        return stats

    async def cleanup_old_data(self, older_than_days: int = 30) -> Dict[str, int]:
        """Run lightweight cleanup jobs."""
        removed: Dict[str, int] = {"expired_sessions": 0, "deleted_events": 0, "deleted_summaries": 0}
        if self.l0 is not None:
            removed["expired_sessions"] = len(await self.l0.expire_idle_sessions())
            await self.l0.checkpoint_all()
        _ = older_than_days
        return removed

    async def run_maintenance(self, retention_days: int = 30) -> Dict[str, int]:
        """Run periodic maintenance."""
        return await self.cleanup_old_data(older_than_days=retention_days)

    async def upsert_user_graph_edge(
        self,
        *,
        subject_id: str,
        subject_type: str,
        predicate: str,
        object_id: str,
        object_type: str,
        evidence_event_ids: list[str],
        confidence: float,
        observed_at: float,
        source_type: str,
        subject_attributes: Optional[Dict[str, Any]] = None,
        object_attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write a knowledge-graph edge through the unified cognition store."""
        _ = subject_attributes
        _ = object_attributes
        if self.l2 is None:
            return
        await self.l2.upsert_knowledge_edge(
            subject_id=subject_id,
            subject_type=subject_type,
            predicate=predicate,
            object_id=object_id,
            object_type=object_type,
            evidence_event_ids=evidence_event_ids,
            confidence=confidence,
            observed_at=observed_at,
            source_type=source_type,
        )

    def _normalize_event(self, event: Dict[str, Any] | Event | MemoryEvent) -> MemoryEvent:
        if isinstance(event, MemoryEvent):
            return event
        if isinstance(event, Event):
            return normalize_runtime_event(event)

        payload = dict(event)
        raw_event = Event(
            type=str(payload.get("type", "unknown")),
            data=payload.get("data", {}),
            timestamp=float(payload.get("timestamp", time.time())),
            source=str(payload.get("source", "memory")),
            level=EventLevel(int(payload.get("level", EventLevel.INFO.value))),
            correlation_id=payload.get("correlation_id"),
            metadata=dict(payload.get("metadata", {})),
        )
        return normalize_runtime_event(raw_event, event_id=payload.get("id") or payload.get("event_id"))

    def _period_seconds(self, period_type: str) -> int:
        return {
            "hour": 60 * 60,
            "day": 24 * 60 * 60,
            "week": 7 * 24 * 60 * 60,
            "month": 30 * 24 * 60 * 60,
        }.get(period_type, 24 * 60 * 60)


__all__ = [
    "AdaptiveProfileUpdater",
    "IdentityConstraintContext",
    "OtherMemory",
    "ProfileMemoryContext",
    "PromptAssemblyContext",
    "PromptContextAssembler",
    "PromptContextRenderer",
    "RetrievalMemoryContext",
    "RuntimeSystemContext",
    "SelfMemory",
    "SelfMemoryContext",
    "ToolCatalogContext",
    "UnifiedMemoryStore",
]
