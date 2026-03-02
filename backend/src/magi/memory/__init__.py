"""Unified memory system entrypoints (L1-L5)."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .l2_event_relations import EventRelation, EventRelationStore
from .l3_semantic_embeddings import (
    EmbeddingBackend,
    EventEmbedding,
    HybrideventSearch,
    LocalEmbeddingBackend,
    RemoteEmbeddingBackend,
    create_embedding_store,
    eventEmbeddingStore,
)
from .l4_summaries import AutoSummarizer, EventSummary, SummaryStore
from .l5_capabilities import Capability, CapabilityMemory
from .other_memory import OtherMemory
from .raw_event_store import RawEventStore
from .self_memory import SelfMemory
from .adaptive_profile_updater import AdaptiveProfileUpdater

logger = logging.getLogger(__name__)


class UnifiedMemoryStore:
    """Coordinates the L1-L5 memory layers with consistent interfaces."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        persist_dir: Optional[str] = None,
        enable_embeddings: bool = True,
        enable_summaries: bool = True,
        enable_capabilities: bool = True,
        embedding_config: Optional[Dict[str, Any]] = None,
        llm_adapter: Any = None,
    ):
        from ..utils.runtime import get_runtime_paths

        runtime_paths = get_runtime_paths()
        events_db = str((Path(db_path).expanduser() if db_path else runtime_paths.events_db_path))
        memories_dir = Path(persist_dir).expanduser() if persist_dir else runtime_paths.memories_dir
        memories_dir.mkdir(parents=True, exist_ok=True)

        emb_config = embedding_config or {}

        self.l1_raw = RawEventStore(db_path=events_db, media_dir=str(runtime_paths.data_dir / "events"))
        self.l2_relations = EventRelationStore(persist_path=str(memories_dir / "relations.pkl"))

        self.l3_embeddings: Optional[eventEmbeddingStore] = None
        self.l3_hybrid_search: Optional[HybrideventSearch] = None
        if enable_embeddings:
            self.l3_embeddings = create_embedding_store(
                backend=str(emb_config.get("backend", "sqlite_vec")),
                llm_adapter=llm_adapter,
                local_model=str(emb_config.get("local_model", "all-MiniLM-L6-v2")),
                local_dimension=int(emb_config.get("local_dimension", 384)),
                remote_model=str(emb_config.get("openai_model", "text-embedding-3-small")),
                remote_dimension=int(emb_config.get("remote_dimension", 1536)),
                persist_path=str(memories_dir / "embeddings.db"),
            )
            self.l3_hybrid_search = HybrideventSearch(self.l3_embeddings)

        self.l4_summaries: Optional[SummaryStore] = None
        self.l4_auto_summarizer: Optional[AutoSummarizer] = None
        if enable_summaries:
            self.l4_summaries = SummaryStore(persist_path=str(memories_dir / "summaries.db"))
            self.l4_auto_summarizer = AutoSummarizer(self.l4_summaries)

        self.l5_capabilities: Optional[CapabilityMemory] = None
        if enable_capabilities:
            self.l5_capabilities = CapabilityMemory(persist_path=str(memories_dir / "capabilities.db"))

        self._initialized = False
        self._write_lock = asyncio.Lock()

    async def initialize(self) -> None:
        if self._initialized:
            return

        await self.l1_raw.init()
        if self.l3_embeddings:
            await self.l3_embeddings.initialize()
        if self.l4_summaries:
            await self.l4_summaries.initialize()

        self._initialized = True
        logger.info("Unified memory store initialized")

    async def store_event(
        self,
        event: Dict[str, Any],
        extract_relations: bool = True,
        generate_embeddings: bool = True,
    ) -> str:
        """Stores an event into L1 and propagates it to enabled layers."""
        return await self.add_event(
            event=event,
            extract_relations=extract_relations,
            generate_embeddings=generate_embeddings,
        )

    async def add_event(
        self,
        event: Dict[str, Any],
        extract_relations: bool = True,
        generate_embeddings: bool = True,
    ) -> str:
        event_id = str(event.get("id") or event.get("event_id") or uuid.uuid4())
        timestamp = float(event.get("timestamp", time.time()))
        payload = {
            "id": event_id,
            "type": str(event.get("type", "unknown")),
            "data": event.get("data", {}),
            "timestamp": timestamp,
            "source": str(event.get("source", "memory")),
            "level": int(event.get("level", 1)),
            "correlation_id": event.get("correlation_id") or event_id,
            "metadata": dict(event.get("metadata", {})),
        }

        from ..events.events import Event, EventLevel

        async with self._write_lock:
            l1_event_id: Optional[str] = None
            try:
                l1_event_id = await self.l1_raw.store(
                    Event(
                        type=payload["type"],
                        data=payload["data"],
                        timestamp=payload["timestamp"],
                        source=payload["source"],
                        level=EventLevel(payload["level"]),
                        correlation_id=payload["correlation_id"],
                        metadata=payload["metadata"],
                    )
                )

                if extract_relations:
                    self.l2_relations.add_event(event_id, payload)

                if generate_embeddings and self.l3_embeddings:
                    text = self._extract_text_from_event(payload)
                    if text:
                        await self.l3_embeddings.add_event(
                            event_id=event_id,
                            text=text,
                            metadata={"event_type": payload["type"]},
                        )

                if self.l4_summaries:
                    self.l4_summaries.add_event(payload)

                if self.l5_capabilities and payload["type"] == "TaskCompleted":
                    self._record_task_attempt(payload)

                if self.l2_relations.persist_path:
                    self.l2_relations._save_to_disk()

            except Exception:
                if l1_event_id:
                    await self.l1_raw.delete_event(l1_event_id)
                raise

        return event_id

    async def search(self, query: str, search_type: str = "hybrid", limit: int = 10) -> List[Dict[str, Any]]:
        if search_type == "hybrid" and self.l3_hybrid_search:
            return await self.l3_hybrid_search.search(query, top_k=limit)
        if search_type == "semantic" and self.l3_embeddings:
            return await self.l3_embeddings.similarity_search(query, top_k=limit)
        if search_type == "keyword" and self.l3_hybrid_search:
            return await self.l3_hybrid_search._keyword_search(query, top_k=limit)
        if search_type == "relation":
            results: List[Dict[str, Any]] = []
            query_text = query.lower().strip()
            for event_id, payload in self.l2_relations._events.items():
                if query_text in str(payload).lower():
                    results.append({"event_id": event_id, "data": payload})
            return results[:limit]
        return []

    def get_related_events(self, event_id: str, max_depth: int = 2) -> Dict[int, List[Dict[str, Any]]]:
        return self.l2_relations.get_related_events(event_id=event_id, max_depth=max_depth)

    def get_summary(self, period_type: str = "day", period_key: Optional[str] = None) -> Optional[EventSummary]:
        if not self.l4_summaries:
            return None
        return self.l4_summaries.get_summary(period_type, period_key)

    def generate_summary(
        self,
        period_type: str = "day",
        period_key: Optional[str] = None,
        force: bool = False,
    ) -> Optional[EventSummary]:
        if not self.l4_summaries:
            return None
        return self.l4_summaries.generate_summary(period_type, period_key, force)

    def find_capability(self, context: Dict[str, Any], threshold: float = 0.5) -> Optional[Capability]:
        if not self.l5_capabilities:
            return None
        return self.l5_capabilities.find_capability(context, threshold)

    def get_statistics(self) -> Dict[str, Any]:
        stats: Dict[str, Any] = {
            "l1_raw": {"db_path": self.l1_raw.db_path},
            "l2_relations": self.l2_relations.get_statistics(),
        }
        if self.l3_embeddings:
            stats["l3_embeddings"] = self.l3_embeddings.get_statistics()
        if self.l4_summaries:
            stats["l4_summaries"] = self.l4_summaries.get_statistics()
        if self.l5_capabilities:
            stats["l5_capabilities"] = self.l5_capabilities.get_statistics()
        return stats

    async def cleanup_old_data(self, older_than_days: int = 30) -> Dict[str, int]:
        removed_l2 = self.l2_relations.clear_old_relations(older_than_days)
        removed_l3 = self.l3_embeddings.clear_old_embeddings(older_than_days) if self.l3_embeddings else 0
        removed_l4 = self.l4_summaries.clear_old_summaries(max(1, older_than_days // 30)) if self.l4_summaries else 0

        return {
            "l2_removed": removed_l2,
            "l3_removed": removed_l3,
            "l4_removed": removed_l4,
        }

    async def run_maintenance(self, retention_days: int = 30) -> Dict[str, int]:
        """Executes retention/cleanup jobs for all layers."""
        l1_removed = 0
        # L1 archive is currently represented as export + delete policy done by external scheduler.
        # The store keeps full history by default unless explicitly cleaned.

        layer_cleanup = await self.cleanup_old_data(older_than_days=retention_days)

        return {
            "l1_removed": l1_removed,
            **layer_cleanup,
        }

    def _extract_text_from_event(self, event: Dict[str, Any]) -> str:
        parts: List[str] = []
        if event.get("type"):
            parts.append(str(event["type"]))

        data = event.get("data")
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, str):
                    parts.append(value)
                elif isinstance(value, (int, float, bool)):
                    parts.append(f"{key}:{value}")
        elif data is not None:
            parts.append(str(data))

        return " ".join(parts).strip()

    def _record_task_attempt(self, event: Dict[str, Any]) -> None:
        if not self.l5_capabilities:
            return

        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        self.l5_capabilities.record_attempt(
            task_id=str(data.get("task_id", "unknown")),
            context=event.get("metadata", {}),
            action=data.get("action", {}),
            success=bool(data.get("success", True)),
            duration=float(data.get("duration", 0.0)),
            error=data.get("error"),
        )


__all__ = [
    "SelfMemory",
    "OtherMemory",
    "RawEventStore",
    "EventRelationStore",
    "EventRelation",
    "eventEmbeddingStore",
    "EventEmbedding",
    "HybrideventSearch",
    "EmbeddingBackend",
    "LocalEmbeddingBackend",
    "RemoteEmbeddingBackend",
    "create_embedding_store",
    "SummaryStore",
    "EventSummary",
    "AutoSummarizer",
    "CapabilityMemory",
    "Capability",
    "AdaptiveProfileUpdater",
    "UnifiedMemoryStore",
]
