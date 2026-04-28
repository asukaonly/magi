"""Unified L2 cognition store for graph facts and defensive ToM assertions."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import aiosqlite

from ...core.logger import get_logger
from ...core.sqlite import sqlite_connection_async
from ..event_contracts import MemoryEvent, TomDepth
from .graph_conflicts import GraphConflictRule, build_exclusive_group_index, build_graph_conflict_matrix
from .models import ContradictionHint, L2KnowledgeEdgeWrite, L2TomAssertionWrite, ReconciledTraitOutcome
from .ontology import are_predicates_synonymous
from .projection_queue import ProjectionJobQueue
from .store_episodes import L2EpisodeStoreMixin
from .store_facets import L2EntityFacetStoreMixin
from .store_migrations import L2StoreMigrationMixin
from .store_projection_jobs import L2ProjectionJobStoreMixin
from .store_graph_conflicts import L2StoreGraphConflictMixin
from .store_reconcile import L2StoreReconcileMixin
from .store_rows import L2StoreRowMappingMixin
from .store_schema import L2_COGNITION_SCHEMA_SQL
from .store_utils import (
    CALM_KEYWORDS as _CALM_KEYWORDS,
    DEFAULT_FUTURE_INTENT_TTL_SECONDS,
    MAX_EVIDENCE_EVENT_IDS,
    MOOD_TRAJECTORY_FAMILIES as _MOOD_TRAJECTORY_FAMILIES,
    MOOD_TRAJECTORY_LIMIT as _MOOD_TRAJECTORY_LIMIT,
    STRESS_KEYWORDS as _STRESS_KEYWORDS,
    accumulate_confidence as _accumulate_confidence,
    normalize_store_entity_ref as _normalize_store_entity_ref,
    normalize_store_entity_type as _normalize_store_entity_type,
)

logger = get_logger(__name__)

class L2CognitionStore(
    L2StoreMigrationMixin,
    L2EntityFacetStoreMixin,
    L2EpisodeStoreMixin,
    L2StoreGraphConflictMixin,
    L2ProjectionJobStoreMixin,
    L2StoreReconcileMixin,
    L2StoreRowMappingMixin,
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
        """Create the cognition schema."""
        if self._initialized:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with sqlite_connection_async(self.db_path) as db:
            await db.executescript(L2_COGNITION_SCHEMA_SQL)
            # FTS for episode text search — stores its own content copy.
            await db.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts
                USING fts5(episode_id, summary, label, user_label)
                """
            )
            await self._ensure_knowledge_graph_columns(db)
            await self._ensure_entity_facet_columns(db)
            await self._ensure_tom_assertion_schema(db)
            await self._ensure_tom_snapshot_schema(db)
            await self._projection_queue.ensure_schema(db)
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_l2_projection_jobs_catch_up_owner_status_created
                    ON l2_projection_jobs(catch_up_owner, status, created_at ASC)
                """
            )
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

    async def upsert_knowledge_edge(
        self,
        *,
        subject_id: str,
        subject_type: str,
        predicate: str,
        object_id: str,
        object_type: str,
        fact_kind: str | None = None,
        evidence_event_ids: List[str],
        confidence: float,
        observed_at: float,
        source_type: str,
        extraction_method: str = "rule",
        evidence_text: str = "",
        expires_at: float | None = None,
    ) -> str:
        """Insert or refresh a knowledge-graph edge.

        When a synonymous predicate already exists for the same (subject, object)
        pair, the existing edge is reused instead of creating a new one.  This
        prevents predicate drift where the same fact gets stored multiple times
        under slightly different predicates (e.g. LIKES vs INTERESTED_IN).
        """
        await self.initialize()
        normalized_subject_type = _normalize_store_entity_type(subject_type) or subject_type
        normalized_object_type = _normalize_store_entity_type(object_type) or object_type
        normalized_object_id = _normalize_store_entity_ref(object_id, normalized_object_type) or object_id
        normalized_fact_kind = str(fact_kind).strip() if fact_kind is not None else ""
        now = time.time()

        # ── P2: fact_kind admission check ──
        normalized_fact_kind = self._validate_fact_kind(
            normalized_fact_kind, extraction_method, confidence
        )

        # Auto-set TTL for future_intent edges
        effective_expires_at = expires_at
        if normalized_fact_kind == "future_intent" and effective_expires_at is None:
            effective_expires_at = float(observed_at) + DEFAULT_FUTURE_INTENT_TTL_SECONDS

        # ── Same (S,O) interception: reuse existing synonymous edge ──
        effective_predicate = predicate
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            # Check for active/archived edges with the same (subject, object) pair
            async with db.execute(
                "SELECT triple_id, predicate, observation_count FROM knowledge_graph "
                "WHERE subject_id = ? AND object_id = ? AND status IN ('active', 'archived')",
                (subject_id, normalized_object_id),
            ) as cursor:
                same_pair_edges = await cursor.fetchall()

            if same_pair_edges:
                # Look for an exact predicate match first, then a synonymous one
                exact_match = None
                synonym_match = None
                for row in same_pair_edges:
                    existing_pred = str(row["predicate"])
                    if existing_pred == predicate:
                        exact_match = row
                        break
                    if synonym_match is None and are_predicates_synonymous(existing_pred, predicate):
                        # Pick the one with the highest observation_count as canonical
                        if synonym_match is None or int(row["observation_count"]) > int(synonym_match["observation_count"]):
                            synonym_match = row

                if exact_match is not None:
                    # Exact predicate exists — normal upsert path below will handle it
                    pass
                elif synonym_match is not None:
                    # Synonymous predicate exists — reuse its predicate to prevent drift
                    effective_predicate = str(synonym_match["predicate"])
                    logger.debug(
                        "L2 same-pair interception: reusing synonymous predicate",
                        subject_id=subject_id,
                        object_id=normalized_object_id,
                        requested_predicate=predicate,
                        canonical_predicate=effective_predicate,
                    )

        triple_id = f"triple_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{subject_id}:{effective_predicate}:{normalized_object_id}')}"
        effective_evidence_text = str(evidence_text).strip() if evidence_text else ""
        natural_summary = effective_evidence_text or f"{subject_id} {effective_predicate} {normalized_object_id}"

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT confidence, evidence_event_ids, observation_count, first_observed_at, last_observed_at, fact_kind, evidence_text FROM knowledge_graph WHERE triple_id = ?",
                (triple_id,),
            ) as cursor:
                existing = await cursor.fetchone()

            if existing:
                merged_evidence = sorted(
                    set(json.loads(existing["evidence_event_ids"] or "[]")).union(evidence_event_ids)
                )
                if len(merged_evidence) > MAX_EVIDENCE_EVENT_IDS:
                    merged_evidence = merged_evidence[-MAX_EVIDENCE_EVENT_IDS:]
                observation_count = int(existing["observation_count"]) + 1
                first_observed_at = min(float(existing["first_observed_at"]), float(observed_at))
                last_observed_at = max(float(existing["last_observed_at"]), float(observed_at))
                old_confidence = float(existing["confidence"])
                accumulated_confidence = _accumulate_confidence(old_confidence, float(confidence))
                effective_fact_kind = normalized_fact_kind or str(existing["fact_kind"] or "").strip() or "explicit_fact"
                # Keep the longer evidence_text
                existing_evidence_text = str(existing["evidence_text"] or "")
                if len(effective_evidence_text) <= len(existing_evidence_text):
                    effective_evidence_text = existing_evidence_text
                    natural_summary = effective_evidence_text or f"{subject_id} {effective_predicate} {normalized_object_id}"
                await db.execute(
                    """
                    UPDATE knowledge_graph
                    SET fact_kind = ?, confidence = ?, evidence_event_ids = ?, observation_count = ?,
                        first_observed_at = ?, last_observed_at = ?, last_confirmed_at = ?, source_type = ?,
                        extraction_method = ?, evidence_text = ?, natural_summary = ?,
                        embedding_status = 'pending', expires_at = COALESCE(?, expires_at),
                        updated_at = ?, status = 'active'
                    WHERE triple_id = ?
                    """,
                    (
                        effective_fact_kind,
                        accumulated_confidence,
                        json.dumps(merged_evidence, ensure_ascii=False),
                        observation_count,
                        first_observed_at,
                        last_observed_at,
                        float(observed_at),
                        source_type,
                        extraction_method,
                        effective_evidence_text,
                        natural_summary,
                        effective_expires_at,
                        now,
                        triple_id,
                    ),
                )
            else:
                await db.execute(
                    """
                    INSERT INTO knowledge_graph(
                        triple_id, subject_id, subject_type, predicate, object_id, object_type,
                        fact_kind, confidence, evidence_event_ids, observation_count, first_observed_at,
                        last_observed_at, last_confirmed_at, source_type, extraction_method,
                        evidence_text, natural_summary, embedding_status, expires_at,
                        status, privacy_scope, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, 'active', 'private', ?, ?)
                    """,
                    (
                        triple_id,
                        subject_id,
                        normalized_subject_type,
                        effective_predicate,
                        normalized_object_id,
                        normalized_object_type,
                        normalized_fact_kind or "explicit_fact",
                        float(confidence),
                        json.dumps(sorted(set(evidence_event_ids)), ensure_ascii=False),
                        1,
                        float(observed_at),
                        float(observed_at),
                        float(observed_at),
                        source_type,
                        extraction_method,
                        effective_evidence_text,
                        natural_summary,
                        effective_expires_at,
                        now,
                        now,
                    ),
            )
            await self._resolve_graph_conflicts(
                db=db,
                triple_id=triple_id,
                subject_id=subject_id,
                predicate=effective_predicate,
                object_id=normalized_object_id,
                observed_at=float(observed_at),
                now=now,
            )
            await db.commit()
        logger.debug(
            "L2 knowledge edge upserted",
            triple_id=triple_id,
            subject_id=subject_id,
            predicate=effective_predicate,
            object_id=normalized_object_id,
            confidence=float(confidence),
            source_type=source_type,
            extraction_method=extraction_method,
        )
        return triple_id

    async def corroborate_edge(
        self,
        *,
        triple_id: str,
        evidence_event_ids: List[str],
        new_confidence: float,
        observed_at: float,
        evidence_text: str = "",
    ) -> bool:
        """Accumulate confidence on an existing edge without creating a new triple.

        Returns ``True`` if the edge was found and updated, ``False`` otherwise.
        """
        await self.initialize()
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT confidence, evidence_event_ids, observation_count, first_observed_at, last_observed_at, evidence_text FROM knowledge_graph "
                "WHERE triple_id = ? AND status = 'active'",
                (triple_id,),
            ) as cursor:
                existing = await cursor.fetchone()

            if not existing:
                return False

            merged_evidence = sorted(
                set(json.loads(existing["evidence_event_ids"] or "[]")).union(evidence_event_ids)
            )
            if len(merged_evidence) > MAX_EVIDENCE_EVENT_IDS:
                merged_evidence = merged_evidence[-MAX_EVIDENCE_EVENT_IDS:]
            observation_count = int(existing["observation_count"]) + 1
            accumulated_confidence = _accumulate_confidence(float(existing["confidence"]), float(new_confidence))
            first_observed_at = min(float(existing["first_observed_at"]), float(observed_at))
            last_observed_at = max(float(existing["last_observed_at"]), float(observed_at))
            # Keep the longer evidence_text
            new_evidence_text = str(evidence_text).strip() if evidence_text else ""
            existing_evidence_text = str(existing["evidence_text"] or "")
            effective_evidence_text = new_evidence_text if len(new_evidence_text) > len(existing_evidence_text) else existing_evidence_text

            await db.execute(
                """
                UPDATE knowledge_graph
                SET confidence = ?, evidence_event_ids = ?, observation_count = ?,
                    first_observed_at = ?, last_observed_at = ?, last_confirmed_at = ?,
                    evidence_text = ?, embedding_status = 'pending', updated_at = ?
                WHERE triple_id = ?
                """,
                (
                    accumulated_confidence,
                    json.dumps(merged_evidence, ensure_ascii=False),
                    observation_count,
                    first_observed_at,
                    last_observed_at,
                    float(observed_at),
                    effective_evidence_text,
                    now,
                    triple_id,
                ),
            )
            await db.commit()

        logger.debug(
            "L2 knowledge edge corroborated",
            triple_id=triple_id,
            new_observation_count=observation_count,
            accumulated_confidence=accumulated_confidence,
        )
        return True

    async def count_tom_assertions(self) -> int:
        """Count all ToM assertions."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM tom_trait_assertions"
            ) as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def list_tom_assertions(
        self,
        *,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        trait_families: Optional[List[str]] = None,
        validation_states: Optional[List[str]] = None,
        include_expired: bool = True,
        target_entity_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List ToM assertions ordered by recency."""
        await self.initialize()
        query = "SELECT * FROM tom_trait_assertions WHERE 1=1"
        args: list[Any] = []
        if entity_id:
            query += " AND entity_id = ?"
            args.append(entity_id)
        if entity_type:
            query += " AND entity_type = ?"
            args.append(entity_type)
        if trait_families:
            placeholders = ", ".join("?" for _ in trait_families)
            query += f" AND trait_family IN ({placeholders})"
            args.extend([str(item).strip().lower() for item in trait_families])
        if validation_states:
            placeholders = ", ".join("?" for _ in validation_states)
            query += f" AND validation_state IN ({placeholders})"
            args.extend([str(item).strip() for item in validation_states])
        if target_entity_id:
            query += " AND target_entity_id = ?"
            args.append(target_entity_id)
        if not include_expired:
            now = time.time()
            query += " AND (expires_at IS NULL OR expires_at > ?)"
            args.append(now)
        query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        args.append(int(limit))
        args.append(int(offset))

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [self._assertion_row_to_dict(row) for row in rows]

    async def expire_session_decay_assertions(
        self,
        *,
        entity_ids: List[str],
    ) -> int:
        """Mark tentative ``session_decay`` assertions as expired for the given entities.

        Called at session end so that ephemeral mood / engagement signals do
        not linger beyond the conversation that produced them.  Assertions
        that have already been promoted to *stable* or *corroborated* with
        multi-evidence backing are left untouched — only *tentative* ones
        are expired because they lack sufficient evidence to persist.
        """
        if not entity_ids:
            return 0
        await self.initialize()
        now = time.time()
        placeholders = ", ".join("?" for _ in entity_ids)
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                f"""
                UPDATE tom_trait_assertions
                SET validation_state = 'expired', status = 'expired',
                    expires_at = ?, updated_at = ?
                WHERE entity_id IN ({placeholders})
                  AND decay_policy = 'session_decay'
                  AND validation_state = 'tentative'
                """,
                (now, now, *entity_ids),
            )
            count = cursor.rowcount
            await db.commit()
        return count

    async def get_tom_snapshot(self, *, entity_id: str, entity_type: str) -> Optional[Dict[str, Any]]:
        """Fetch the current stable snapshot for an entity."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM tom_snapshots WHERE entity_id = ? AND entity_type = ?",
                (entity_id, entity_type),
            ) as cursor:
                row = await cursor.fetchone()
        return self._snapshot_row_to_dict(row) if row else None

    async def get_tom_assertion(self, *, assertion_id: str) -> Optional[Dict[str, Any]]:
        """Fetch one ToM assertion by id."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM tom_trait_assertions WHERE assertion_id = ?",
                (assertion_id,),
            ) as cursor:
                row = await cursor.fetchone()
        return self._assertion_row_to_dict(row) if row else None

    async def apply_user_feedback(
        self,
        *,
        assertion_id: str,
        feedback: str,
    ) -> Optional[Dict[str, Any]]:
        """Apply user confirmation or rejection to an assertion.

        Args:
            assertion_id: The assertion to update.
            feedback: ``"confirmed"`` or ``"rejected"``.

        Returns:
            The updated assertion dict, or ``None`` if not found.
        """
        if feedback not in {"confirmed", "rejected"}:
            raise ValueError(f"Invalid feedback value: {feedback!r}")

        await self.initialize()
        now = time.time()

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM tom_trait_assertions WHERE assertion_id = ?",
                (assertion_id,),
            ) as cursor:
                existing = await cursor.fetchone()

            if existing is None:
                return None

            current_confidence = float(existing["confidence_score"])
            current_state = str(existing["validation_state"])

            if feedback == "confirmed":
                new_confidence = min(0.95, current_confidence + 0.20)
                new_state = "stable" if current_state != "contradicted" else current_state
            else:
                new_confidence = 0.10
                new_state = "user_rejected"

            await db.execute(
                """
                UPDATE tom_trait_assertions
                SET user_feedback = ?, user_feedback_at = ?,
                    confidence_score = ?, validation_state = ?, status = ?, updated_at = ?
                WHERE assertion_id = ?
                """,
                (feedback, now, new_confidence, new_state, new_state, now, assertion_id),
            )
            await db.commit()

        logger.info(
            "L2 user feedback applied",
            assertion_id=assertion_id,
            feedback=feedback,
            old_confidence=current_confidence,
            new_confidence=new_confidence,
            old_state=current_state,
            new_state=new_state,
        )
        return await self.get_tom_assertion(assertion_id=assertion_id)

    async def correct_assertion(
        self,
        *,
        assertion_id: str,
        new_value: str,
        reason: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """User-initiated value correction that supersedes the current assertion.

        Creates a new assertion with the corrected value and marks the old one
        as ``superseded``.  The new assertion starts at ``status='stable'``
        with high confidence because it comes directly from the user.

        Args:
            assertion_id: The assertion to correct.
            new_value: The corrected value.
            reason: Optional reason for the correction.

        Returns:
            The newly created assertion dict, or ``None`` if the original was
            not found.
        """
        await self.initialize()
        now = time.time()

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM tom_trait_assertions WHERE assertion_id = ?",
                (assertion_id,),
            ) as cursor:
                existing = await cursor.fetchone()

            if existing is None:
                return None

            new_assertion_id = f"assert_{uuid.uuid4().hex}"

            # Supersede the old assertion
            await db.execute(
                """
                UPDATE tom_trait_assertions
                SET status = 'superseded', superseded_by = ?, superseded_at = ?, updated_at = ?
                WHERE assertion_id = ?
                """,
                (new_assertion_id, now, now, assertion_id),
            )

            # Insert the corrected assertion with high confidence
            evidence = json.loads(existing["evidence_events"] or "[]")
            await db.execute(
                """
                INSERT INTO tom_trait_assertions(
                    assertion_id, entity_id, entity_type, trait_family, trait_name, trait_value,
                    confidence_score, evidence_events, volatility_index, source_domain,
                    inference_depth, validation_state, first_inferred_at, last_validated_at,
                    target_entity_id, target_entity_type, target_scope, temporal_scope,
                    decay_policy, decay_anchor_at, context_ref_id, expires_at,
                    status, privacy_scope, user_feedback, user_feedback_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_assertion_id,
                    str(existing["entity_id"]),
                    str(existing["entity_type"]),
                    str(existing["trait_family"]),
                    str(existing["trait_name"]),
                    new_value,
                    0.95,  # high confidence — user-provided
                    json.dumps(evidence, ensure_ascii=False),
                    float(existing["volatility_index"]),
                    "user_correction",
                    "explicit",
                    "stable",
                    float(existing["first_inferred_at"]),
                    now,
                    str(existing["target_entity_id"] or ""),
                    str(existing["target_entity_type"] or ""),
                    str(existing["target_scope"] or "global"),
                    str(existing["temporal_scope"] or "session"),
                    existing["decay_policy"],
                    existing["decay_anchor_at"],
                    str(existing["context_ref_id"] or ""),
                    existing["expires_at"],
                    "stable",
                    str(existing["privacy_scope"] if "privacy_scope" in existing.keys() else "private"),
                    "confirmed",
                    now,
                    now,
                    now,
                ),
            )
            await db.commit()

        logger.info(
            "L2 user correction applied",
            old_assertion_id=assertion_id,
            new_assertion_id=new_assertion_id,
            entity_id=str(existing["entity_id"]),
            trait_name=str(existing["trait_name"]),
            old_value=str(existing["trait_value"]),
            new_value=new_value,
            reason=reason,
        )
        return await self.get_tom_assertion(assertion_id=new_assertion_id)

    # ── User agency: reject / forget ─────────────────────────────────

    async def reject_edge(
        self,
        *,
        triple_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Mark a KG edge as user-rejected.

        Returns the updated edge dict, or ``None`` if not found.
        """
        await self.initialize()
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT triple_id FROM knowledge_graph WHERE triple_id = ?",
                (triple_id,),
            ) as cursor:
                existing = await cursor.fetchone()
            if existing is None:
                return None
            await db.execute(
                "UPDATE knowledge_graph SET status = 'user_rejected', updated_at = ? WHERE triple_id = ?",
                (now, triple_id),
            )
            await db.commit()
        logger.info("L2 edge rejected by user", triple_id=triple_id)
        return await self.get_relationship(triple_id=triple_id)

    async def forget_entity(
        self,
        *,
        entity_id: str,
    ) -> Dict[str, int]:
        """Cascade soft-delete everything derived from an entity.

        Marks KG edges, assertions, entity facets, and episodes referencing
        the entity.  Does **not** touch L1 events (caller handles L1).

        Returns counts of affected records per table.
        """
        await self.initialize()
        now = time.time()
        counts: Dict[str, int] = {}

        async with sqlite_connection_async(self.db_path) as db:
            # 1. KG edges — subject or object matches
            cursor = await db.execute(
                """
                UPDATE knowledge_graph SET status = 'archived', updated_at = ?
                WHERE (subject_id = ? OR object_id = ?) AND status NOT IN ('archived', 'user_rejected')
                """,
                (now, entity_id, entity_id),
            )
            counts["knowledge_graph"] = cursor.rowcount

            # 2. Assertions — entity_id or target_entity_id matches
            cursor = await db.execute(
                """
                UPDATE tom_trait_assertions SET status = 'archived', updated_at = ?
                WHERE (entity_id = ? OR target_entity_id = ?) AND status NOT IN ('archived', 'user_rejected')
                """,
                (now, entity_id, entity_id),
            )
            counts["tom_trait_assertions"] = cursor.rowcount

            # 3. Entity facets
            cursor = await db.execute(
                """
                UPDATE entity_facets SET status = 'archived', updated_at = ?
                WHERE entity_id = ? AND status != 'archived'
                """,
                (now, entity_id),
            )
            counts["entity_facets"] = cursor.rowcount

            # 4. Episodes — those that list the entity in primary_entity_ids
            escaped = entity_id.replace('"', '""')
            pattern = f'%"{escaped}"%'
            cursor = await db.execute(
                """
                UPDATE episodes SET status = 'invalidated', updated_at = ?
                WHERE primary_entity_ids LIKE ? AND status NOT IN ('invalidated', 'archived')
                """,
                (now, pattern),
            )
            counts["episodes"] = cursor.rowcount

            await db.commit()

        logger.info("L2 entity forgotten", entity_id=entity_id, counts=counts)
        return counts

    async def forget_time_range(
        self,
        *,
        start: float,
        end: float,
    ) -> Dict[str, int]:
        """Cascade invalidation for a time range.

        Marks episodes that overlap the range and assertions inferred during it.
        Does **not** touch L1 events (caller handles L1).

        Returns counts of affected records per table.
        """
        if end <= start:
            raise ValueError("end must be greater than start")

        await self.initialize()
        now = time.time()
        counts: Dict[str, int] = {}

        async with sqlite_connection_async(self.db_path) as db:
            # 1. Episodes overlapping the range
            cursor = await db.execute(
                """
                UPDATE episodes SET status = 'invalidated', updated_at = ?
                WHERE time_start < ? AND time_end > ? AND status NOT IN ('invalidated', 'archived')
                """,
                (now, end, start),
            )
            counts["episodes"] = cursor.rowcount

            # 2. Assertions whose first_inferred_at falls in range
            cursor = await db.execute(
                """
                UPDATE tom_trait_assertions SET status = 'archived', updated_at = ?
                WHERE first_inferred_at >= ? AND first_inferred_at <= ?
                  AND status NOT IN ('archived', 'user_rejected')
                """,
                (now, start, end),
            )
            counts["tom_trait_assertions"] = cursor.rowcount

            # 3. KG edges whose first_observed_at falls in range
            cursor = await db.execute(
                """
                UPDATE knowledge_graph SET status = 'archived', updated_at = ?
                WHERE first_observed_at >= ? AND first_observed_at <= ?
                  AND status NOT IN ('archived', 'user_rejected')
                """,
                (now, start, end),
            )
            counts["knowledge_graph"] = cursor.rowcount

            await db.commit()

        logger.info("L2 time range forgotten", start=start, end=end, counts=counts)
        return counts

    async def forget_episode(
        self,
        *,
        episode_id: str,
        delete_events: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Mark an episode as invalidated.

        If *delete_events* is ``True``, returns the list of member event IDs
        so the caller can soft-delete them from L1.

        Returns ``{"episode_id": ..., "event_ids": [...]}`` or ``None`` if
        the episode was not found.
        """
        await self.initialize()
        now = time.time()

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT episode_id FROM episodes WHERE episode_id = ?",
                (episode_id,),
            ) as cursor:
                existing = await cursor.fetchone()
            if existing is None:
                return None

            await db.execute(
                "UPDATE episodes SET status = 'invalidated', updated_at = ? WHERE episode_id = ?",
                (now, episode_id),
            )

            event_ids: list[str] = []
            if delete_events:
                async with db.execute(
                    "SELECT event_id FROM episode_events WHERE episode_id = ?",
                    (episode_id,),
                ) as cursor:
                    rows = await cursor.fetchall()
                event_ids = [str(row["event_id"]) for row in rows]

            await db.commit()

        logger.info(
            "L2 episode forgotten",
            episode_id=episode_id,
            delete_events=delete_events,
            event_count=len(event_ids),
        )
        return {"episode_id": episode_id, "event_ids": event_ids}

    async def count_tom_snapshots(self) -> int:
        """Count all ToM snapshots."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM tom_snapshots"
            ) as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def list_tom_snapshots(
        self,
        *,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List materialized ToM snapshots ordered by recency."""
        await self.initialize()
        query = "SELECT * FROM tom_snapshots WHERE 1=1"
        args: list[Any] = []
        if entity_id:
            query += " AND entity_id = ?"
            args.append(entity_id)
        if entity_type:
            query += " AND entity_type = ?"
            args.append(entity_type)
        query += " ORDER BY last_updated_at DESC LIMIT ? OFFSET ?"
        args.append(int(limit))
        args.append(int(offset))

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [self._snapshot_row_to_dict(row) for row in rows]

    async def count_relationships(self) -> int:
        """Count all active relationships in the knowledge graph."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM knowledge_graph WHERE status = 'active'"
            ) as cursor:
                row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def get_relationships(
        self,
        *,
        subject_id: Optional[str] = None,
        object_id: Optional[str] = None,
        status: str = "active",
        status_filters: Optional[List[str]] = None,
        predicates: Optional[List[str]] = None,
        object_types: Optional[List[str]] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Query the knowledge graph."""
        await self.initialize()
        if status_filters:
            placeholders = ", ".join("?" for _ in status_filters)
            query = f"SELECT * FROM knowledge_graph WHERE status IN ({placeholders})"
            args: list[Any] = [str(item).strip() for item in status_filters]
        else:
            query = "SELECT * FROM knowledge_graph WHERE status = ?"
            args = [status]
        if subject_id:
            query += " AND subject_id = ?"
            args.append(subject_id)
        if object_id:
            query += " AND object_id = ?"
            args.append(object_id)
        if predicates:
            placeholders = ", ".join("?" for _ in predicates)
            query += f" AND predicate IN ({placeholders})"
            args.extend([str(item).strip().upper() for item in predicates])
        if object_types:
            placeholders = ", ".join("?" for _ in object_types)
            query += f" AND object_type IN ({placeholders})"
            args.extend([str(item).strip().lower() for item in object_types])
        query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        args.append(int(limit))
        args.append(int(offset))
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [self._relation_row_to_dict(row) for row in rows]

    async def get_relationship(self, *, triple_id: str) -> Optional[Dict[str, Any]]:
        """Fetch one graph edge by id."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM knowledge_graph WHERE triple_id = ?",
                (triple_id,),
            ) as cursor:
                row = await cursor.fetchone()
        return self._relation_row_to_dict(row) if row else None

    async def find_edges_by_event_id(self, event_id: str) -> List[Dict[str, Any]]:
        """Return graph edges that cite a specific event as evidence."""
        await self.initialize()
        escaped = str(event_id).replace('"', '""')
        pattern = f'%"{escaped}"%'
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM knowledge_graph WHERE evidence_event_ids LIKE ? AND status = 'active' ORDER BY updated_at DESC LIMIT 500",
                (pattern,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [
            self._relation_row_to_dict(row) for row in rows
            if event_id in json.loads(row["evidence_event_ids"] or "[]")
        ]

    async def batch_get_relationships(
        self,
        *,
        entity_ids: List[str],
        direction: str = "outgoing",
        status: str = "active",
        status_filters: Optional[List[str]] = None,
        predicates: Optional[List[str]] = None,
        target_object_id: Optional[str] = None,
        object_types: Optional[List[str]] = None,
        limit_per_entity: int = 100,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Batch-fetch relationships for multiple entities in one query.

        Returns a dict keyed by entity_id with lists of relationship dicts.
        ``direction`` controls whether entity_ids match subject_id ('outgoing'),
        object_id ('incoming'), or both ('both').
        ``target_object_id`` narrows to edges pointing at a specific object.
        """
        await self.initialize()
        if not entity_ids:
            return {}

        unique_ids = list(dict.fromkeys(entity_ids))
        id_placeholders = ", ".join("?" for _ in unique_ids)

        if status_filters:
            status_ph = ", ".join("?" for _ in status_filters)
            status_clause = f"status IN ({status_ph})"
            status_args = [str(s).strip() for s in status_filters]
        else:
            status_clause = "status = ?"
            status_args = [status]

        direction_clause: str
        if direction == "incoming":
            direction_clause = f"object_id IN ({id_placeholders})"
        elif direction == "both":
            direction_clause = f"(subject_id IN ({id_placeholders}) OR object_id IN ({id_placeholders}))"
            unique_ids = unique_ids + unique_ids  # duplicate for both IN clauses
        else:
            direction_clause = f"subject_id IN ({id_placeholders})"

        args: list[Any] = status_args + unique_ids
        query = f"SELECT * FROM knowledge_graph WHERE {status_clause} AND {direction_clause}"
        if predicates:
            pred_ph = ", ".join("?" for _ in predicates)
            query += f" AND predicate IN ({pred_ph})"
            args.extend(str(p).strip().upper() for p in predicates)
        if target_object_id:
            query += " AND object_id = ?"
            args.append(str(target_object_id))
        if object_types:
            ot_ph = ", ".join("?" for _ in object_types)
            query += f" AND object_type IN ({ot_ph})"
            args.extend(str(t).strip().lower() for t in object_types)
        query += " ORDER BY updated_at DESC"

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()

        result: Dict[str, List[Dict[str, Any]]] = {eid: [] for eid in dict.fromkeys(entity_ids)}
        for row in rows:
            edge = self._relation_row_to_dict(row)
            subject_id = edge["subject_id"]
            object_id = edge["object_id"]
            if direction == "incoming":
                if object_id in result and len(result[object_id]) < limit_per_entity:
                    result[object_id].append(edge)
            elif direction == "both":
                if subject_id in result and len(result[subject_id]) < limit_per_entity:
                    result[subject_id].append(edge)
                if object_id in result and object_id != subject_id and len(result[object_id]) < limit_per_entity:
                    result[object_id].append(edge)
            else:
                if subject_id in result and len(result[subject_id]) < limit_per_entity:
                    result[subject_id].append(edge)
        return result

    async def batch_list_tom_assertions(
        self,
        *,
        entity_ids: List[str],
        entity_type: Optional[str] = None,
        trait_families: Optional[List[str]] = None,
        validation_states: Optional[List[str]] = None,
        include_expired: bool = False,
        target_entity_id: Optional[str] = None,
        limit_per_entity: int = 100,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Batch-fetch assertions for multiple entities in one query.

        Returns a dict keyed by entity_id.
        """
        await self.initialize()
        if not entity_ids:
            return {}

        unique_ids = list(dict.fromkeys(entity_ids))
        id_placeholders = ", ".join("?" for _ in unique_ids)
        query = f"SELECT * FROM tom_trait_assertions WHERE entity_id IN ({id_placeholders})"
        args: list[Any] = list(unique_ids)

        if entity_type:
            query += " AND entity_type = ?"
            args.append(entity_type)
        if trait_families:
            tf_ph = ", ".join("?" for _ in trait_families)
            query += f" AND trait_family IN ({tf_ph})"
            args.extend(str(tf).strip().lower() for tf in trait_families)
        if validation_states:
            vs_ph = ", ".join("?" for _ in validation_states)
            query += f" AND validation_state IN ({vs_ph})"
            args.extend(str(vs).strip() for vs in validation_states)
        if target_entity_id:
            query += " AND target_entity_id = ?"
            args.append(target_entity_id)
        if not include_expired:
            now = time.time()
            query += " AND (expires_at IS NULL OR expires_at > ?)"
            args.append(now)
        query += " ORDER BY updated_at DESC"

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()

        result: Dict[str, List[Dict[str, Any]]] = {eid: [] for eid in unique_ids}
        for row in rows:
            assertion = self._assertion_row_to_dict(row)
            eid = assertion["entity_id"]
            if eid in result and len(result[eid]) < limit_per_entity:
                result[eid].append(assertion)
        return result

    async def batch_get_tom_snapshots(
        self,
        *,
        entities: List[Dict[str, str]],
    ) -> List[Dict[str, Any]]:
        """Batch-fetch snapshots for multiple entity_id+entity_type pairs.

        Returns a list of snapshot dicts (one per found entity).
        """
        await self.initialize()
        if not entities:
            return []

        conditions: list[str] = []
        args: list[Any] = []
        for entity in entities:
            conditions.append("(entity_id = ? AND entity_type = ?)")
            args.append(str(entity["entity_id"]))
            args.append(str(entity["entity_type"]))

        query = f"SELECT * FROM tom_snapshots WHERE {' OR '.join(conditions)}"
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [self._snapshot_row_to_dict(row) for row in rows]

    async def get_pending_edge_embeddings(self, *, limit: int = 200) -> List[Dict[str, Any]]:
        """Return active edges whose embedding_status is 'pending'."""
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM knowledge_graph WHERE embedding_status = 'pending' AND status = 'active' "
                "ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._relation_row_to_dict(row) for row in rows]

    async def update_edge_embedding_status(
        self,
        *,
        triple_ids: List[str],
        status: str = "ready",
    ) -> int:
        """Mark edges as embedded (or failed)."""
        if not triple_ids:
            return 0
        await self.initialize()
        placeholders = ", ".join("?" for _ in triple_ids)
        async with sqlite_connection_async(self.db_path) as db:
            cursor = await db.execute(
                f"UPDATE knowledge_graph SET embedding_status = ? WHERE triple_id IN ({placeholders})",
                (status, *triple_ids),
            )
            await db.commit()
            return cursor.rowcount

    async def search_edges_by_embedding(
        self,
        *,
        vector_index: Any,
        embedding: Any,
        limit: int = 20,
        status_filters: Optional[List[str]] = None,
        predicates: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Find graph edges similar to *embedding* via the edge vector index.

        Returns full edge dicts from knowledge_graph, filtered by status and
        predicates, ordered by vector distance (ascending).
        """
        if vector_index is None or embedding is None:
            return []
        await self.initialize()
        try:
            hits = await vector_index.search(embedding=embedding, limit=limit * 3)
        except Exception as exc:
            logger.debug("Edge vector search failed: %s", exc)
            return []
        if not hits:
            return []

        triple_ids = [hit.entity_id for hit in hits]
        distance_by_id = {hit.entity_id: hit.distance for hit in hits}
        placeholders = ", ".join("?" for _ in triple_ids)
        args: list[Any] = list(triple_ids)

        status_clause = ""
        if status_filters:
            sf_ph = ", ".join("?" for _ in status_filters)
            status_clause = f" AND status IN ({sf_ph})"
            args.extend(str(s).strip() for s in status_filters)
        else:
            status_clause = " AND status = 'active'"

        pred_clause = ""
        if predicates:
            pred_ph = ", ".join("?" for _ in predicates)
            pred_clause = f" AND predicate IN ({pred_ph})"
            args.extend(str(p).strip().upper() for p in predicates)

        query = (
            f"SELECT * FROM knowledge_graph WHERE triple_id IN ({placeholders})"
            f"{status_clause}{pred_clause}"
        )
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()

        edges = [self._relation_row_to_dict(row) for row in rows]
        for edge in edges:
            edge["vector_distance"] = distance_by_id.get(edge["triple_id"])
        edges.sort(key=lambda e: e.get("vector_distance") or float("inf"))
        return edges[:limit]

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

    async def apply_contradiction_hint(self, hint: Dict[str, Any] | ContradictionHint) -> bool:
        """Apply a contradiction hint to an existing graph edge or ToM assertion."""
        payload = hint.to_dict() if isinstance(hint, ContradictionHint) else dict(hint)
        target_record_type = str(payload.get("target_record_type", ""))
        target_record_id = str(payload.get("target_record_id", ""))
        action = str(payload.get("recommended_action", ""))
        confidence = float(payload.get("confidence", 0.0) or 0.0)
        if not target_record_id or not target_record_type:
            return False

        now = time.time()
        await self.initialize()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if target_record_type == "tom_trait_assertion":
                async with db.execute(
                    "SELECT assertion_id, confidence_score, validation_state FROM tom_trait_assertions WHERE assertion_id = ?",
                    (target_record_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                if row is None:
                    return False

                if action == "revalidate_only":
                    await db.execute(
                        """
                        UPDATE tom_trait_assertions
                        SET last_validated_at = ?, updated_at = ?
                        WHERE assertion_id = ?
                        """,
                        (now, now, target_record_id),
                    )
                    await db.commit()
                    logger.info(
                        "L2 contradiction revalidated existing assertion",
                        target_record_type=target_record_type,
                        target_record_id=target_record_id,
                    )
                    return True

                existing_confidence = float(row["confidence_score"])
                next_confidence = self._contradicted_confidence(
                    current_confidence=existing_confidence,
                    hint_confidence=confidence,
                    action=action,
                )
                next_state = "contradicted" if action in {"downgrade_confidence", "mark_conflicted"} else "corroborated"
                await db.execute(
                    """
                    UPDATE tom_trait_assertions
                    SET confidence_score = ?, validation_state = ?, last_validated_at = ?, updated_at = ?
                    WHERE assertion_id = ?
                    """,
                    (
                        next_confidence,
                        next_state,
                        now,
                        now,
                        target_record_id,
                    ),
                )
                await db.commit()
                logger.info(
                    "L2 contradiction applied",
                    target_record_type=target_record_type,
                    target_record_id=target_record_id,
                    action=action,
                    next_state=next_state,
                    next_confidence=next_confidence,
                )
                return True

            if target_record_type == "knowledge_graph":
                if action == "revalidate_only":
                    await db.execute(
                        """
                        UPDATE knowledge_graph
                        SET last_confirmed_at = ?, updated_at = ?
                        WHERE triple_id = ?
                        """,
                        (now, now, target_record_id),
                    )
                    await db.commit()
                    logger.info(
                        "L2 contradiction revalidated existing relation",
                        target_record_type=target_record_type,
                        target_record_id=target_record_id,
                    )
                    return True

                next_status = "deprecated" if action == "mark_deprecated" else "conflicted"
                await db.execute(
                    """
                    UPDATE knowledge_graph
                    SET status = ?, deprecated_by = ?, deprecated_at = ?, updated_at = ?
                    WHERE triple_id = ?
                    """,
                    (
                        next_status,
                        f"hint:{target_record_id}",
                        now,
                        now,
                        target_record_id,
                    ),
                )
                await db.commit()
                logger.info(
                    "L2 contradiction applied",
                    target_record_type=target_record_type,
                    target_record_id=target_record_id,
                    action=action,
                    next_status=next_status,
                )
                return True

        return False

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

    def _extract_graph_candidates(self, event: MemoryEvent) -> list[L2KnowledgeEdgeWrite]:
        content = event.content.lower()
        if " like " not in f" {content} ":
            return []
        subject_id, subject_type = self._entity_identity(event)
        if subject_id is None:
            return []
        return [
            L2KnowledgeEdgeWrite(
                subject_id=subject_id,
                subject_type=subject_type,
                predicate="LIKES",
                object_id="topic:mentioned_preference",
                object_type="topic",
                evidence_event_ids=[event.event_id],
                confidence=0.7,
                observed_at=event.timestamp,
                source_type=event.source,
                extraction_method="keyword_rule",
            )
        ]

    def _extract_assertion_candidates(self, event: MemoryEvent) -> list[L2TomAssertionWrite]:
        subject_id, subject_type = self._entity_identity(event)
        if subject_id is None:
            return []
        if not event.cognition_eligible or event.tom_depth != TomDepth.DEFENSIVE_PSYCHOLOGY:
            return []

        text = event.content.lower()
        if any(keyword in text for keyword in _STRESS_KEYWORDS):
            return [
                L2TomAssertionWrite(
                    entity_id=subject_id,
                    entity_type=subject_type,
                    trait_name="stress_level",
                    trait_value="high",
                    confidence_score=0.3,
                    evidence_events=[event.event_id],
                    volatility_index=0.7,
                    source_domain=event.memory_domain.label,
                    inference_depth=event.tom_depth.label,
                    validation_state="tentative",
                    first_inferred_at=event.timestamp,
                    last_validated_at=event.timestamp,
                )
            ]
        if any(keyword in text for keyword in _CALM_KEYWORDS):
            return [
                L2TomAssertionWrite(
                    entity_id=subject_id,
                    entity_type=subject_type,
                    trait_name="stress_level",
                    trait_value="low",
                    confidence_score=0.3,
                    evidence_events=[event.event_id],
                    volatility_index=0.7,
                    source_domain=event.memory_domain.label,
                    inference_depth=event.tom_depth.label,
                    validation_state="tentative",
                    first_inferred_at=event.timestamp,
                    last_validated_at=event.timestamp,
                )
            ]
        return []

    async def _upsert_assertion(self, candidate: Dict[str, Any]) -> str:
        now = time.time()
        await self.initialize()
        normalized_entity_type = _normalize_store_entity_type(candidate.get("entity_type")) or "other"
        normalized_candidate = dict(candidate)
        normalized_candidate["entity_type"] = normalized_entity_type
        normalized_candidate["trait_family"] = str(candidate.get("trait_family", "")).strip().lower() or self._derive_trait_family(
            str(candidate.get("trait_name", "")).strip()
        )
        normalized_candidate["target_entity_type"] = _normalize_store_entity_type(candidate.get("target_entity_type")) or ""
        normalized_candidate["target_entity_id"] = (
            _normalize_store_entity_ref(candidate.get("target_entity_id"), normalized_candidate["target_entity_type"]) or ""
        )
        normalized_candidate["target_scope"] = str(candidate.get("target_scope", "global")).strip() or "global"
        normalized_candidate["temporal_scope"] = str(candidate.get("temporal_scope", "session")).strip() or "session"
        normalized_candidate["decay_policy"] = self._optional_text(candidate.get("decay_policy"))
        normalized_candidate["decay_anchor_at"] = float(
            candidate.get("decay_anchor_at", candidate.get("last_validated_at", now)) or now
        )
        normalized_candidate["context_ref_id"] = self._optional_text(candidate.get("context_ref_id")) or ""
        normalized_candidate["expires_at"] = self._coerce_expires_at(
            candidate.get("expires_at"),
            trait_family=normalized_candidate["trait_family"],
            trait_name=str(candidate.get("trait_name", "")).strip(),
            target_entity_id=normalized_candidate["target_entity_id"],
            anchor_at=normalized_candidate["decay_anchor_at"],
        )
        normalized_candidate["memory_subdomain"] = str(candidate.get("memory_subdomain", "")).strip() or ""

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            # Find the active assertion for this key (excluding superseded/archived/expired)
            async with db.execute(
                """
                SELECT * FROM tom_trait_assertions
                WHERE entity_id = ? AND entity_type = ? AND trait_name = ? AND target_entity_id = ?
                  AND status NOT IN ('superseded', 'archived', 'expired', 'user_rejected')
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (
                    normalized_candidate["entity_id"],
                    normalized_candidate["entity_type"],
                    normalized_candidate["trait_name"],
                    normalized_candidate["target_entity_id"],
                ),
            ) as cursor:
                existing = await cursor.fetchone()

            if existing is None:
                assertion_id = f"assert_{uuid.uuid4().hex}"
                await db.execute(
                    """
                    INSERT INTO tom_trait_assertions(
                        assertion_id, entity_id, entity_type, trait_family, trait_name, trait_value,
                        confidence_score, evidence_events, volatility_index, source_domain,
                        inference_depth, validation_state, first_inferred_at, last_validated_at,
                        target_entity_id, target_entity_type, target_scope, temporal_scope,
                        decay_policy, decay_anchor_at, context_ref_id, expires_at,
                        status, privacy_scope, memory_subdomain, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        assertion_id,
                        normalized_candidate["entity_id"],
                        normalized_candidate["entity_type"],
                        normalized_candidate["trait_family"],
                        normalized_candidate["trait_name"],
                        normalized_candidate["trait_value"],
                        float(normalized_candidate["confidence_score"]),
                        json.dumps(normalized_candidate["evidence_events"], ensure_ascii=False),
                        float(normalized_candidate["volatility_index"]),
                        normalized_candidate["source_domain"],
                        normalized_candidate["inference_depth"],
                        normalized_candidate["validation_state"],
                        float(normalized_candidate["first_inferred_at"]),
                        float(normalized_candidate["last_validated_at"]),
                        normalized_candidate["target_entity_id"],
                        normalized_candidate["target_entity_type"],
                        normalized_candidate["target_scope"],
                        normalized_candidate["temporal_scope"],
                        normalized_candidate["decay_policy"],
                        normalized_candidate["decay_anchor_at"],
                        normalized_candidate["context_ref_id"],
                        normalized_candidate["expires_at"],
                        normalized_candidate["validation_state"],  # status mirrors validation_state
                        "private",
                        normalized_candidate["memory_subdomain"],
                        now,
                        now,
                    ),
                )
                await db.commit()
                logger.debug(
                    "L2 assertion upserted",
                    assertion_id=assertion_id,
                    entity_id=normalized_candidate["entity_id"],
                    trait_name=normalized_candidate["trait_name"],
                    validation_state=normalized_candidate["validation_state"],
                    confidence=float(normalized_candidate["confidence_score"]),
                    evidence_count=len(normalized_candidate["evidence_events"]),
                    action="inserted",
                )
                return assertion_id

            evidence = sorted(
                set(json.loads(existing["evidence_events"] or "[]")).union(normalized_candidate["evidence_events"])
            )
            if len(evidence) > MAX_EVIDENCE_EVENT_IDS:
                evidence = evidence[-MAX_EVIDENCE_EVENT_IDS:]
            first_inferred_at = float(existing["first_inferred_at"])
            last_validated_at = float(normalized_candidate["last_validated_at"])
            existing_value = str(existing["trait_value"])
            next_value = str(normalized_candidate["trait_value"])
            existing_temporal_scope = str(existing["temporal_scope"] or "session")

            if existing_value != next_value:
                # Value changed — decide: supersede or in-place update
                if existing_temporal_scope in ("session", "momentary"):
                    # Session/momentary state: update in place (ephemeral)
                    confidence = max(0.15, float(existing["confidence_score"]) * 0.35)
                    validation_state = "contradicted"
                    status = "contradicted"
                    await db.execute(
                        """
                        UPDATE tom_trait_assertions
                        SET trait_value = ?, confidence_score = ?, evidence_events = ?,
                            validation_state = ?, status = ?, last_validated_at = ?,
                            target_entity_type = ?, target_scope = ?, temporal_scope = ?,
                            decay_policy = ?, decay_anchor_at = ?, context_ref_id = ?,
                            expires_at = ?, updated_at = ?
                        WHERE assertion_id = ?
                        """,
                        (
                            next_value,
                            confidence,
                            json.dumps(evidence, ensure_ascii=False),
                            validation_state,
                            status,
                            last_validated_at,
                            normalized_candidate["target_entity_type"],
                            normalized_candidate["target_scope"],
                            normalized_candidate["temporal_scope"],
                            normalized_candidate["decay_policy"],
                            normalized_candidate["decay_anchor_at"],
                            normalized_candidate["context_ref_id"],
                            normalized_candidate["expires_at"],
                            now,
                            str(existing["assertion_id"]),
                        ),
                    )
                    await db.commit()
                    logger.debug(
                        "L2 assertion upserted",
                        assertion_id=str(existing["assertion_id"]),
                        entity_id=normalized_candidate["entity_id"],
                        trait_name=normalized_candidate["trait_name"],
                        validation_state=validation_state,
                        confidence=confidence,
                        evidence_count=len(evidence),
                        action="updated_in_place",
                    )
                    return str(existing["assertion_id"])
                else:
                    # Persistent/daily/stable scope: supersede the old, insert new
                    new_assertion_id = f"assert_{uuid.uuid4().hex}"
                    await db.execute(
                        """
                        UPDATE tom_trait_assertions
                        SET status = 'superseded', superseded_by = ?, superseded_at = ?, updated_at = ?
                        WHERE assertion_id = ?
                        """,
                        (new_assertion_id, now, now, str(existing["assertion_id"])),
                    )
                    await db.execute(
                        """
                        INSERT INTO tom_trait_assertions(
                            assertion_id, entity_id, entity_type, trait_family, trait_name, trait_value,
                            confidence_score, evidence_events, volatility_index, source_domain,
                            inference_depth, validation_state, first_inferred_at, last_validated_at,
                            target_entity_id, target_entity_type, target_scope, temporal_scope,
                            decay_policy, decay_anchor_at, context_ref_id, expires_at,
                            status, privacy_scope, memory_subdomain, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            new_assertion_id,
                            normalized_candidate["entity_id"],
                            normalized_candidate["entity_type"],
                            normalized_candidate["trait_family"],
                            normalized_candidate["trait_name"],
                            next_value,
                            float(normalized_candidate["confidence_score"]),
                            json.dumps(normalized_candidate["evidence_events"], ensure_ascii=False),
                            float(normalized_candidate["volatility_index"]),
                            normalized_candidate["source_domain"],
                            normalized_candidate["inference_depth"],
                            "tentative",
                            float(normalized_candidate["first_inferred_at"]),
                            last_validated_at,
                            normalized_candidate["target_entity_id"],
                            normalized_candidate["target_entity_type"],
                            normalized_candidate["target_scope"],
                            normalized_candidate["temporal_scope"],
                            normalized_candidate["decay_policy"],
                            normalized_candidate["decay_anchor_at"],
                            normalized_candidate["context_ref_id"],
                            normalized_candidate["expires_at"],
                            "tentative",
                            str(existing["privacy_scope"] or "private"),
                            normalized_candidate["memory_subdomain"],
                            now,
                            now,
                        ),
                    )
                    await db.commit()
                    logger.info(
                        "L2 assertion superseded",
                        old_assertion_id=str(existing["assertion_id"]),
                        new_assertion_id=new_assertion_id,
                        entity_id=normalized_candidate["entity_id"],
                        trait_name=normalized_candidate["trait_name"],
                        old_value=existing_value,
                        new_value=next_value,
                    )
                    return new_assertion_id
            else:
                # Same value — corroborate
                confidence = min(0.95, 0.3 + 0.25 * max(0, len(evidence) - 1))
                enough_events = len(evidence) >= 3
                enough_span = (last_validated_at - first_inferred_at) > 24 * 60 * 60
                validation_state = "stable" if enough_events and enough_span and confidence >= 0.8 else "corroborated"
                status = validation_state

                await db.execute(
                    """
                    UPDATE tom_trait_assertions
                    SET confidence_score = ?, evidence_events = ?,
                        validation_state = ?, status = ?, last_validated_at = ?, target_entity_type = ?,
                        target_scope = ?, temporal_scope = ?, decay_policy = ?, decay_anchor_at = ?,
                        context_ref_id = ?, expires_at = ?, updated_at = ?
                    WHERE assertion_id = ?
                    """,
                    (
                        confidence,
                        json.dumps(evidence, ensure_ascii=False),
                        validation_state,
                        status,
                        last_validated_at,
                        normalized_candidate["target_entity_type"],
                        normalized_candidate["target_scope"],
                        normalized_candidate["temporal_scope"],
                        normalized_candidate["decay_policy"],
                        normalized_candidate["decay_anchor_at"],
                        normalized_candidate["context_ref_id"],
                        normalized_candidate["expires_at"],
                        now,
                        str(existing["assertion_id"]),
                    ),
                )
                await db.commit()
        logger.debug(
            "L2 assertion upserted",
            assertion_id=str(existing["assertion_id"]),
            entity_id=normalized_candidate["entity_id"],
            trait_name=normalized_candidate["trait_name"],
            validation_state=validation_state,
            confidence=confidence,
            evidence_count=len(evidence),
            action="updated",
        )

        if validation_state == "stable":
            await self._materialize_snapshot(
                entity_id=normalized_candidate["entity_id"],
                entity_type=normalized_candidate["entity_type"],
                trait_name=normalized_candidate["trait_name"],
                trait_value=next_value,
                assertion_ids=[str(existing["assertion_id"])],
                last_interaction_at=last_validated_at,
            )
        return str(existing["assertion_id"])

    async def _materialize_snapshot(
        self,
        *,
        entity_id: str,
        entity_type: str,
        trait_name: str,
        trait_value: str,
        assertion_ids: List[str],
        last_interaction_at: float,
    ) -> None:
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM tom_snapshots WHERE entity_id = ? AND entity_type = ?",
                (entity_id, entity_type),
            ) as cursor:
                existing = await cursor.fetchone()

            core_traits = {"stress_level": trait_value} if trait_name == "stress_level" else {}
            current_stress = 1.0 if trait_value == "high" else 0.2

            if existing:
                merged_traits = json.loads(existing["core_traits"] or "{}")
                merged_traits.update(core_traits)
                await db.execute(
                    """
                    UPDATE tom_snapshots
                    SET core_traits = ?, current_stress_level = ?, last_interaction_at = ?,
                        last_updated_at = ?, update_source_assertion_ids = ?,
                        snapshot_version = snapshot_version + 1
                    WHERE snapshot_id = ?
                    """,
                    (
                        json.dumps(merged_traits, ensure_ascii=False),
                        current_stress,
                        float(last_interaction_at),
                        now,
                        json.dumps(assertion_ids, ensure_ascii=False),
                        str(existing["snapshot_id"]),
                    ),
                )
            else:
                await db.execute(
                    """
                    INSERT INTO tom_snapshots(
                        snapshot_id, entity_id, entity_type, core_traits, sensitive_triggers,
                        preferences, public_sentiment_profile, relationship_topology,
                        current_stress_level, current_mood, current_engagement, current_context,
                        interaction_count, last_interaction_at, last_updated_at,
                        update_source_assertion_ids, snapshot_version, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"snapshot_{uuid.uuid4().hex}",
                        entity_id,
                        entity_type,
                        json.dumps(core_traits, ensure_ascii=False),
                        json.dumps([], ensure_ascii=False),
                        json.dumps({}, ensure_ascii=False),
                        json.dumps({}, ensure_ascii=False),
                        json.dumps({}, ensure_ascii=False),
                        current_stress,
                        None,
                        0.5,
                        json.dumps({}, ensure_ascii=False),
                        1,
                        float(last_interaction_at),
                        now,
                        json.dumps(assertion_ids, ensure_ascii=False),
                        1,
                        now,
                    ),
                )
            await db.commit()

    async def _upsert_snapshot(
        self,
        *,
        entity_id: str,
        entity_type: str,
        assertions: List[Dict[str, Any]],
        expired_assertions: List[Dict[str, Any]],
        stable_assertions: List[Dict[str, Any]],
        tentative_assertions: List[Dict[str, Any]] | None = None,
        all_raw_assertions: List[Dict[str, Any]] | None = None,
        outgoing_relations: List[Dict[str, Any]],
        incoming_relations: List[Dict[str, Any]],
        superseded_outgoing_relations: List[Dict[str, Any]],
        superseded_incoming_relations: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        now = time.time()
        stable_by_trait = {item["trait_name"]: item for item in stable_assertions}
        active_by_trait = {item["trait_name"]: item for item in assertions}

        core_traits: dict[str, Any] = {}
        preferences: dict[str, Any] = {}
        sensitive_triggers: list[str] = []
        public_sentiment_profile: dict[str, Any] = {}

        current_stress_level = 0.0
        stress_assertion = active_by_trait.get("stress_level") or stable_by_trait.get("stress_level")
        if stress_assertion:
            stress_value = str(stress_assertion["trait_value"])
            current_stress_level = 1.0 if stress_value == "high" else 0.2 if stress_value == "low" else 0.5
            if stress_assertion["validation_state"] == "stable":
                core_traits["stress_level"] = stress_value

        current_mood = None
        mood_assertion = active_by_trait.get("mood")
        if mood_assertion:
            current_mood = str(mood_assertion["trait_value"])

        current_engagement = 0.5
        engagement_assertion = active_by_trait.get("engagement")
        if engagement_assertion:
            current_engagement = self._engagement_value(str(engagement_assertion["trait_value"]))

        for trait_name, assertion in stable_by_trait.items():
            if trait_name.startswith("preference."):
                preference_key = trait_name.split(".", 1)[1]
                preferences[preference_key] = assertion["trait_value"]
            elif trait_name.startswith("trigger."):
                sensitive_triggers.append(str(assertion["trait_value"]))
            elif trait_name not in {"stress_level", "mood", "engagement"}:
                core_traits[trait_name] = assertion["trait_value"]

        # Enrich preferences from taste_profile / preference_profile assertions
        _PREF_FAMILIES = {"taste_profile", "preference_profile"}
        for assertion in assertions:
            family = assertion.get("trait_family", "")
            if family not in _PREF_FAMILIES:
                continue
            t_name = str(assertion.get("trait_name", ""))
            if t_name.startswith("preference."):
                continue  # already handled above via stable_by_trait
            confidence = float(assertion.get("confidence_score", 0))
            evidence_count = len(assertion.get("evidence_events", []) or [])
            affinity = round(min(1.0, confidence * (1 + 0.1 * min(evidence_count, 5))), 2)
            preferences[t_name] = {
                "value": assertion["trait_value"],
                "affinity": affinity,
                "family": family,
            }

        for relation in outgoing_relations:
            if relation["predicate"] == "LIKES":
                confidence = float(relation.get("confidence", 0.5))
                obs_count = int(relation.get("observation_count", 1))
                affinity = round(min(1.0, confidence * (1 + 0.1 * min(obs_count, 5))), 2)
                preferences[relation["object_id"]] = {
                    "value": "like",
                    "affinity": affinity,
                    "family": "graph",
                }
            elif relation["predicate"] == "DISLIKES":
                confidence = float(relation.get("confidence", 0.5))
                obs_count = int(relation.get("observation_count", 1))
                affinity = round(min(1.0, confidence * (1 + 0.1 * min(obs_count, 5))), 2)
                preferences[relation["object_id"]] = {
                    "value": "dislike",
                    "affinity": -affinity,
                    "family": "graph",
                }

        relationship_topology = {
            "outgoing_count": len(outgoing_relations),
            "incoming_count": len(incoming_relations),
            "outgoing": [
                {
                    "predicate": relation["predicate"],
                    "object_id": relation["object_id"],
                    "object_type": relation["object_type"],
                }
                for relation in outgoing_relations[:20]
            ],
            "incoming": [
                {
                    "predicate": relation["predicate"],
                    "subject_id": relation["subject_id"],
                    "subject_type": relation["subject_type"],
                }
                for relation in incoming_relations[:20]
            ],
        }
        current_context = {
            "active_assertion_count": len(assertions),
            "expired_assertion_count": len(expired_assertions),
            "stable_assertion_count": len(stable_assertions),
            "relation_count": len(outgoing_relations) + len(incoming_relations),
        }
        emerging_signals: list[dict[str, Any]] = []
        for item in (tentative_assertions or []):
            emerging_signals.append({
                "trait_family": item.get("trait_family", ""),
                "trait_name": item["trait_name"],
                "trait_value": item["trait_value"],
                "confidence": float(item.get("confidence_score", 0)),
                "evidence_count": len(item.get("evidence_events", []) or []),
                "first_inferred_at": float(item.get("first_inferred_at", 0)),
                "last_validated_at": float(item.get("last_validated_at", 0)),
            })

        update_source_assertion_ids = [item["assertion_id"] for item in assertions]
        last_interaction_at = max(
            [float(item["last_validated_at"]) for item in assertions] + [now]
        )
        interaction_count = max(1, len(assertions) + len(outgoing_relations) + len(incoming_relations))

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM tom_snapshots WHERE entity_id = ? AND entity_type = ?",
                (entity_id, entity_type),
            ) as cursor:
                existing = await cursor.fetchone()
            existing_snapshot = self._snapshot_row_to_dict(existing) if existing else None

            # Build mood trajectory: accumulate from previous snapshot, append current state
            prev_trajectory: list[dict[str, Any]] = (
                list(existing_snapshot.get("mood_trajectory", [])) if existing_snapshot else []
            )
            for item in (all_raw_assertions or assertions):
                family = item.get("trait_family")
                if family not in _MOOD_TRAJECTORY_FAMILIES:
                    continue
                if self._is_assertion_expired(item):
                    continue
                val = str(item["trait_value"])
                same_family = [e for e in prev_trajectory if e.get("family") == family]
                if same_family and str(same_family[-1].get("value")) == val:
                    continue
                prev_trajectory.append({
                    "family": family,
                    "value": val,
                    "confidence": float(item.get("confidence_score", 0)),
                    "at": float(item.get("last_validated_at", 0)),
                })
            prev_trajectory.sort(key=lambda e: e["at"])
            mood_trajectory = prev_trajectory[-_MOOD_TRAJECTORY_LIMIT:]

            evolution_payload = self._build_snapshot_evolution_payload(
                existing_snapshot=existing_snapshot,
                core_traits=core_traits,
                preferences=preferences,
                relationship_topology=relationship_topology,
                assertions=assertions,
                outgoing_relations=outgoing_relations,
                incoming_relations=incoming_relations,
                superseded_outgoing_relations=superseded_outgoing_relations,
                superseded_incoming_relations=superseded_incoming_relations,
                fallback_updated_at=now,
            )

            payload = (
                json.dumps(core_traits, ensure_ascii=False),
                json.dumps(sorted(set(sensitive_triggers)), ensure_ascii=False),
                json.dumps(preferences, ensure_ascii=False),
                json.dumps(public_sentiment_profile, ensure_ascii=False),
                json.dumps(relationship_topology, ensure_ascii=False),
                float(current_stress_level),
                current_mood,
                float(current_engagement),
                json.dumps(current_context, ensure_ascii=False),
                interaction_count,
                last_interaction_at,
                now,
                json.dumps(update_source_assertion_ids, ensure_ascii=False),
                json.dumps(evolution_payload["core_traits_history"], ensure_ascii=False),
                json.dumps(evolution_payload["preferences_history"], ensure_ascii=False),
                json.dumps(evolution_payload["relationship_history"], ensure_ascii=False),
                evolution_payload["last_evolution_at"],
                json.dumps(evolution_payload["active_record_ids"], ensure_ascii=False),
                json.dumps(evolution_payload["superseded_record_ids"], ensure_ascii=False),
                json.dumps(emerging_signals, ensure_ascii=False),
                json.dumps(mood_trajectory, ensure_ascii=False),
            )

            if existing:
                await db.execute(
                    """
                    UPDATE tom_snapshots
                    SET core_traits = ?, sensitive_triggers = ?, preferences = ?,
                        public_sentiment_profile = ?, relationship_topology = ?,
                        current_stress_level = ?, current_mood = ?, current_engagement = ?,
                        current_context = ?, interaction_count = ?, last_interaction_at = ?,
                        last_updated_at = ?, update_source_assertion_ids = ?,
                        core_traits_history = ?, preferences_history = ?, relationship_history = ?,
                        last_evolution_at = ?, active_record_ids = ?, superseded_record_ids = ?,
                        emerging_signals = ?, mood_trajectory = ?,
                        snapshot_version = snapshot_version + 1
                    WHERE snapshot_id = ?
                    """,
                    payload + (str(existing["snapshot_id"]),),
                )
            else:
                await db.execute(
                    """
                    INSERT INTO tom_snapshots(
                        snapshot_id, entity_id, entity_type, core_traits, sensitive_triggers,
                        preferences, public_sentiment_profile, relationship_topology,
                        current_stress_level, current_mood, current_engagement, current_context,
                        interaction_count, last_interaction_at, last_updated_at,
                        update_source_assertion_ids, core_traits_history, preferences_history,
                        relationship_history, last_evolution_at, active_record_ids,
                        superseded_record_ids, emerging_signals, mood_trajectory,
                        snapshot_version, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"snapshot_{uuid.uuid4().hex}",
                        entity_id,
                        entity_type,
                    )
                    + payload
                    + (1, now),
                )
            await db.commit()

        snapshot = await self.get_tom_snapshot(entity_id=entity_id, entity_type=entity_type)
        assert snapshot is not None
        return snapshot

    # ── P2: fact_kind admission ──────────────────────────────────────

    # extraction_methods that qualify as explicit/structured sources
    _EXPLICIT_SOURCES: set[str] = {"rule", "structured_hint", "source_explicit"}
    _STRUCTURED_SOURCES: set[str] = {"structured_hint", "rule"}

    # fact_kind values that require specific extraction lineage
    _FACT_KIND_RULES: dict[str, set[str]] = {
        "public_topology": _EXPLICIT_SOURCES | _STRUCTURED_SOURCES,
        "stable_preference": _EXPLICIT_SOURCES,
    }

    @staticmethod
    def _validate_fact_kind(
        fact_kind: str,
        extraction_method: str,
        confidence: float,
    ) -> str:
        """Validate fact_kind against extraction_method, downgrading on mismatch.

        Returns the (possibly adjusted) fact_kind. Empty input is returned as-is
        so callers can fall back to existing values on update.
        """
        if not fact_kind:
            return ""

        # public_topology: only from explicit/structured sources,
        # or high-confidence structured
        if fact_kind == "public_topology":
            allowed = L2CognitionStore._FACT_KIND_RULES["public_topology"]
            if extraction_method not in allowed and not (
                extraction_method in L2CognitionStore._STRUCTURED_SOURCES
                and confidence >= 0.8
            ):
                logger.warning(
                    "fact_kind_downgraded",
                    original=fact_kind,
                    extraction_method=extraction_method,
                    confidence=confidence,
                    target="explicit_fact",
                )
                return "explicit_fact"

        # stable_preference: only from explicit user statements/configs
        elif fact_kind == "stable_preference":
            allowed = L2CognitionStore._FACT_KIND_RULES["stable_preference"]
            if extraction_method not in allowed:
                logger.warning(
                    "fact_kind_downgraded",
                    original=fact_kind,
                    extraction_method=extraction_method,
                    target="explicit_fact",
                )
                return "explicit_fact"

        # interaction_evidence: real events can direct-write, no restriction needed

        return fact_kind


__all__ = ["L2CognitionStore"]
