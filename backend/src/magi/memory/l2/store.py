"""Unified L2 cognition store for graph facts and defensive ToM assertions."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Mapping

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from ...core.logger import get_logger
from ..event_contracts import MemoryEvent
from ..clear_generation import (
    advance_memory_clear_generation,
    current_memory_clear_generation,
    ensure_memory_clear_state,
    memory_clear_generation_on_connection,
)
from ..context_scope.cache_epoch import invalidate_context_caches
from ..context_scope.catalog import clear_user_contexts
from .corrections.fingerprints import (
    relationship_claim_fingerprint,
    relationship_slot_key,
)
from .graph_conflicts import (
    GraphConflictRule,
    build_exclusive_group_index,
    build_graph_conflict_matrix,
    relationship_predicate_slot,
)
from .models import L2KnowledgeEdgeWrite, L2TomAssertionWrite
from .batch_models import L2ProjectionLease
from .corrections.repository import (
    DEFAULT_DERIVATION_MAX_ATTEMPTS,
    DEFAULT_DERIVATION_STALE_RUNNING_SECONDS,
    MemoryCorrectionRepository,
)
from .corrections.cache_signals import mark_all_subjects_changed, mark_subject_changed
from .claims.repository import L2GroundedClaimStoreMixin
from .claims.outcomes import ClaimTargetOutcomeContext
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
from .governance.source_event_forgetting import L2StoreSourceEventForgettingMixin
from .graph.conflicts import L2StoreGraphConflictMixin
from .graph.edge_embeddings import L2StoreEdgeEmbeddingMixin
from .graph.fact_kind import L2StoreFactKindMixin
from .graph.relationship_rekey_coordinator import RelationshipIdentityRekeyCoordinator
from .graph.relationship_rekey_history import (
    refresh_relationship_governance_history_for_predicate,
)
from .graph.rule_convergence import converge_existing_graph_conflicts
from .graph.writes import L2StoreGraphWriteMixin
from .projection.jobs import L2ProjectionJobStoreMixin
from .projection.entity_links import (
    L2EventEntityLinkOutboxMixin,
    _clear_projection_recovery_on_connection,
    _count_projection_recovery_rows,
)
from .retrieval.queries import L2StoreQueryMixin
from .storage.rows import L2StoreRowMappingMixin

logger = get_logger(__name__)


class L2CognitionStore(
    L2GroundedClaimStoreMixin,
    L2EventEntityLinkOutboxMixin,
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
    L2StoreSourceEventForgettingMixin,
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
        evidence_timestamp_resolver: (
            Callable[[List[str]], Awaitable[Mapping[str, float]]] | None
        ) = None,
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
        self._graph_conflict_rule_lock = asyncio.Lock()
        self._evidence_timestamp_resolver = evidence_timestamp_resolver

    async def resolve_evidence_timestamps(
        self,
        event_ids: List[str],
    ) -> Dict[str, float]:
        """Resolve canonical L1 occurrence times when the unified store is available."""
        normalized = list(dict.fromkeys(str(event_id) for event_id in event_ids if event_id))
        if not normalized or self._evidence_timestamp_resolver is None:
            return {}
        resolved = await self._evidence_timestamp_resolver(normalized)
        return {
            str(event_id): float(observed_at)
            for event_id, observed_at in resolved.items()
            if str(event_id) in normalized
        }

    async def initialize(self) -> None:
        """Verify cognition schema (alembic-managed) is reachable."""
        if self._initialized:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with sqlite_connection_async(self.db_path) as db:
            await ensure_memory_clear_state(db)
            await self._reload_graph_conflict_rules(db)
            await db.commit()
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
        async with self._graph_conflict_rule_lock:
            return await self._upsert_graph_conflict_rule_locked(rule)

    async def _upsert_graph_conflict_rule_locked(
        self,
        rule: GraphConflictRule | Mapping[str, Any],
    ) -> Dict[str, Any]:
        normalized = (
            rule if isinstance(rule, GraphConflictRule) else GraphConflictRule.from_mapping(rule)
        )
        now = time.time()
        await self.initialize()
        previous_rules = dict(self._graph_conflict_rules)
        previous_exclusive_index = dict(self._exclusive_group_index)
        next_rules = dict(previous_rules)
        next_rules[normalized.predicate] = normalized
        affected_subjects: set[str] = set()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
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
                # Converge before identity rekeying: rekey reconciliation can
                # apply the new rule, which must not hide an ambiguous pair of
                # user-authoritative claims from the safety check.
                convergence = await converge_existing_graph_conflicts(
                    db,
                    rule=normalized,
                    rules=next_rules,
                    now=now,
                )
                async with db.execute(
                    """
                    SELECT triple_id, subject_id, predicate, object_id, slot_key,
                           claim_fingerprint, scope_key
                    FROM knowledge_graph
                    WHERE predicate = ?
                    ORDER BY triple_id
                    """,
                    (normalized.predicate,),
                ) as cursor:
                    affected_edges = await cursor.fetchall()
                for edge in affected_edges:
                    expected_slot = relationship_slot_key(
                        subject_id=str(edge["subject_id"]),
                        predicate=str(edge["predicate"]),
                        object_id=str(edge["object_id"]),
                        predicate_slot=relationship_predicate_slot(
                            next_rules,
                            predicate=str(edge["predicate"]),
                            object_id=str(edge["object_id"]),
                        ),
                    )
                    expected_fingerprint = relationship_claim_fingerprint(
                        slot_key_value=expected_slot,
                        subject_id=str(edge["subject_id"]),
                        predicate=str(edge["predicate"]),
                        object_id=str(edge["object_id"]),
                        scope_key_value=str(edge["scope_key"] or "global"),
                    )
                    if (
                        str(edge["slot_key"] or "") == expected_slot
                        and str(edge["claim_fingerprint"] or "") == expected_fingerprint
                    ):
                        continue
                    await RelationshipIdentityRekeyCoordinator(db).rekey(
                        source_triple_id=str(edge["triple_id"]),
                        subject_id=str(edge["subject_id"]),
                        predicate=str(edge["predicate"]),
                        object_id=str(edge["object_id"]),
                        now=now,
                    )
                await refresh_relationship_governance_history_for_predicate(
                    db,
                    predicate=normalized.predicate,
                )
                if convergence.loser_ids:
                    repository = MemoryCorrectionRepository(self.db_path)
                    l3_subjects = await repository.invalidate_l3_insights_on_connection(
                        db,
                        source_kind="edge",
                        source_ids=convergence.loser_ids,
                        subject_keys=convergence.subject_keys,
                        updated_at=now,
                    )
                    affected_subjects.update(convergence.subject_keys)
                    affected_subjects.update(l3_subjects)
                    for subject_key in sorted(affected_subjects):
                        await repository.bump_subject_revision(
                            db,
                            subject_key=subject_key,
                            updated_at=now,
                        )
                await self._reload_graph_conflict_rules(db)
                await db.commit()
            except Exception:
                await db.rollback()
                self._graph_conflict_rules = previous_rules
                self._exclusive_group_index = previous_exclusive_index
                raise
        for subject_key in sorted(affected_subjects):
            mark_subject_changed(self.db_path, subject_key)
        return normalized.to_record()

    def build_rule_graph_candidates(self, event: MemoryEvent) -> list[L2KnowledgeEdgeWrite]:
        """Build deterministic graph candidates from lightweight rules."""
        return self._extract_graph_candidates(event)

    def build_rule_assertion_candidates(self, event: MemoryEvent) -> list[L2TomAssertionWrite]:
        """Build deterministic ToM assertion candidates from lightweight rules."""
        return self._extract_assertion_candidates(event)

    async def upsert_assertion_candidate(
        self,
        candidate: Dict[str, Any],
        *,
        projection_leases: Iterable[L2ProjectionLease] = (),
    ) -> str:
        """Persist a normalized assertion candidate."""
        result = await self._upsert_assertion(
            candidate,
            projection_leases=projection_leases,
        )
        return result.assertion_id

    async def upsert_assertion_candidate_with_receipt(
        self,
        candidate: Dict[str, Any],
        *,
        claim_outcome_context: ClaimTargetOutcomeContext,
        projection_leases: Iterable[L2ProjectionLease] = (),
    ) -> dict[str, Any]:
        """Atomically persist an assertion, Claim outcomes, and a receipt."""

        lease_items = list(projection_leases)
        if not lease_items:
            raise ValueError("projection_leases are required for assertion receipts")
        result = await self._upsert_assertion(
            candidate,
            claim_outcome_context=claim_outcome_context,
            projection_leases=lease_items,
        )
        return {
            "assertion_id": result.assertion_id,
            "governance_action": result.governance_action.value,
            "persisted": result.persisted,
            "reason_code": result.reason_code,
        }

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
        return await MemoryCorrectionRepository(self.db_path).current_subject_revision(subject_key)

    async def active_correction_evidence_event_ids(
        self,
        event_ids: List[str],
    ) -> set[str]:
        """Return L1 evidence IDs deferred to active correction-governed claims."""
        await self.initialize()
        return await MemoryCorrectionRepository(self.db_path).active_correction_evidence_event_ids(
            event_ids
        )

    async def current_clear_generation(self) -> int:
        """Return the durable generation advanced by destructive clears."""
        await self.initialize()
        return await current_memory_clear_generation(self.db_path)

    def register_memory_correction_job_handler(
        self,
        job_kind: str,
        handler: Callable[[Mapping[str, Any]], Awaitable[None]],
    ) -> None:
        """Register a composed runtime handler for a durable correction follow-up."""
        self._memory_correction_job_handlers[str(job_kind)] = handler

    def get_memory_correction_job_handlers(
        self,
    ) -> Dict[str, Callable[[Mapping[str, Any]], Awaitable[None]]]:
        """Return a snapshot of composed correction follow-up handlers."""
        return dict(self._memory_correction_job_handlers)

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
        l3_store: Any | None = None,
        limit: int = 50,
        recover_interrupted: bool = False,
        recover_stale_after_seconds: float | None = None,
        max_attempts: int = DEFAULT_DERIVATION_MAX_ATTEMPTS,
    ) -> Dict[str, int]:
        """Rebuild correction-sensitive derived views from durable jobs."""
        from .corrections.derivations import CorrectionDerivationRunner

        async with self.memory_correction_job_guard():
            repository = MemoryCorrectionRepository(self.db_path)
            activated, subject_revisions = await repository.activate_due_situation_changes(
                limit=limit,
            )
            for subject_key in subject_revisions:
                mark_subject_changed(self.db_path, subject_key)
            if recover_stale_after_seconds is not None:
                await repository.recover_stale_running_jobs(
                    stale_after_seconds=recover_stale_after_seconds,
                    max_attempts=max_attempts,
                )
            stats = await CorrectionDerivationRunner(
                db_path=self.db_path,
                l2_store=self,
                l3_store=l3_store,
            ).run_pending(
                limit=limit,
                recover_interrupted=recover_interrupted,
                max_attempts=max_attempts,
            )
            return {**stats, "activated": activated}

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

    async def clear(
        self,
        *,
        entity_link_clear_generation: int | None = None,
    ) -> int:
        """Delete cognition artifacts without orphaning L1 projections.

        A store with durable entity-link projection lineage can only be fully
        cleared by the unified cross-database clear flow, after that flow has
        fenced the outbox and successfully cleared L1.
        """
        await self.initialize()
        async with self.memory_correction_job_guard():
            async with sqlite_connection_async(self.db_path) as db:
                await db.execute("BEGIN IMMEDIATE")
                try:
                    async with db.execute("SELECT COUNT(*) FROM tom_trait_assertions") as cursor:
                        row = await cursor.fetchone()
                        count = int(row[0]) if row else 0
                    projection_recovery_rows = await _count_projection_recovery_rows(db)
                    if projection_recovery_rows and entity_link_clear_generation is None:
                        raise RuntimeError(
                            "L2 clear with entity-link projections requires unified memory clear"
                        )
                    if entity_link_clear_generation is None:
                        clear_generation = await advance_memory_clear_generation(db)
                    else:
                        clear_generation = await memory_clear_generation_on_connection(db)
                        if int(entity_link_clear_generation) != clear_generation:
                            raise RuntimeError("entity-link projection clear generation is stale")
                    async with db.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ) as cursor:
                        existing_tables = {str(row[0]) for row in await cursor.fetchall()}
                    if {
                        "memory_context_catalog",
                        "memory_context_aliases",
                        "memory_context_bindings",
                    }.issubset(existing_tables):
                        await clear_user_contexts(db)
                    for table in L2_USER_CONTENT_TABLES:
                        if table not in existing_tables:
                            continue
                        await db.execute(f"DELETE FROM {table}")
                    if entity_link_clear_generation is not None:
                        await _clear_projection_recovery_on_connection(
                            db,
                            expected_clear_generation=clear_generation,
                        )
                    elif not projection_recovery_rows:
                        await db.execute("DELETE FROM l2_projection_jobs")
                    await db.commit()
                    invalidate_context_caches(self.db_path)
                except Exception:
                    await db.rollback()
                    raise
        mark_all_subjects_changed(self.db_path)
        return count


L2_USER_CONTENT_TABLES = (
    "l2_claim_projection_outcomes",
    "l2_claim_entity_refs",
    "l2_claim_evidence",
    "l2_grounded_claims",
    "memory_derivation_jobs",
    "memory_derivation_dependencies",
    "memory_correction_forget_barriers",
    "memory_forget_evidence_events",
    "memory_forget_claim_rules",
    "memory_time_range_forget_barriers",
    "memory_entity_projection_identity_blocks",
    "memory_projection_blocks",
    "memory_forget_operation_refs",
    "memory_forget_operation_events",
    "memory_forget_operations",
    "memory_source_event_tombstones",
    "memory_claim_evidence_events",
    "memory_correction_evidence_fail_closed",
    "memory_correction_evidence_events",
    "memory_relationship_conflict_effects",
    "memory_correction_request_fingerprints",
    "memory_correction_revert_blocks",
    "memory_correction_rules",
    "memory_corrections",
    "memory_subject_revisions",
    "knowledge_graph_versions",
    "knowledge_graph",
    "entity_facets",
    "tom_trait_assertions",
    "tom_snapshots",
    "user_profile_projection",
    "user_portrait_projection",
    "experience_seed_evidence",
    "experience_seeds",
    "experience_key_events",
    "experience_members",
    "experience_chapters",
    "experience_drafts",
    "experiences",
    "episodes_fts",
    "episode_events",
    "episodes",
    "l2_promotion_seen",
    "l2_promotion_counter",
)


__all__ = ["L2CognitionStore", "L2_USER_CONTENT_TABLES"]
