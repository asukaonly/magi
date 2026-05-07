"""Unified L2 cognition store for graph facts and defensive ToM assertions."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import aiosqlite

from ...core.logger import get_logger
from ...core.sqlite import sqlite_connection_async
from ..event_contracts import MemoryEvent
from .graph_conflicts import GraphConflictRule, build_exclusive_group_index, build_graph_conflict_matrix
from .models import L2KnowledgeEdgeWrite, L2TomAssertionWrite, ReconciledTraitOutcome
from .projection.queue import ProjectionJobQueue
from .assertions.contradictions import L2StoreContradictionMixin
from .assertions.feedback import L2StoreFeedbackMixin
from .assertions.reconcile import L2StoreReconcileMixin
from .assertions.snapshots import L2StoreSnapshotMixin
from .assertions.write import L2StoreAssertionMixin
from .entities.facets import L2EntityFacetStoreMixin
from .episodes.store import L2EpisodeStoreMixin
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

    async def initialize(self) -> None:
        """Verify cognition schema (alembic-managed) is reachable."""
        if self._initialized:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with sqlite_connection_async(self.db_path) as db:
            await self._seed_default_graph_conflict_rules(db)
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
        normalized = rule if isinstance(rule, GraphConflictRule) else GraphConflictRule.from_mapping(rule)
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
            await db.executescript(
                """
                DELETE FROM knowledge_graph;
                DELETE FROM entity_facets;
                DELETE FROM tom_trait_assertions;
                DELETE FROM tom_snapshots;
                DELETE FROM episodes;
                DELETE FROM episode_events;
                """
            )
            await db.commit()
        await self._projection_queue.clear_all()
        return count

    async def reconcile_entity(
        self,
        *,
        entity_id: str,
        entity_type: Optional[str] = None,
        evidence_timestamps: Optional[Dict[str, float]] = None,
    ) -> list[ReconciledTraitOutcome]:
        """Re-evaluate assertion confidence and stability for one entity."""
        assertions = await self.list_tom_assertions(entity_id=entity_id, entity_type=entity_type, limit=500)
        if not assertions:
            return []

        normalized_entity_type = entity_type or assertions[0]["entity_type"]
        now = time.time()
        outcomes: list[ReconciledTraitOutcome] = []

        async with sqlite_connection_async(self.db_path) as db:
            for assertion in assertions:
                evidence_events = [str(item) for item in assertion.get("evidence_events", [])]
                timestamps = sorted(
                    float(evidence_timestamps[item])
                    for item in evidence_events
                    if evidence_timestamps and item in evidence_timestamps
                )
                first_seen = timestamps[0] if timestamps else float(assertion["first_inferred_at"])
                last_seen = timestamps[-1] if timestamps else float(assertion["last_validated_at"])
                time_span_hours = max(0.0, (last_seen - first_seen) / 3600.0)
                evidence_count = len(set(evidence_events))

                status, confidence, stability_kind = self._derive_reconcile_state(
                    current_state=str(assertion["validation_state"]),
                    current_confidence=float(assertion["confidence_score"]),
                    evidence_count=evidence_count,
                    time_span_hours=time_span_hours,
                    trait_name=str(assertion["trait_name"]),
                    user_feedback=assertion.get("user_feedback"),
                )
                snapshot_field = self._recommend_snapshot_field(
                    trait_name=str(assertion["trait_name"]),
                    status=status,
                )

                await db.execute(
                    """
                    UPDATE tom_trait_assertions
                    SET confidence_score = ?, validation_state = ?, status = ?,
                        last_validated_at = ?, updated_at = ?
                    WHERE assertion_id = ?
                    """,
                    (
                        confidence,
                        status,
                        status,
                        last_seen,
                        now,
                        assertion["assertion_id"],
                    ),
                )
                outcomes.append(
                    ReconciledTraitOutcome(
                        entity_id=entity_id,
                        entity_type=normalized_entity_type,
                        trait_name=str(assertion["trait_name"]),
                        winning_value=str(assertion["trait_value"]),
                        status=status,
                        confidence=confidence,
                        evidence_event_ids=evidence_events,
                        time_span_hours=round(time_span_hours, 2),
                        stability_kind=stability_kind,
                        recommended_snapshot_field=snapshot_field,
                    )
                )
            await db.commit()
        status_counts: dict[str, int] = {}
        for item in outcomes:
            status = str(item.status or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
        logger.info(
            "L2 reconcile entity completed",
            entity_id=entity_id,
            entity_type=normalized_entity_type,
            outcome_count=len(outcomes),
            status_counts=status_counts,
        )
        return outcomes

    async def refresh_entity_snapshot(
        self,
        *,
        entity_id: str,
        entity_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Rebuild one snapshot from reconciled assertions and graph edges."""
        assertions = await self.list_tom_assertions(entity_id=entity_id, entity_type=entity_type, limit=500)
        batch_result = await self.batch_get_relationships(
            entity_ids=[entity_id],
            direction="both",
            status_filters=["active", "deprecated", "conflicted"],
            limit_per_entity=400,
        )
        all_edges = batch_result.get(entity_id, [])
        _superseded = {"deprecated", "conflicted"}
        outgoing = [e for e in all_edges if e["subject_id"] == entity_id and e["status"] == "active"]
        incoming = [e for e in all_edges if e["object_id"] == entity_id and e["status"] == "active"]
        superseded_outgoing = [e for e in all_edges if e["subject_id"] == entity_id and e["status"] in _superseded]
        superseded_incoming = [e for e in all_edges if e["object_id"] == entity_id and e["status"] in _superseded]
        expired_assertions = [item for item in assertions if self._is_assertion_expired(item)]
        _active_statuses = {"stable", "corroborated", "tentative"}
        active_assertions = [
            item
            for item in assertions
            if item.get("status", item["validation_state"]) in {"stable", "corroborated"}
            and not self._is_assertion_expired(item)
            and item.get("user_feedback") != "rejected"
        ]
        tentative_assertions = [
            item
            for item in assertions
            if item.get("status", item["validation_state"]) == "tentative"
            and not self._is_assertion_expired(item)
            and item.get("user_feedback") != "rejected"
        ]
        if not assertions and not outgoing and not incoming and not superseded_outgoing and not superseded_incoming:
            return None

        normalized_entity_type = entity_type or (assertions[0]["entity_type"] if assertions else entity_id.split(":", 1)[0])
        stable_assertions = [item for item in assertions if item["validation_state"] == "stable"]
        snapshot = await self._upsert_snapshot(
            entity_id=entity_id,
            entity_type=normalized_entity_type,
            assertions=active_assertions,
            expired_assertions=expired_assertions,
            stable_assertions=stable_assertions,
            tentative_assertions=tentative_assertions,
            all_raw_assertions=assertions,
            outgoing_relations=outgoing,
            incoming_relations=incoming,
            superseded_outgoing_relations=superseded_outgoing,
            superseded_incoming_relations=superseded_incoming,
        )
        if snapshot is not None:
            logger.info(
                "L2 snapshot refreshed",
                entity_id=entity_id,
                entity_type=normalized_entity_type,
                active_assertion_count=len(active_assertions),
                stable_assertion_count=len(stable_assertions),
                outgoing_relation_count=len(outgoing),
                incoming_relation_count=len(incoming),
                snapshot_version=snapshot.get("snapshot_version"),
            )
        return snapshot

__all__ = ["L2CognitionStore"]
