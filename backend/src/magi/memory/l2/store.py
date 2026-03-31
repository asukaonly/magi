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
from .graph_conflicts import DEFAULT_GRAPH_CONFLICT_RULES, GraphConflictRule, build_exclusive_group_index, build_graph_conflict_matrix, iter_opposite_predicates
from .models import ContradictionHint, L2KnowledgeEdgeWrite, L2TomAssertionWrite, ReconciledTraitOutcome
from .ontology import are_predicates_synonymous, coerce_unknown_entity_type
from .projection_queue import ProjectionJobQueue

_STRESS_KEYWORDS = ("stress", "stressed", "anxious", "anxiety", "pressure")
_CALM_KEYWORDS = ("calm", "relaxed", "relief", "peaceful")
_MOMENTARY_TRAITS = {"annoyance", "irritation", "frustration"}
_SNAPSHOT_HISTORY_LIMIT = 5
DEFAULT_FUTURE_INTENT_TTL_SECONDS = 30 * 24 * 3600  # 30 days
logger = get_logger(__name__)


def _normalize_store_entity_type(entity_type: str | None) -> str | None:
    if entity_type is None:
        return None
    text = str(entity_type).strip().lower()
    if not text:
        return None
    if text in {"user", "assistant", "system"}:
        return text
    return coerce_unknown_entity_type(text)


def _normalize_store_entity_ref(entity_id: str | None, entity_type: str | None) -> str | None:
    if entity_id is None:
        return None
    text = str(entity_id).strip()
    if not text or not entity_type or ":" not in text:
        return text or None
    _, _, suffix = text.partition(":")
    if not suffix:
        return text
    return f"{entity_type}:{suffix}"


def _accumulate_confidence(old: float, new: float) -> float:
    """Combine old and new confidence using noisy-OR (independent evidence).

    Result = 1 - (1 - old) * (1 - new), clamped to [0.0, 0.99].
    """
    combined = 1.0 - (1.0 - max(0.0, old)) * (1.0 - max(0.0, new))
    return min(combined, 0.99)


