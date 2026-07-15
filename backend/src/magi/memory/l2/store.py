"""Unified L2 cognition store for graph facts and defensive ToM assertions."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Mapping

from ...core.sqlite import sqlite_connection_async
from ...core.logger import get_logger
from ..event_contracts import MemoryEvent
from .graph_conflicts import (
    GraphConflictRule,
    build_exclusive_group_index,
    build_graph_conflict_matrix,
)
from .models import L2KnowledgeEdgeWrite, L2TomAssertionWrite
from .corrections.repository import (
    DEFAULT_DERIVATION_MAX_ATTEMPTS,
    DEFAULT_DERIVATION_STALE_RUNNING_SECONDS,
    MemoryCorrectionRepository,
)
from .projection.queue import ProjectionJobQueue
from .assertions.contradictions import L2StoreContradictionMixin
from .assertions.feedback import L2StoreFeedbackMixin
from .assertions.reconcile import L2StoreReconcileMixin
from .assertions.snapshots import L2StoreSnapshotMixin
from .assertions.write import L2StoreAssertionMixin
from .entities.facets import L2EntityFacetStoreMixin
from .episodes.store import L2EpisodeStoreMixin
from .experiences.store import L2ExperienceStoreMixin
from .extraction.candidates import L2StoreCandidateExtractionMixin
from .governance.forgetting import L2StoreForgettingMixin
from .graph.conflicts import L2StoreGraphConflictMixin
from .graph.edge_embeddings import L2StoreEdgeEmbeddingMixin
from .graph.fact_kind import L2StoreFactKindMixin
from .graph.writes import L2StoreGraphWriteMixin
from .projection.jobs import L2ProjectionJobStoreMixin
from .retrieval.queries import L2StoreQueryMixin
from .storage.rows import L2StoreRowMappingMixin

logger = get_logger(__name__)


class L2CognitionStore(
    L2EntityFacetStoreMixin,
    L2EpisodeStoreMixin,
    L2ExperienceStoreMixin,
    L2StoreGraphConflictMixin,
    L2ProjectionJobStoreMixin,
    L2StoreReconcileMixin,
    L2StoreRowMappingMixin,
    L2StoreFactKindMixin,
    L2StoreCandidateExtractionMixin,
    L2StoreContradictionMixin,
    L2StoreSnapshotMixin,
    L2StoreAssertionMixin,
    L2StoreForgettingMixin,
    L2StoreFeedbackMixin,
    L2StoreQueryMixin,
    L2StoreEdgeEmbeddingMixin,
    L2StoreGraphWriteMixin,
):
    """Persists structured cognition artifacts derived from L1 events."""

    def __init__(
        self,
        *,
        db_path: str = "~/.magi/data/memory/memory.db",
        graph_conflict_rules: Mapping[str, GraphConflictRule | Mapping[str, Any]] | None = None,
    ) -> None:
        self.db_path = str(Path(db_path).expanduser())
        self._initialized = False
        self._projection_queue = ProjectionJobQueue(db_path=self.db_path)
        self._seed_graph_conflict_rules = build_graph_conflict_matrix(graph_conflict_rules)
        self._graph_conflict_rules = dict(self._seed_graph_conflict_rules)
        self._exclusive_group_index = build_exclusive_group_index(self._graph_conflict_rules)
        self._assertion_change_callback: Callable[[Dict[str, Any]], Awaitable[None]] | None = None
        self._memory_correction_job_handlers: Dict[
            str, Callable[[Mapping[str, Any]], Awaitable[None]]
        ] = {}
        self._memory_correction_job_wakeup: Callable[[], Awaitable[None]] | None = None
        self._memory_correction_job_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Verify cognition schema (alembic-managed) is reachable."""
        if self._initialized:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with sqlite_connection_async(self.db_path) as db:
            await self._reload_graph_conflict_rules(db)
        self._initialized = True

    async def list_graph_conflict_rules(self) -> List[Dict[str, Any]]:
        """List graph conflict rules from the persisted matrix."""
        await self.initialize()
        return [rule.to_record() for _, rule in sorted(self._graph_conflict_rules.items())]

    async def upsert_graph_conflict_rule(
        self,
        rule: GraphConflictRule | Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Persist and activate a graph conflict rule."""
        normalized = (
            rule if isinstance(rule, GraphConflictRule) else GraphConflictRule.from_mapping(rule)
        )
        now = time.time()
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO graph_conflict_rules(
                    predicate, opposite_predicates, opposite_resolution, exclusive_group,
                    exclusive_scope, exclusive_resolution, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(predicate) DO UPDATE SET
                    opposite_predicates = excluded.opposite_predicates,
                    opposite_resolution = excluded.opposite_resolution,
                    exclusive_group = excluded.exclusive_group,
                    exclusive_scope = excluded.exclusive_scope,
                    exclusive_resolution = excluded.exclusive_resolution,
                    updated_at = excluded.updated_at
                """,
                (
                    normalized.predicate,
                    json.dumps(list(normalized.opposite_predicates), ensure_ascii=False),
                    normalized.opposite_resolution,
                    normalized.exclusive_group,
                    normalized.exclusive_scope,
                    normalized.exclusive_resolution,
                    now,
                    now,
                ),
            )
            await self._reload_graph_conflict_rules(db)
            await db.commit()
        return normalized.to_record()

    def build_rule_graph_candidates(self, event: MemoryEvent) -> list[L2KnowledgeEdgeWrite]:
        """Build deterministic graph candidates from lightweight rules."""
        return self._extract_graph_candidates(event)

    def build_rule_assertion_candidates(self, event: MemoryEvent) -> list[L2TomAssertionWrite]:
        """Build deterministic ToM assertion candidates from lightweight rules."""
        return self._extract_assertion_candidates(event)

    async def upsert_assertion_candidate(self, candidate: Dict[str, Any]) -> str:
        """Persist a normalized assertion candidate."""
        return await self._upsert_assertion(candidate)

    def set_assertion_change_callback(
        self,
        callback: Callable[[Dict[str, Any]], Awaitable[None]] | None,
    ) -> None:
        """Register an async callback invoked after assertion changes commit."""
        self._assertion_change_callback = callback

    async def _notify_assertion_changed(self, assertion: Dict[str, Any]) -> None:
        callback = self._assertion_change_callback
        if callback is None:
            return
        await callback(assertion)

    async def current_subject_revision(self, subject_key: str) -> int:
        """Return the correction revision governing derived views for a subject."""
        return await MemoryCorrectionRepository(self.db_path).current_subject_revision(
            subject_key
        )

    def register_memory_correction_job_handler(
        self,
        job_kind: str,
        handler: Callable[[Mapping[str, Any]], Awaitable[None]],
    ) -> None:
        """Register a composed runtime handler for a durable correction follow-up."""
        self._memory_correction_job_handlers[str(job_kind)] = handler

    def set_memory_correction_job_wakeup(
        self,
        callback: Callable[[], Awaitable[None]] | None,
    ) -> None:
        """Register the runtime scheduler wakeup for durable correction jobs."""
        self._memory_correction_job_wakeup = callback

    async def wake_memory_correction_jobs(self) -> bool:
        """Wake the scheduler without making the user request drain the queue."""
        callback = self._memory_correction_job_wakeup
        if callback is None:
            return False
        try:
            await callback()
        except Exception as exc:
            logger.warning(
                "Memory correction scheduler wakeup failed",
                error=str(exc),
            )
            return False
        return True

    @asynccontextmanager
    async def memory_correction_job_guard(self) -> AsyncIterator[None]:
        """Serialize correction derivation and destructive memory operations."""
        async with self._memory_correction_job_lock:
            yield

    async def get_memory_correction_derivation_state(self, correction_id: str) -> str:
        """Return whether all durable correction follow-ups have completed."""
        return await MemoryCorrectionRepository(self.db_path).derivation_state_for_correction(
            correction_id
        )

    async def process_memory_correction_jobs(
        self,
        *,
        limit: int = 50,
        recover_interrupted: bool = False,
        recover_stale_after_seconds: float | None = None,
        max_attempts: int = DEFAULT_DERIVATION_MAX_ATTEMPTS,
    ) -> Dict[str, int]:
        """Rebuild correction-sensitive derived views from durable jobs."""
        from .corrections.derivations import CorrectionDerivationRunner

        async with self.memory_correction_job_guard():
            if recover_stale_after_seconds is not None:
                await MemoryCorrectionRepository(self.db_path).recover_stale_running_jobs(
                    stale_after_seconds=recover_stale_after_seconds,
                    max_attempts=max_attempts,
                )
            return await CorrectionDerivationRunner(
                db_path=self.db_path,
                l2_store=self,
                handlers=self._memory_correction_job_handlers,
            ).run_pending(
                limit=limit,
                recover_interrupted=recover_interrupted,
                max_attempts=max_attempts,
            )

    async def next_memory_correction_job_wakeup_at(
        self,
        *,
        stale_after_seconds: float = DEFAULT_DERIVATION_STALE_RUNNING_SECONDS,
        max_attempts: int = DEFAULT_DERIVATION_MAX_ATTEMPTS,
    ) -> float | None:
        """Return when the scheduler should next inspect durable correction jobs."""
        return await MemoryCorrectionRepository(self.db_path).next_derivation_wakeup_at(
            stale_after_seconds=stale_after_seconds,
            max_attempts=max_attempts,
        )

    def get_statistics(self) -> Dict[str, Any]:
        """Return lightweight counts for API reporting."""
        return {
            "db_path": self.db_path,
        }

    async def clear(self) -> int:
        """Delete all cognition artifacts."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM tom_trait_assertions") as cursor:
                row = await cursor.fetchone()
                count = int(row[0]) if row else 0
            await db.executescript("""
                DELETE FROM knowledge_graph;
                DELETE FROM entity_facets;
                DELETE FROM tom_trait_assertions;
                DELETE FROM tom_snapshots;
                DELETE FROM user_profile_projection;
                DELETE FROM user_portrait_projection;
                DELETE FROM experience_seed_evidence;
                DELETE FROM experience_seeds;
                DELETE FROM experience_key_events;
                DELETE FROM experience_members;
                DELETE FROM experiences;
                DELETE FROM episodes;
                DELETE FROM episode_events;
                """)
            await db.commit()
        await self._projection_queue.clear_all()
        return count


__all__ = ["L2CognitionStore"]
