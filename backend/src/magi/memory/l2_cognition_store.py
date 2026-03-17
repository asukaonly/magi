"""Unified L2 cognition store for graph facts and defensive ToM assertions."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import aiosqlite

from ..core.logger import get_logger
from .event_contracts import MemoryEvent, TomDepth
from .l2_graph_conflicts import DEFAULT_GRAPH_CONFLICT_RULES, GraphConflictRule, build_exclusive_group_index, build_graph_conflict_matrix, iter_opposite_predicates
from .l2_models import ContradictionHint, ReconciledTraitOutcome
from .l2_ontology import coerce_unknown_entity_type

_STRESS_KEYWORDS = ("stress", "stressed", "anxious", "anxiety", "pressure")
_CALM_KEYWORDS = ("calm", "relaxed", "relief", "peaceful")
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


class L2CognitionStore:
    """Persists structured cognition artifacts derived from L1 events."""

    def __init__(
        self,
        *,
        db_path: str = "~/.magi/data/memories/memory.db",
        graph_conflict_rules: Mapping[str, GraphConflictRule | Mapping[str, Any]] | None = None,
    ) -> None:
        self.db_path = str(Path(db_path).expanduser())
        self._initialized = False
        self._seed_graph_conflict_rules = build_graph_conflict_matrix(graph_conflict_rules)
        self._graph_conflict_rules = dict(self._seed_graph_conflict_rules)
        self._exclusive_group_index = build_exclusive_group_index(self._graph_conflict_rules)

    async def initialize(self) -> None:
        """Create the cognition schema."""
        if self._initialized:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_graph (
                    triple_id TEXT PRIMARY KEY,
                    subject_id TEXT NOT NULL,
                    subject_type TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    object_type TEXT NOT NULL,
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

                CREATE TABLE IF NOT EXISTS tom_trait_assertions (
                    assertion_id TEXT PRIMARY KEY,
                    entity_id TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
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
                    expires_at REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(entity_id, entity_type, trait_name)
                );

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
        async with aiosqlite.connect(self.db_path) as db:
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

    async def apply_memory_event(self, event: MemoryEvent) -> Dict[str, int]:
        """Extract graph and ToM candidates from a normalized memory event."""
        await self.initialize()
        relation_count = 0
        assertion_count = 0

        for candidate in self.extract_graph_candidates(event):
            await self.upsert_knowledge_edge(**candidate)
            relation_count += 1

        for candidate in self.extract_assertion_candidates(event):
            await self.upsert_assertion_candidate(candidate)
            assertion_count += 1

        return {"relation_count": relation_count, "assertion_count": assertion_count}

    def extract_graph_candidates(self, event: MemoryEvent) -> List[Dict[str, Any]]:
        """Expose the legacy explicit-fact extraction rules."""
        return self._extract_graph_candidates(event)

    def extract_assertion_candidates(self, event: MemoryEvent) -> List[Dict[str, Any]]:
        """Expose the legacy defensive ToM extraction rules."""
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
        evidence_event_ids: List[str],
        confidence: float,
        observed_at: float,
        source_type: str,
        extraction_method: str = "rule",
    ) -> str:
        """Insert or refresh a knowledge-graph edge."""
        await self.initialize()
        normalized_subject_type = _normalize_store_entity_type(subject_type) or subject_type
        normalized_object_type = _normalize_store_entity_type(object_type) or object_type
        normalized_object_id = _normalize_store_entity_ref(object_id, normalized_object_type) or object_id
        now = time.time()
        triple_id = f"triple_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{subject_id}:{predicate}:{normalized_object_id}')}"

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT evidence_event_ids, observation_count, first_observed_at FROM knowledge_graph WHERE triple_id = ?",
                (triple_id,),
            ) as cursor:
                existing = await cursor.fetchone()

            if existing:
                merged_evidence = sorted(
                    set(json.loads(existing["evidence_event_ids"] or "[]")).union(evidence_event_ids)
                )
                observation_count = int(existing["observation_count"]) + 1
                first_observed_at = float(existing["first_observed_at"])
                await db.execute(
                    """
                    UPDATE knowledge_graph
                    SET confidence = ?, evidence_event_ids = ?, observation_count = ?,
                        last_observed_at = ?, last_confirmed_at = ?, source_type = ?,
                        extraction_method = ?, updated_at = ?
                    WHERE triple_id = ?
                    """,
                    (
                        float(confidence),
                        json.dumps(merged_evidence, ensure_ascii=False),
                        observation_count,
                        float(observed_at),
                        float(observed_at),
                        source_type,
                        extraction_method,
                        now,
                        triple_id,
                    ),
                )
            else:
                await db.execute(
                    """
                    INSERT INTO knowledge_graph(
                        triple_id, subject_id, subject_type, predicate, object_id, object_type,
                        confidence, evidence_event_ids, observation_count, first_observed_at,
                        last_observed_at, last_confirmed_at, source_type, extraction_method,
                        status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                    """,
                    (
                        triple_id,
                        subject_id,
                        normalized_subject_type,
                        predicate,
                        normalized_object_id,
                        normalized_object_type,
                        float(confidence),
                        json.dumps(sorted(set(evidence_event_ids)), ensure_ascii=False),
                        1,
                        float(observed_at),
                        float(observed_at),
                        float(observed_at),
                        source_type,
                        extraction_method,
                        now,
                        now,
                    ),
            )
            await self._resolve_graph_conflicts(
                db=db,
                triple_id=triple_id,
                subject_id=subject_id,
                predicate=predicate,
                object_id=normalized_object_id,
                observed_at=float(observed_at),
                now=now,
            )
            await db.commit()
        logger.debug(
            "L2 knowledge edge upserted",
            triple_id=triple_id,
            subject_id=subject_id,
            predicate=predicate,
            object_id=normalized_object_id,
            confidence=float(confidence),
            source_type=source_type,
            extraction_method=extraction_method,
        )
        return triple_id

    async def list_tom_assertions(
        self,
        *,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
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
        query += " ORDER BY updated_at DESC LIMIT ?"
        args.append(int(limit))

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [self._assertion_row_to_dict(row) for row in rows]

    async def get_tom_snapshot(self, *, entity_id: str, entity_type: str) -> Optional[Dict[str, Any]]:
        """Fetch the current stable snapshot for an entity."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM tom_snapshots WHERE entity_id = ? AND entity_type = ?",
                (entity_id, entity_type),
            ) as cursor:
                row = await cursor.fetchone()
        return self._snapshot_row_to_dict(row) if row else None

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

        async with aiosqlite.connect(self.db_path) as db:
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
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query the knowledge graph."""
        await self.initialize()
        query = "SELECT * FROM knowledge_graph WHERE status = ?"
        args: list[Any] = [status]
        if subject_id:
            query += " AND subject_id = ?"
            args.append(subject_id)
        if object_id:
            query += " AND object_id = ?"
            args.append(object_id)
        query += " ORDER BY updated_at DESC LIMIT ?"
        args.append(int(limit))
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, tuple(args)) as cursor:
                rows = await cursor.fetchall()
        return [self._relation_row_to_dict(row) for row in rows]

    async def find_edges_by_event_id(self, event_id: str) -> List[Dict[str, Any]]:
        """Return graph edges that cite a specific event as evidence."""
        edges = await self.get_relationships(limit=500)
        return [edge for edge in edges if event_id in edge["evidence_event_ids"]]

    def get_statistics(self) -> Dict[str, Any]:
        """Return lightweight counts for API reporting."""
        return {
            "db_path": self.db_path,
        }

    async def clear(self) -> int:
        """Delete all cognition artifacts."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM tom_trait_assertions") as cursor:
                row = await cursor.fetchone()
                count = int(row[0]) if row else 0
            await db.executescript(
                """
                DELETE FROM knowledge_graph;
                DELETE FROM tom_trait_assertions;
                DELETE FROM tom_snapshots;
                """
            )
            await db.commit()
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
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if target_record_type == "tom_trait_assertion":
                async with db.execute(
                    "SELECT assertion_id, confidence_score FROM tom_trait_assertions WHERE assertion_id = ?",
                    (target_record_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                if row is None:
                    return False

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
    ) -> List[Dict[str, Any]]:
        """Re-evaluate assertion confidence and stability for one entity."""
        assertions = await self.list_tom_assertions(entity_id=entity_id, entity_type=entity_type, limit=500)
        if not assertions:
            return []

        normalized_entity_type = entity_type or assertions[0]["entity_type"]
        now = time.time()
        outcomes: list[dict[str, Any]] = []

        async with aiosqlite.connect(self.db_path) as db:
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
                    ).to_dict()
                )
            await db.commit()
        status_counts: dict[str, int] = {}
        for item in outcomes:
            status = str(item.get("status", "unknown"))
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
        outgoing = await self.get_relationships(subject_id=entity_id, limit=200)
        incoming = await self.get_relationships(object_id=entity_id, limit=200)
        active_assertions = [
            item
            for item in assertions
            if item["validation_state"] in {"stable", "corroborated"}
        ]
        if not assertions and not outgoing and not incoming:
            return None

        normalized_entity_type = entity_type or (assertions[0]["entity_type"] if assertions else entity_id.split(":", 1)[0])
        stable_assertions = [item for item in active_assertions if item["validation_state"] == "stable"]
        snapshot = await self._upsert_snapshot(
            entity_id=entity_id,
            entity_type=normalized_entity_type,
            assertions=active_assertions,
            stable_assertions=stable_assertions,
            outgoing_relations=outgoing,
            incoming_relations=incoming,
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

    def _extract_graph_candidates(self, event: MemoryEvent) -> List[Dict[str, Any]]:
        content = event.raw_content.lower()
        if " like " not in f" {content} ":
            return []
        subject_id, subject_type = self._entity_identity(event)
        if subject_id is None:
            return []
        return [
            {
                "subject_id": subject_id,
                "subject_type": subject_type,
                "predicate": "LIKES",
                "object_id": "topic:mentioned_preference",
                "object_type": "topic",
                "evidence_event_ids": [event.event_id],
                "confidence": 0.7,
                "observed_at": event.timestamp,
                "source_type": event.source,
                "extraction_method": "keyword_rule",
            }
        ]

    def _extract_assertion_candidates(self, event: MemoryEvent) -> List[Dict[str, Any]]:
        subject_id, subject_type = self._entity_identity(event)
        if subject_id is None:
            return []
        if not event.cognition_eligible or event.tom_depth != TomDepth.DEFENSIVE_PSYCHOLOGY:
            return []

        text = event.raw_content.lower()
        if any(keyword in text for keyword in _STRESS_KEYWORDS):
            return [
                {
                    "entity_id": subject_id,
                    "entity_type": subject_type,
                    "trait_name": "stress_level",
                    "trait_value": "high",
                    "confidence_score": 0.3,
                    "evidence_events": [event.event_id],
                    "volatility_index": 0.7,
                    "source_domain": event.memory_domain.label,
                    "inference_depth": event.tom_depth.label,
                    "validation_state": "tentative",
                    "first_inferred_at": event.timestamp,
                    "last_validated_at": event.timestamp,
                }
            ]
        if any(keyword in text for keyword in _CALM_KEYWORDS):
            return [
                {
                    "entity_id": subject_id,
                    "entity_type": subject_type,
                    "trait_name": "stress_level",
                    "trait_value": "low",
                    "confidence_score": 0.3,
                    "evidence_events": [event.event_id],
                    "volatility_index": 0.7,
                    "source_domain": event.memory_domain.label,
                    "inference_depth": event.tom_depth.label,
                    "validation_state": "tentative",
                    "first_inferred_at": event.timestamp,
                    "last_validated_at": event.timestamp,
                }
            ]
        return []

    async def _upsert_assertion(self, candidate: Dict[str, Any]) -> str:
        now = time.time()
        await self.initialize()
        normalized_entity_type = _normalize_store_entity_type(candidate.get("entity_type")) or "other"
        normalized_candidate = dict(candidate)
        normalized_candidate["entity_type"] = normalized_entity_type

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM tom_trait_assertions
                WHERE entity_id = ? AND entity_type = ? AND trait_name = ?
                """,
                (normalized_candidate["entity_id"], normalized_candidate["entity_type"], normalized_candidate["trait_name"]),
            ) as cursor:
                existing = await cursor.fetchone()

            if existing is None:
                assertion_id = f"assert_{uuid.uuid4().hex}"
                await db.execute(
                    """
                    INSERT INTO tom_trait_assertions(
                        assertion_id, entity_id, entity_type, trait_name, trait_value,
                        confidence_score, evidence_events, volatility_index, source_domain,
                        inference_depth, validation_state, first_inferred_at, last_validated_at,
                        expires_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        assertion_id,
                        normalized_candidate["entity_id"],
                        normalized_candidate["entity_type"],
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
                        None,
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
                    validation_state = ?, last_validated_at = ?, updated_at = ?
                WHERE assertion_id = ?
                """,
                (
                    next_value if existing_value != next_value else existing_value,
                    confidence,
                    json.dumps(evidence, ensure_ascii=False),
                    validation_state,
                    last_validated_at,
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
        async with aiosqlite.connect(self.db_path) as db:
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
        stable_assertions: List[Dict[str, Any]],
        outgoing_relations: List[Dict[str, Any]],
        incoming_relations: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        now = time.time()
        stable_by_trait = {item["trait_name"]: item for item in stable_assertions}
        active_by_trait = {item["trait_name"]: item for item in assertions}

        core_traits: dict[str, Any] = {}
        preferences: dict[str, Any] = {}
        sensitive_triggers: list[str] = []
        public_sentiment_profile: dict[str, Any] = {}

        current_stress_level = 0.0
        stress_assertion = active_by_trait.get("stress_level")
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
            "stable_assertion_count": len(stable_assertions),
            "relation_count": len(outgoing_relations) + len(incoming_relations),
        }
        update_source_assertion_ids = [item["assertion_id"] for item in assertions]
        last_interaction_at = max(
            [float(item["last_validated_at"]) for item in assertions] + [now]
        )
        interaction_count = max(1, len(assertions) + len(outgoing_relations) + len(incoming_relations))

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM tom_snapshots WHERE entity_id = ? AND entity_type = ?",
                (entity_id, entity_type),
            ) as cursor:
                existing = await cursor.fetchone()

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
                        update_source_assertion_ids, snapshot_version, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    def _derive_reconcile_state(
        self,
        *,
        current_state: str,
        current_confidence: float,
        evidence_count: int,
        time_span_hours: float,
        trait_name: str,
    ) -> tuple[str, float, str]:
        if current_state == "contradicted":
            return ("contradicted", min(current_confidence, 0.35), "volatile_pattern")

        if evidence_count >= 3 and time_span_hours >= 24.0:
            stability_kind = "temporary_state" if trait_name in {"stress_level", "mood", "engagement"} else "stable_trait"
            return ("stable", max(current_confidence, 0.82), stability_kind)

        if evidence_count >= 2:
            stability_kind = "temporary_state" if trait_name in {"stress_level", "mood", "engagement"} else "volatile_pattern"
            return ("corroborated", max(current_confidence, 0.58), stability_kind)

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
        return {
            "assertion_id": str(row["assertion_id"]),
            "entity_id": str(row["entity_id"]),
            "entity_type": str(row["entity_type"]),
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
            "expires_at": float(row["expires_at"]) if row["expires_at"] else None,
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }

    def _snapshot_row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]:
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
            "snapshot_version": int(row["snapshot_version"] or 1),
            "created_at": float(row["created_at"]),
        }

    def _relation_row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]:
        return {
            "triple_id": str(row["triple_id"]),
            "subject_id": str(row["subject_id"]),
            "subject_type": str(row["subject_type"]),
            "predicate": str(row["predicate"]),
            "object_id": str(row["object_id"]),
            "object_type": str(row["object_type"]),
            "confidence": float(row["confidence"]),
            "evidence_event_ids": json.loads(row["evidence_event_ids"] or "[]"),
            "observation_count": int(row["observation_count"]),
            "first_observed_at": float(row["first_observed_at"]),
            "last_observed_at": float(row["last_observed_at"]),
            "last_confirmed_at": float(row["last_confirmed_at"]) if row["last_confirmed_at"] else None,
            "source_type": row["source_type"],
            "extraction_method": row["extraction_method"],
            "status": str(row["status"]),
            "deprecated_by": row["deprecated_by"],
            "deprecated_at": float(row["deprecated_at"]) if row["deprecated_at"] else None,
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }


__all__ = ["L2CognitionStore"]