class L2CognitionStore:
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
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_graph (
                    triple_id TEXT PRIMARY KEY,
                    subject_id TEXT NOT NULL,
                    subject_type TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    object_type TEXT NOT NULL,
                    fact_kind TEXT NOT NULL DEFAULT 'explicit_fact',
                    confidence REAL NOT NULL DEFAULT 0.5,
                    evidence_event_ids TEXT NOT NULL,
                    observation_count INTEGER NOT NULL DEFAULT 1,
                    first_observed_at REAL NOT NULL,
                    last_observed_at REAL NOT NULL,
                    last_confirmed_at REAL,
                    source_type TEXT,
                    extraction_method TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    deprecated_by TEXT,
                    deprecated_at REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(subject_id, predicate, object_id)
                );

                CREATE TABLE IF NOT EXISTS entity_facets (
                    facet_id TEXT PRIMARY KEY,
                    entity_id TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    facet_name TEXT NOT NULL,
                    facet_value TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0.5,
                    evidence_event_ids TEXT NOT NULL,
                    first_observed_at REAL NOT NULL,
                    last_observed_at REAL NOT NULL,
                    source_type TEXT,
                    extraction_method TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(entity_id, facet_name, facet_value)
                );
                CREATE INDEX IF NOT EXISTS idx_entity_facets_entity_name
                    ON entity_facets(entity_id, facet_name);
                CREATE INDEX IF NOT EXISTS idx_entity_facets_name_value
                    ON entity_facets(facet_name, facet_value);

                CREATE INDEX IF NOT EXISTS idx_knowledge_graph_status_subject
                    ON knowledge_graph(status, subject_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_knowledge_graph_status_object
                    ON knowledge_graph(status, object_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_knowledge_graph_status_predicate
                    ON knowledge_graph(status, predicate);

                CREATE TABLE IF NOT EXISTS tom_trait_assertions (
                    assertion_id TEXT PRIMARY KEY,
                    entity_id TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    trait_family TEXT NOT NULL,
                    trait_name TEXT NOT NULL,
                    trait_value TEXT NOT NULL,
                    confidence_score REAL NOT NULL,
                    evidence_events TEXT NOT NULL,
                    volatility_index REAL NOT NULL,
                    source_domain TEXT NOT NULL,
                    inference_depth TEXT NOT NULL,
                    validation_state TEXT NOT NULL,
                    first_inferred_at REAL NOT NULL,
                    last_validated_at REAL NOT NULL,
                    target_entity_id TEXT NOT NULL DEFAULT '',
                    target_entity_type TEXT NOT NULL DEFAULT '',
                    target_scope TEXT NOT NULL DEFAULT 'global',
                    temporal_scope TEXT NOT NULL DEFAULT 'session',
                    decay_policy TEXT,
                    decay_anchor_at REAL,
                    context_ref_id TEXT NOT NULL DEFAULT '',
                    expires_at REAL,
                    user_feedback TEXT,
                    user_feedback_at REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(entity_id, entity_type, trait_name, target_entity_id)
                );
                CREATE INDEX IF NOT EXISTS idx_tom_assertions_entity_updated
                    ON tom_trait_assertions(entity_id, entity_type, updated_at DESC);

                CREATE TABLE IF NOT EXISTS tom_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    entity_id TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    core_traits TEXT,
                    sensitive_triggers TEXT,
                    preferences TEXT,
                    public_sentiment_profile TEXT,
                    relationship_topology TEXT,
                    current_stress_level REAL DEFAULT 0.0,
                    current_mood TEXT,
                    current_engagement REAL DEFAULT 0.5,
                    current_context TEXT,
                    interaction_count INTEGER DEFAULT 0,
                    last_interaction_at REAL,
                    last_updated_at REAL NOT NULL,
                    update_source_assertion_ids TEXT,
                    snapshot_version INTEGER DEFAULT 1,
                    created_at REAL NOT NULL,
                    UNIQUE(entity_id, entity_type)
                );

                CREATE TABLE IF NOT EXISTS graph_conflict_rules (
                    predicate TEXT PRIMARY KEY,
                    opposite_predicates TEXT NOT NULL DEFAULT '[]',
                    opposite_resolution TEXT NOT NULL DEFAULT 'mark_deprecated',
                    exclusive_group TEXT,
                    exclusive_scope TEXT NOT NULL DEFAULT 'same_subject',
                    exclusive_resolution TEXT NOT NULL DEFAULT 'mark_deprecated',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS l2_projection_jobs (
                    event_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    batch_owner TEXT,
                    catch_up_owner TEXT,
                    max_events INTEGER,
                    min_ready_events INTEGER,
                    max_wait_seconds REAL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    claimed_by TEXT,
                    claimed_at REAL,
                    started_at REAL,
                    completed_at REAL,
                    last_error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_l2_projection_jobs_status_created
                    ON l2_projection_jobs(status, created_at ASC);

                CREATE INDEX IF NOT EXISTS idx_l2_projection_jobs_owner_status_created
                    ON l2_projection_jobs(batch_owner, status, created_at ASC);

                """
            )
            await self._ensure_knowledge_graph_columns(db)
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

    async def _ensure_tom_assertion_schema(self, db: aiosqlite.Connection) -> None:
        db.row_factory = aiosqlite.Row
        async with db.execute("PRAGMA table_info(tom_trait_assertions)") as cursor:
            rows = await cursor.fetchall()
        existing_columns = {str(row["name"]) for row in rows}
        required_columns = {
            "assertion_id",
            "entity_id",
            "entity_type",
            "trait_family",
            "trait_name",
            "trait_value",
            "confidence_score",
            "evidence_events",
            "volatility_index",
            "source_domain",
            "inference_depth",
            "validation_state",
            "first_inferred_at",
            "last_validated_at",
            "target_entity_id",
            "target_entity_type",
            "target_scope",
            "temporal_scope",
            "decay_policy",
            "decay_anchor_at",
            "context_ref_id",
            "expires_at",
            "created_at",
            "updated_at",
        }
        if required_columns.issubset(existing_columns):
            # Schema is up-to-date for the core columns; ensure newer optional
            # columns are present (added after the original full-recreation migration).
            if "user_feedback" not in existing_columns:
                await db.execute("ALTER TABLE tom_trait_assertions ADD COLUMN user_feedback TEXT")
            if "user_feedback_at" not in existing_columns:
                await db.execute("ALTER TABLE tom_trait_assertions ADD COLUMN user_feedback_at REAL")
            return

        await db.executescript(
            """
            ALTER TABLE tom_trait_assertions RENAME TO tom_trait_assertions_legacy;
            CREATE TABLE tom_trait_assertions (
                assertion_id TEXT PRIMARY KEY,
                entity_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                trait_family TEXT NOT NULL,
                trait_name TEXT NOT NULL,
                trait_value TEXT NOT NULL,
                confidence_score REAL NOT NULL,
                evidence_events TEXT NOT NULL,
                volatility_index REAL NOT NULL,
                source_domain TEXT NOT NULL,
                inference_depth TEXT NOT NULL,
                validation_state TEXT NOT NULL,
                first_inferred_at REAL NOT NULL,
                last_validated_at REAL NOT NULL,
                target_entity_id TEXT NOT NULL DEFAULT '',
                target_entity_type TEXT NOT NULL DEFAULT '',
                target_scope TEXT NOT NULL DEFAULT 'global',
                temporal_scope TEXT NOT NULL DEFAULT 'session',
                decay_policy TEXT,
                decay_anchor_at REAL,
                context_ref_id TEXT NOT NULL DEFAULT '',
                expires_at REAL,
                user_feedback TEXT,
                user_feedback_at REAL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(entity_id, entity_type, trait_name, target_entity_id)
            );
            """
        )
        await db.execute(
            """
            INSERT INTO tom_trait_assertions(
                assertion_id, entity_id, entity_type, trait_family, trait_name, trait_value,
                confidence_score, evidence_events, volatility_index, source_domain, inference_depth,
                validation_state, first_inferred_at, last_validated_at, target_entity_id,
                target_entity_type, target_scope, temporal_scope, decay_policy, decay_anchor_at,
                context_ref_id, expires_at, created_at, updated_at
            )
            SELECT
                assertion_id,
                entity_id,
                entity_type,
                CASE
                    WHEN trait_name = 'stress_level' THEN 'stress'
                    WHEN trait_name IN ('mood', 'annoyance', 'irritation', 'frustration') THEN 'mood'
                    WHEN trait_name = 'engagement' THEN 'engagement'
                    WHEN trait_name LIKE 'trigger.%' THEN 'trigger'
                    WHEN trait_name IN ('taste_profile', 'taste_preference') THEN 'taste_profile'
                    WHEN trait_name LIKE 'preference.%' THEN 'preference_profile'
                    ELSE 'preference_profile'
                END,
                trait_name,
                trait_value,
                confidence_score,
                evidence_events,
                volatility_index,
                source_domain,
                inference_depth,
                validation_state,
                first_inferred_at,
                last_validated_at,
                '',
                '',
                'global',
                CASE
                    WHEN trait_name IN ('annoyance', 'irritation', 'frustration') THEN 'momentary'
                    WHEN trait_name = 'stress_level' THEN 'daily'
                    WHEN trait_name IN ('mood', 'engagement') THEN 'session'
                    ELSE 'stable'
                END,
                CASE
                    WHEN trait_name IN ('annoyance', 'irritation', 'frustration') THEN 'fast_decay'
                    WHEN trait_name = 'stress_level' THEN 'time_window'
                    WHEN trait_name IN ('mood', 'engagement') THEN 'session_decay'
                    ELSE 'evidence_only'
                END,
                last_validated_at,
                '',
                expires_at,
                created_at,
                updated_at
            FROM tom_trait_assertions_legacy
            """
        )
        await db.execute("DROP TABLE tom_trait_assertions_legacy")

    async def _ensure_tom_snapshot_schema(self, db: aiosqlite.Connection) -> None:
        db.row_factory = aiosqlite.Row
        async with db.execute("PRAGMA table_info(tom_snapshots)") as cursor:
            rows = await cursor.fetchall()
        existing_columns = {str(row["name"]) for row in rows}
        required_columns = {
            "core_traits_history": "TEXT",
            "preferences_history": "TEXT",
            "relationship_history": "TEXT",
            "last_evolution_at": "REAL",
            "active_record_ids": "TEXT",
            "superseded_record_ids": "TEXT",
        }
        for column_name, column_type in required_columns.items():
            if column_name in existing_columns:
                continue
            await db.execute(f"ALTER TABLE tom_snapshots ADD COLUMN {column_name} {column_type}")

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

        # Auto-set TTL for future_intent edges
        effective_expires_at = expires_at
        if normalized_fact_kind == "future_intent" and effective_expires_at is None:
            effective_expires_at = float(observed_at) + DEFAULT_FUTURE_INTENT_TTL_SECONDS

        # ── Same (S,O) interception: reuse existing synonymous edge ──
        effective_predicate = predicate
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            # Check for active edges with the same (subject, object) pair
            async with db.execute(
                "SELECT triple_id, predicate, observation_count FROM knowledge_graph "
                "WHERE subject_id = ? AND object_id = ? AND status = 'active'",
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
                "SELECT confidence, evidence_event_ids, observation_count, first_observed_at, fact_kind, evidence_text FROM knowledge_graph WHERE triple_id = ?",
                (triple_id,),
            ) as cursor:
                existing = await cursor.fetchone()

            if existing:
                merged_evidence = sorted(
                    set(json.loads(existing["evidence_event_ids"] or "[]")).union(evidence_event_ids)
                )
                observation_count = int(existing["observation_count"]) + 1
                first_observed_at = float(existing["first_observed_at"])
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
                        last_observed_at = ?, last_confirmed_at = ?, source_type = ?,
                        extraction_method = ?, evidence_text = ?, natural_summary = ?,
                        embedding_status = 'pending', expires_at = COALESCE(?, expires_at),
                        updated_at = ?
                    WHERE triple_id = ?
                    """,
                    (
                        effective_fact_kind,
                        accumulated_confidence,
                        json.dumps(merged_evidence, ensure_ascii=False),
                        observation_count,
                        float(observed_at),
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
                        status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, 'active', ?, ?)
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
                "SELECT confidence, evidence_event_ids, observation_count, evidence_text FROM knowledge_graph "
                "WHERE triple_id = ? AND status = 'active'",
                (triple_id,),
            ) as cursor:
                existing = await cursor.fetchone()

            if not existing:
                return False

            merged_evidence = sorted(
                set(json.loads(existing["evidence_event_ids"] or "[]")).union(evidence_event_ids)
            )
            observation_count = int(existing["observation_count"]) + 1
            accumulated_confidence = _accumulate_confidence(float(existing["confidence"]), float(new_confidence))
            # Keep the longer evidence_text
            new_evidence_text = str(evidence_text).strip() if evidence_text else ""
            existing_evidence_text = str(existing["evidence_text"] or "")
            effective_evidence_text = new_evidence_text if len(new_evidence_text) > len(existing_evidence_text) else existing_evidence_text

            await db.execute(
                """
                UPDATE knowledge_graph
                SET confidence = ?, evidence_event_ids = ?, observation_count = ?,
                    last_observed_at = ?, last_confirmed_at = ?,
                    evidence_text = ?, embedding_status = 'pending', updated_at = ?
                WHERE triple_id = ?
                """,
                (
                    accumulated_confidence,
                    json.dumps(merged_evidence, ensure_ascii=False),
                    observation_count,
                    float(observed_at),
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

    async def upsert_entity_facet(
        self,
        *,
        entity_id: str,
        entity_type: str,
        facet_name: str,
        facet_value: str,
        evidence_event_ids: List[str],
        confidence: float,
        observed_at: float,
        source_type: str,
        extraction_method: str = "structured_hint",
    ) -> str:
        """Insert or refresh a sidecar facet for one entity."""
        await self.initialize()
        normalized_entity_type = _normalize_store_entity_type(entity_type) or entity_type
        normalized_entity_id = _normalize_store_entity_ref(entity_id, normalized_entity_type) or entity_id
        normalized_facet_name = str(facet_name or "").strip().casefold()
        normalized_facet_value = str(facet_value or "").strip().casefold()
        now = time.time()
        facet_id = f"facet_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{normalized_entity_id}:{normalized_facet_name}:{normalized_facet_value}')}"

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT confidence, evidence_event_ids, first_observed_at FROM entity_facets WHERE facet_id = ?",
                (facet_id,),
            ) as cursor:
                existing = await cursor.fetchone()

            if existing:
                merged_evidence = sorted(set(json.loads(existing["evidence_event_ids"] or "[]")).union(evidence_event_ids))
                accumulated_confidence = _accumulate_confidence(float(existing["confidence"]), float(confidence))
                await db.execute(
                    """
                    UPDATE entity_facets
                    SET confidence = ?, evidence_event_ids = ?, last_observed_at = ?,
                        source_type = ?, extraction_method = ?, updated_at = ?
                    WHERE facet_id = ?
                    """,
                    (
                        accumulated_confidence,
                        json.dumps(merged_evidence, ensure_ascii=False),
                        float(observed_at),
                        source_type,
                        extraction_method,
                        now,
                        facet_id,
                    ),
                )
            else:
                await db.execute(
                    """
                    INSERT INTO entity_facets(
                        facet_id, entity_id, entity_type, facet_name, facet_value,
                        confidence, evidence_event_ids, first_observed_at, last_observed_at,
                        source_type, extraction_method, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        facet_id,
                        normalized_entity_id,
                        normalized_entity_type,
                        normalized_facet_name,
                        normalized_facet_value,
                        float(confidence),
                        json.dumps(sorted(set(evidence_event_ids)), ensure_ascii=False),
                        float(observed_at),
                        float(observed_at),
                        source_type,
                        extraction_method,
                        now,
                        now,
                    ),
                )
            await db.commit()
        return facet_id

    async def list_entity_facets(
        self,
        *,
        entity_id: str | None = None,
        facet_name: str | None = None,
        facet_values: List[str] | None = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List persisted entity facets."""
        await self.initialize()
        sql = "SELECT * FROM entity_facets WHERE 1=1"
        args: list[Any] = []
        if entity_id:
            sql += " AND entity_id = ?"
            args.append(entity_id)
        if facet_name:
            sql += " AND facet_name = ?"
            args.append(str(facet_name).strip().casefold())
        normalized_values = [str(item).strip().casefold() for item in (facet_values or []) if str(item).strip()]
        if normalized_values:
            placeholders = ", ".join("?" for _ in normalized_values)
            sql += f" AND facet_value IN ({placeholders})"
            args.extend(normalized_values)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        args.append(max(1, int(limit)))

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [self._facet_row_to_dict(row) for row in rows]

    async def filter_entity_ids_by_facet(
        self,
        *,
        entity_ids: List[str],
        facet_name: str,
        facet_values: List[str],
    ) -> List[str]:
        """Filter candidate entity IDs by matching sidecar facets."""
        await self.initialize()
        normalized_entity_ids = [str(item).strip() for item in entity_ids if str(item).strip()]
        normalized_values = [str(item).strip().casefold() for item in facet_values if str(item).strip()]
        normalized_facet_name = str(facet_name or "").strip().casefold()
        if not normalized_entity_ids or not normalized_facet_name or not normalized_values:
            return []

        placeholders_entity = ", ".join("?" for _ in normalized_entity_ids)
        placeholders_value = ", ".join("?" for _ in normalized_values)
        sql = f"""
            SELECT entity_id
            FROM entity_facets
            WHERE entity_id IN ({placeholders_entity})
              AND facet_name = ?
              AND facet_value IN ({placeholders_value})
            GROUP BY entity_id
        """
        args: list[Any] = [*normalized_entity_ids, normalized_facet_name, *normalized_values]
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, tuple(args)) as cursor:
                rows = await cursor.fetchall()

        matched = {str(row["entity_id"]) for row in rows}
        return [entity_id for entity_id in normalized_entity_ids if entity_id in matched]

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
        query += " ORDER BY updated_at DESC LIMIT ?"
        args.append(int(limit))

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
                SET validation_state = 'expired', expires_at = ?, updated_at = ?
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
                    confidence_score = ?, validation_state = ?, updated_at = ?
                WHERE assertion_id = ?
                """,
                (feedback, now, new_confidence, new_state, now, assertion_id),
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

    async def list_tom_snapshots(
        self,
        *,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        limit: int = 100,
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
        query += " ORDER BY last_updated_at DESC LIMIT ?"
        args.append(int(limit))

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [self._snapshot_row_to_dict(row) for row in rows]

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
        query += " ORDER BY updated_at DESC LIMIT ?"
        args.append(int(limit))
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

    async def enqueue_projection_job(
        self,
        *,
        event_id: str,
        source: str,
        event_type: str,
        batch_owner: str | None = None,
        catch_up_owner: str | None = None,
        max_events: int | None = None,
        min_ready_events: int | None = None,
        max_wait_seconds: float | None = None,
    ) -> bool:
        """Insert one pending L2 projection job if it does not already exist."""
        await self.initialize()
        return await self._projection_queue.enqueue(
            event_id=event_id,
            source=source,
            event_type=event_type,
            batch_owner=batch_owner,
            catch_up_owner=catch_up_owner,
            max_events=max_events,
            min_ready_events=min_ready_events,
            max_wait_seconds=max_wait_seconds,
        )

    async def claim_ready_projection_jobs(
        self,
        *,
        consumer_name: str,
        limit: int,
    ) -> list[Dict[str, Any]]:
        """Claim pending jobs whose owner bucket is ready for extraction."""
        await self.initialize()
        return await self._projection_queue.claim_ready(
            consumer_name=consumer_name,
            limit=limit,
        )

    async def claim_projection_jobs(
        self,
        *,
        consumer_name: str,
        limit: int,
    ) -> list[Dict[str, Any]]:
        """Claim up to *limit* pending projection jobs ordered by creation time."""
        await self.initialize()
        return await self._projection_queue.claim(
            consumer_name=consumer_name,
            limit=limit,
        )

    async def mark_projection_jobs_running(
        self,
        event_ids: List[str],
        *,
        consumer_name: str,
    ) -> int:
        """Mark queued projection jobs as actively running."""
        if not event_ids:
            return 0
        await self.initialize()
        return await self._projection_queue.mark_running(
            event_ids=event_ids,
            consumer_name=consumer_name,
        )

    async def complete_projection_jobs(self, event_ids: List[str]) -> int:
        """Mark projection jobs as completed."""
        if not event_ids:
            return 0
        await self.initialize()
        return await self._projection_queue.complete(event_ids=event_ids)

    async def fail_projection_jobs(
        self,
        event_ids: List[str],
        *,
        error_text: str | None = None,
        requeue: bool,
    ) -> int:
        """Mark projection jobs as failed or return them to pending."""
        if not event_ids:
            return 0
        await self.initialize()
        return await self._projection_queue.fail(
            event_ids=event_ids,
            error_text=error_text,
            requeue=requeue,
        )

    async def requeue_stale_projection_jobs(
        self,
        *,
        queued_timeout_seconds: float,
        running_timeout_seconds: float,
    ) -> int:
        """Return stale queued or running jobs back to pending for replay."""
        await self.initialize()
        return await self._projection_queue.requeue_stale(
            queued_timeout_seconds=queued_timeout_seconds,
            running_timeout_seconds=running_timeout_seconds,
        )

    async def get_projection_backlog_stats(self) -> Dict[str, int]:
        """Return counts for durable L2 projection jobs by status."""
        await self.initialize()
        return await self._projection_queue.get_backlog_stats()

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
                    SET confidence_score = ?, validation_state = ?, last_validated_at = ?, updated_at = ?
                    WHERE assertion_id = ?
                    """,
                    (
                        confidence,
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
        active_assertions = [
            item
            for item in assertions
            if item["validation_state"] in {"stable", "corroborated"}
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

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM tom_trait_assertions
                WHERE entity_id = ? AND entity_type = ? AND trait_name = ? AND target_entity_id = ?
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
                        decay_policy, decay_anchor_at, context_ref_id, expires_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            first_inferred_at = float(existing["first_inferred_at"])
            last_validated_at = float(normalized_candidate["last_validated_at"])
            existing_value = str(existing["trait_value"])
            next_value = str(normalized_candidate["trait_value"])

            if existing_value != next_value:
                confidence = max(0.15, float(existing["confidence_score"]) * 0.35)
                validation_state = "contradicted"
            else:
                confidence = min(0.95, 0.3 + 0.25 * max(0, len(evidence) - 1))
                enough_events = len(evidence) >= 3
                enough_span = (last_validated_at - first_inferred_at) > 24 * 60 * 60
                validation_state = "stable" if enough_events and enough_span and confidence >= 0.8 else "corroborated"

            await db.execute(
                """
                UPDATE tom_trait_assertions
                SET trait_value = ?, confidence_score = ?, evidence_events = ?,
                    validation_state = ?, last_validated_at = ?, target_entity_type = ?,
                    target_scope = ?, temporal_scope = ?, decay_policy = ?, decay_anchor_at = ?,
                    context_ref_id = ?, expires_at = ?, updated_at = ?
                WHERE assertion_id = ?
                """,
                (
                    next_value if existing_value != next_value else existing_value,
                    confidence,
                    json.dumps(evidence, ensure_ascii=False),
                    validation_state,
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

        for relation in outgoing_relations:
            if relation["predicate"] == "LIKES":
                preferences[relation["object_id"]] = "like"
            elif relation["predicate"] == "DISLIKES":
                preferences[relation["object_id"]] = "dislike"

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
                        superseded_record_ids, snapshot_version, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    def _build_snapshot_evolution_payload(
        self,
        *,
        existing_snapshot: Dict[str, Any] | None,
        core_traits: Dict[str, Any],
        preferences: Dict[str, Any],
        relationship_topology: Dict[str, Any],
        assertions: List[Dict[str, Any]],
        outgoing_relations: List[Dict[str, Any]],
        incoming_relations: List[Dict[str, Any]],
        superseded_outgoing_relations: List[Dict[str, Any]],
        superseded_incoming_relations: List[Dict[str, Any]],
        fallback_updated_at: float,
    ) -> Dict[str, Any]:
        previous_core_traits = dict(existing_snapshot.get("core_traits", {})) if existing_snapshot else {}
        previous_preferences = dict(existing_snapshot.get("preferences", {})) if existing_snapshot else {}
        previous_relationship = (
            dict(existing_snapshot.get("relationship_topology", {})) if existing_snapshot else {}
        )

        active_assertion_ids = [str(item["assertion_id"]) for item in assertions]
        active_relation_ids = [
            str(item["triple_id"]) for item in [*outgoing_relations, *incoming_relations]
        ]
        active_record_ids = self._dedupe_preserve_order([*active_assertion_ids, *active_relation_ids])

        previous_assertion_ids = (
            [str(item) for item in existing_snapshot.get("update_source_assertion_ids", [])]
            if existing_snapshot
            else []
        )

        preference_support_ids = {
            str(item["object_id"]): [str(item["triple_id"])]
            for item in outgoing_relations
            if item["predicate"] in {"LIKES", "DISLIKES"}
        }
        preference_superseded_ids = self._group_relation_ids_by_object(superseded_outgoing_relations)
        core_support_ids = {
            str(item["trait_name"]): [str(item["assertion_id"])]
            for item in assertions
        }

        next_preference_entries = self._build_mapping_transition_entries(
            previous_values=previous_preferences,
            current_values=preferences,
            support_ids_by_field=preference_support_ids,
            superseded_ids_by_field=preference_superseded_ids,
            evolved_at_by_field=self._relation_evolved_at_by_object(
                outgoing_relations=outgoing_relations,
                superseded_outgoing_relations=superseded_outgoing_relations,
                fallback_updated_at=fallback_updated_at,
            ),
        )
        next_core_entries = self._build_mapping_transition_entries(
            previous_values=previous_core_traits,
            current_values=core_traits,
            support_ids_by_field=core_support_ids,
            superseded_ids_by_field={
                field_name: previous_assertion_ids
                for field_name in set(previous_core_traits).intersection(core_traits)
            },
            evolved_at_by_field={
                str(item["trait_name"]): float(item["last_validated_at"])
                for item in assertions
            },
        )

        relationship_support_ids = [str(item["triple_id"]) for item in [*outgoing_relations, *incoming_relations]]
        relationship_superseded_ids = [
            str(item["triple_id"]) for item in [*superseded_outgoing_relations, *superseded_incoming_relations]
        ]
        next_relationship_entries = self._build_relationship_transition_entries(
            previous_relationship=previous_relationship,
            current_relationship=relationship_topology,
            support_ids=relationship_support_ids,
            superseded_ids=relationship_superseded_ids,
            fallback_updated_at=fallback_updated_at,
        )

        core_traits_history = self._merge_snapshot_history(
            existing_history=existing_snapshot.get("core_traits_history", []) if existing_snapshot else [],
            new_entries=next_core_entries,
        )
        preferences_history = self._merge_snapshot_history(
            existing_history=existing_snapshot.get("preferences_history", []) if existing_snapshot else [],
            new_entries=next_preference_entries,
        )
        relationship_history = self._merge_snapshot_history(
            existing_history=existing_snapshot.get("relationship_history", []) if existing_snapshot else [],
            new_entries=next_relationship_entries,
        )

        history_entries = [*core_traits_history, *preferences_history, *relationship_history]
        evolution_timestamps = [
            float(entry["evolved_at"])
            for entry in history_entries
            if entry.get("evolved_at") is not None
        ]
        last_evolution_at = max(evolution_timestamps) if evolution_timestamps else (
            existing_snapshot.get("last_evolution_at") if existing_snapshot else None
        )
        superseded_record_ids = self._dedupe_preserve_order(
            [
                str(record_id)
                for entry in history_entries
                for record_id in entry.get("superseded_record_ids", [])
                if str(record_id).strip()
            ]
        )

        return {
            "core_traits_history": core_traits_history,
            "preferences_history": preferences_history,
            "relationship_history": relationship_history,
            "last_evolution_at": last_evolution_at,
            "active_record_ids": active_record_ids,
            "superseded_record_ids": superseded_record_ids,
        }

    def _build_mapping_transition_entries(
        self,
        *,
        previous_values: Dict[str, Any],
        current_values: Dict[str, Any],
        support_ids_by_field: Dict[str, List[str]],
        superseded_ids_by_field: Dict[str, List[str]],
        evolved_at_by_field: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for field_name in sorted(set(previous_values).intersection(current_values)):
            previous_value = previous_values.get(field_name)
            current_value = current_values.get(field_name)
            if previous_value == current_value:
                continue
            entries.append(
                {
                    "field": field_name,
                    "from": previous_value,
                    "to": current_value,
                    "evolved_at": evolved_at_by_field.get(field_name),
                    "supporting_record_ids": self._dedupe_preserve_order(support_ids_by_field.get(field_name, [])),
                    "superseded_record_ids": self._dedupe_preserve_order(
                        superseded_ids_by_field.get(field_name, [])
                    ),
                }
            )
        return entries

    def _build_relationship_transition_entries(
        self,
        *,
        previous_relationship: Dict[str, Any],
        current_relationship: Dict[str, Any],
        support_ids: List[str],
        superseded_ids: List[str],
        fallback_updated_at: float,
    ) -> List[Dict[str, Any]]:
        if not previous_relationship or previous_relationship == current_relationship:
            return []
        return [
            {
                "field": "relationship_topology",
                "from": previous_relationship,
                "to": current_relationship,
                "evolved_at": fallback_updated_at,
                "supporting_record_ids": self._dedupe_preserve_order(support_ids),
                "superseded_record_ids": self._dedupe_preserve_order(superseded_ids),
            }
        ]

    def _merge_snapshot_history(
        self,
        *,
        existing_history: List[Dict[str, Any]],
        new_entries: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        merged = [dict(entry) for entry in new_entries]
        for entry in existing_history:
            if any(self._same_history_entry(entry, candidate) for candidate in merged):
                continue
            merged.append(dict(entry))
        return merged[:_SNAPSHOT_HISTORY_LIMIT]

    def _same_history_entry(self, left: Dict[str, Any], right: Dict[str, Any]) -> bool:
        return (
            left.get("field") == right.get("field")
            and left.get("from") == right.get("from")
            and left.get("to") == right.get("to")
        )

    def _group_relation_ids_by_object(self, relations: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        grouped: dict[str, list[str]] = {}
        for relation in relations:
            if relation["predicate"] not in {"LIKES", "DISLIKES"}:
                continue
            object_id = str(relation["object_id"])
            grouped.setdefault(object_id, []).append(str(relation["triple_id"]))
        return {key: self._dedupe_preserve_order(value) for key, value in grouped.items()}

    def _relation_evolved_at_by_object(
        self,
        *,
        outgoing_relations: List[Dict[str, Any]],
        superseded_outgoing_relations: List[Dict[str, Any]],
        fallback_updated_at: float,
    ) -> Dict[str, float]:
        timestamps: dict[str, float] = {}
        for relation in [*outgoing_relations, *superseded_outgoing_relations]:
            if relation["predicate"] not in {"LIKES", "DISLIKES"}:
                continue
            object_id = str(relation["object_id"])
            candidate_timestamp = max(
                float(relation.get("last_observed_at") or 0.0),
                float(relation.get("deprecated_at") or 0.0),
                float(relation.get("updated_at") or 0.0),
                fallback_updated_at,
            )
            timestamps[object_id] = max(timestamps.get(object_id, 0.0), candidate_timestamp)
        return timestamps

    def _dedupe_preserve_order(self, values: List[str]) -> List[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = str(value).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
        return ordered

    def _derive_trait_family(self, trait_name: str) -> str:
        normalized = trait_name.strip().lower()
        if normalized == "stress_level":
            return "stress"
        if normalized in {"mood", "annoyance", "irritation", "frustration"}:
            return "mood"
        if normalized == "engagement":
            return "engagement"
        if normalized.startswith("trigger."):
            return "trigger"
        if normalized in {"taste_profile", "taste_preference"}:
            return "taste_profile"
        if normalized.startswith("preference."):
            return "preference_profile"
        return "preference_profile"

    def _optional_text(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _coerce_expires_at(
        self,
        value: Any,
        *,
        trait_family: str,
        trait_name: str,
        target_entity_id: str,
        anchor_at: float,
    ) -> float | None:
        if value is not None:
            return float(value)
        normalized_trait_name = trait_name.strip().lower()
        if target_entity_id and normalized_trait_name in _MOMENTARY_TRAITS:
            return anchor_at + 2 * 60 * 60
        if trait_family == "mood":
            return anchor_at + 12 * 60 * 60
        if trait_family == "stress":
            return anchor_at + 24 * 60 * 60
        if trait_family == "engagement":
            return anchor_at + 12 * 60 * 60
        if trait_family in {"group_atmosphere", "public_sentiment", "relationship_shift"}:
            return anchor_at + 6 * 60 * 60
        return None

    def _is_assertion_expired(self, assertion: Dict[str, Any], *, now: float | None = None) -> bool:
        expires_at = assertion.get("expires_at")
        if expires_at is None:
            return False
        current_time = float(now if now is not None else time.time())
        return float(expires_at) <= current_time

    _TEMPORARY_STATE_TRAITS = frozenset({"stress_level", "mood", "engagement"})

    def _derive_reconcile_state(
        self,
        *,
        current_state: str,
        current_confidence: float,
        evidence_count: int,
        time_span_hours: float,
        trait_name: str,
        user_feedback: Optional[str] = None,
    ) -> tuple[str, float, str]:
        is_temporary = trait_name in self._TEMPORARY_STATE_TRAITS

        # User-rejected assertions stay rejected.
        if user_feedback == "rejected":
            return ("user_rejected", 0.10, "volatile_pattern")

        # User-confirmed assertions are promoted to stable with a confidence floor.
        if user_feedback == "confirmed":
            stability_kind = "temporary_state" if is_temporary else "stable_trait"
            return ("stable", max(current_confidence, 0.85), stability_kind)

        if current_state == "contradicted":
            return ("contradicted", min(current_confidence, 0.35), "volatile_pattern")

        # Temporary-state traits (mood, stress, engagement) are inherently
        # short-lived observations.  A single piece of evidence is enough to
        # treat them as corroborated so that they appear in snapshots and are
        # actionable until they expire or are contradicted.
        if is_temporary:
            if evidence_count >= 3 and time_span_hours >= 24.0:
                return ("stable", max(current_confidence, 0.82), "temporary_state")
            if evidence_count >= 1:
                return ("corroborated", max(current_confidence, 0.50), "temporary_state")

        if evidence_count >= 3 and time_span_hours >= 24.0:
            stability_kind = "stable_trait"
            return ("stable", max(current_confidence, 0.82), stability_kind)

        if evidence_count >= 2:
            return ("corroborated", max(current_confidence, 0.58), "volatile_pattern")

        return ("tentative", min(current_confidence, 0.3), "volatile_pattern")

    def _recommend_snapshot_field(self, *, trait_name: str, status: str) -> str:
        if status not in {"stable", "corroborated"}:
            return "none"
        if trait_name.startswith("preference."):
            return "preferences"
        if trait_name.startswith("trigger."):
            return "sensitive_triggers"
        if trait_name == "stress_level":
            return "core_traits" if status == "stable" else "current_stress_level"
        if trait_name == "mood":
            return "current_mood"
        if trait_name == "engagement":
            return "current_engagement"
        return "core_traits"

    def _engagement_value(self, value: str) -> float:
        normalized = value.strip().lower()
        if normalized in {"high", "engaged", "focused"}:
            return 0.9
        if normalized in {"low", "disengaged", "distant"}:
            return 0.2
        try:
            return float(normalized)
        except ValueError:
            return 0.5

    def _contradicted_confidence(self, *, current_confidence: float, hint_confidence: float, action: str) -> float:
        base = current_confidence * 0.35
        if action == "mark_conflicted":
            return round(max(0.1, min(base, 0.35)), 4)
        if action == "revalidate_only":
            return round(max(0.15, current_confidence * 0.75), 4)
        confidence_weight = 1.0 - min(max(hint_confidence, 0.0), 1.0) * 0.45
        return round(max(0.1, min(current_confidence * confidence_weight, 0.35)), 4)

    async def _resolve_graph_conflicts(
        self,
        *,
        db: aiosqlite.Connection,
        triple_id: str,
        subject_id: str,
        predicate: str,
        object_id: str,
        observed_at: float,
        now: float,
    ) -> None:
        rule = self._graph_conflict_rules.get(predicate)
        if rule is None:
            return

        for opposite_predicate in iter_opposite_predicates(rule):
            await self._apply_graph_status(
                db=db,
                status=self._status_from_action(rule.opposite_resolution),
                triple_id=triple_id,
                observed_at=observed_at,
                now=now,
                query="""
                UPDATE knowledge_graph
                SET status = ?, deprecated_by = ?, deprecated_at = ?, updated_at = ?
                WHERE subject_id = ? AND object_id = ? AND predicate = ? AND triple_id != ? AND status = 'active'
                """,
                args=(
                    subject_id,
                    object_id,
                    opposite_predicate,
                    triple_id,
                ),
            )

        if not rule.exclusive_group:
            return

        group_predicates = self._exclusive_group_index.get(rule.exclusive_group, ())
        if not group_predicates:
            return

        placeholders = ", ".join("?" for _ in group_predicates)
        await self._apply_graph_status(
            db=db,
            status=self._status_from_action(rule.exclusive_resolution),
            triple_id=triple_id,
            observed_at=observed_at,
            now=now,
            query=f"""
            UPDATE knowledge_graph
            SET status = ?, deprecated_by = ?, deprecated_at = ?, updated_at = ?
            WHERE subject_id = ? AND predicate IN ({placeholders}) AND triple_id != ? AND status = 'active'
              AND (predicate != ? OR object_id != ?)
            """,
            args=(
                subject_id,
                *group_predicates,
                triple_id,
                predicate,
                object_id,
            ),
        )

    async def _apply_graph_status(
        self,
        *,
        db: aiosqlite.Connection,
        status: str,
        triple_id: str,
        observed_at: float,
        now: float,
        query: str,
        args: tuple[Any, ...],
    ) -> None:
        cursor = await db.execute(
            query,
            (
                status,
                triple_id,
                observed_at,
                now,
                *args,
            ),
        )
        if int(cursor.rowcount or 0) > 0:
            logger.debug(
                "L2 graph conflict applied",
                source_triple_id=triple_id,
                next_status=status,
                affected_count=int(cursor.rowcount or 0),
            )

    def _status_from_action(self, action: str) -> str:
        if action == "mark_conflicted":
            return "conflicted"
        return "deprecated"

    async def _seed_default_graph_conflict_rules(self, db: aiosqlite.Connection) -> None:
        now = time.time()
        seed_rules = build_graph_conflict_matrix(self._seed_graph_conflict_rules)
        for predicate, rule in seed_rules.items():
            await db.execute(
                """
                INSERT OR IGNORE INTO graph_conflict_rules(
                    predicate, opposite_predicates, opposite_resolution, exclusive_group,
                    exclusive_scope, exclusive_resolution, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    predicate,
                    json.dumps(list(rule.opposite_predicates), ensure_ascii=False),
                    rule.opposite_resolution,
                    rule.exclusive_group,
                    rule.exclusive_scope,
                    rule.exclusive_resolution,
                    now,
                    now,
                ),
            )

    async def _reload_graph_conflict_rules(self, db: aiosqlite.Connection) -> None:
        db.row_factory = aiosqlite.Row
        rules: dict[str, GraphConflictRule] = {}
        async with db.execute(
            """
            SELECT predicate, opposite_predicates, opposite_resolution,
                   exclusive_group, exclusive_scope, exclusive_resolution
            FROM graph_conflict_rules
            ORDER BY predicate ASC
            """
        ) as cursor:
            rows = await cursor.fetchall()
        for row in rows:
            rule = GraphConflictRule.from_mapping(dict(row))
            rules[rule.predicate] = rule

        if not rules:
            rules = dict(DEFAULT_GRAPH_CONFLICT_RULES)

        self._graph_conflict_rules = rules
        self._exclusive_group_index = build_exclusive_group_index(self._graph_conflict_rules)

    def _entity_identity(self, event: MemoryEvent) -> tuple[Optional[str], Optional[str]]:
        if event.user_id:
            return (f"user:{event.user_id}", "user")
        return (None, None)

    def _assertion_row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]:
        columns = set(row.keys())
        return {
            "assertion_id": str(row["assertion_id"]),
            "entity_id": str(row["entity_id"]),
            "entity_type": str(row["entity_type"]),
            "trait_family": str(row["trait_family"]),
            "trait_name": str(row["trait_name"]),
            "trait_value": str(row["trait_value"]),
            "confidence_score": float(row["confidence_score"]),
            "evidence_events": json.loads(row["evidence_events"] or "[]"),
            "volatility_index": float(row["volatility_index"]),
            "source_domain": str(row["source_domain"]),
            "inference_depth": str(row["inference_depth"]),
            "validation_state": str(row["validation_state"]),
            "first_inferred_at": float(row["first_inferred_at"]),
            "last_validated_at": float(row["last_validated_at"]),
            "target_entity_id": str(row["target_entity_id"] or ""),
            "target_entity_type": str(row["target_entity_type"] or ""),
            "target_scope": str(row["target_scope"] or "global"),
            "temporal_scope": str(row["temporal_scope"] or "session"),
            "decay_policy": row["decay_policy"],
            "decay_anchor_at": float(row["decay_anchor_at"]) if row["decay_anchor_at"] else None,
            "context_ref_id": str(row["context_ref_id"] or ""),
            "expires_at": float(row["expires_at"]) if row["expires_at"] else None,
            "user_feedback": str(row["user_feedback"]) if "user_feedback" in columns and row["user_feedback"] else None,
            "user_feedback_at": float(row["user_feedback_at"]) if "user_feedback_at" in columns and row["user_feedback_at"] else None,
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }

    def _snapshot_row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]:
        columns = set(row.keys())
        return {
            "snapshot_id": str(row["snapshot_id"]),
            "entity_id": str(row["entity_id"]),
            "entity_type": str(row["entity_type"]),
            "core_traits": json.loads(row["core_traits"] or "{}"),
            "sensitive_triggers": json.loads(row["sensitive_triggers"] or "[]"),
            "preferences": json.loads(row["preferences"] or "{}"),
            "public_sentiment_profile": json.loads(row["public_sentiment_profile"] or "{}"),
            "relationship_topology": json.loads(row["relationship_topology"] or "{}"),
            "current_stress_level": float(row["current_stress_level"] or 0.0),
            "current_mood": row["current_mood"],
            "current_engagement": float(row["current_engagement"] or 0.5),
            "current_context": json.loads(row["current_context"] or "{}"),
            "interaction_count": int(row["interaction_count"] or 0),
            "last_interaction_at": float(row["last_interaction_at"]) if row["last_interaction_at"] else None,
            "last_updated_at": float(row["last_updated_at"]),
            "update_source_assertion_ids": json.loads(row["update_source_assertion_ids"] or "[]"),
            "core_traits_history": json.loads(row["core_traits_history"] or "[]") if "core_traits_history" in columns else [],
            "preferences_history": json.loads(row["preferences_history"] or "[]") if "preferences_history" in columns else [],
            "relationship_history": json.loads(row["relationship_history"] or "[]") if "relationship_history" in columns else [],
            "last_evolution_at": (
                float(row["last_evolution_at"])
                if "last_evolution_at" in columns and row["last_evolution_at"] is not None
                else None
            ),
            "active_record_ids": json.loads(row["active_record_ids"] or "[]") if "active_record_ids" in columns else [],
            "superseded_record_ids": (
                json.loads(row["superseded_record_ids"] or "[]") if "superseded_record_ids" in columns else []
            ),
            "snapshot_version": int(row["snapshot_version"] or 1),
            "created_at": float(row["created_at"]),
        }

    def _relation_row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]:
        columns = set(row.keys()) if hasattr(row, "keys") else set()
        return {
            "triple_id": str(row["triple_id"]),
            "subject_id": str(row["subject_id"]),
            "subject_type": str(row["subject_type"]),
            "predicate": str(row["predicate"]),
            "object_id": str(row["object_id"]),
            "object_type": str(row["object_type"]),
            "fact_kind": str(row["fact_kind"]),
            "confidence": float(row["confidence"]),
            "evidence_event_ids": json.loads(row["evidence_event_ids"] or "[]"),
            "observation_count": int(row["observation_count"]),
            "first_observed_at": float(row["first_observed_at"]),
            "last_observed_at": float(row["last_observed_at"]),
            "last_confirmed_at": float(row["last_confirmed_at"]) if row["last_confirmed_at"] else None,
            "source_type": row["source_type"],
            "extraction_method": row["extraction_method"],
            "evidence_text": str(row["evidence_text"] or "") if "evidence_text" in columns else "",
            "natural_summary": str(row["natural_summary"] or "") if "natural_summary" in columns else "",
            "embedding_status": str(row["embedding_status"] or "pending") if "embedding_status" in columns else "pending",
            "expires_at": float(row["expires_at"]) if "expires_at" in columns and row["expires_at"] else None,
            "status": str(row["status"]),
            "deprecated_by": row["deprecated_by"],
            "deprecated_at": float(row["deprecated_at"]) if row["deprecated_at"] else None,
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }

    def _facet_row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]:
        return {
            "entity_id": str(row["entity_id"]),
            "entity_type": str(row["entity_type"]),
            "facet_name": str(row["facet_name"]),
            "facet_value": str(row["facet_value"]),
            "confidence": float(row["confidence"]),
            "evidence_event_ids": json.loads(row["evidence_event_ids"] or "[]"),
            "source_type": row["source_type"],
            "extraction_method": row["extraction_method"],
        }

    async def _ensure_knowledge_graph_columns(self, db: aiosqlite.Connection) -> None:
        """Backfill additive columns for older knowledge_graph schemas."""
        db.row_factory = aiosqlite.Row
        async with db.execute("PRAGMA table_info(knowledge_graph)") as cursor:
            rows = await cursor.fetchall()
        columns = {str(row["name"]) for row in rows}
        if "fact_kind" not in columns:
            await db.execute(
                "ALTER TABLE knowledge_graph ADD COLUMN fact_kind TEXT NOT NULL DEFAULT 'explicit_fact'"
            )
        if "evidence_text" not in columns:
            await db.execute("ALTER TABLE knowledge_graph ADD COLUMN evidence_text TEXT DEFAULT ''")
        if "natural_summary" not in columns:
            await db.execute("ALTER TABLE knowledge_graph ADD COLUMN natural_summary TEXT DEFAULT ''")
        if "embedding_status" not in columns:
            await db.execute("ALTER TABLE knowledge_graph ADD COLUMN embedding_status TEXT DEFAULT 'pending'")
        if "expires_at" not in columns:
            await db.execute("ALTER TABLE knowledge_graph ADD COLUMN expires_at REAL")


__all__ = ["L2CognitionStore"]
