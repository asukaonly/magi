"""Unified L2 cognition store for graph facts and defensive ToM assertions."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

from .event_contracts import MemoryEvent, TomDepth

_STRESS_KEYWORDS = ("stress", "stressed", "anxious", "anxiety", "pressure")
_CALM_KEYWORDS = ("calm", "relaxed", "relief", "peaceful")


class L2CognitionStore:
    """Persists structured cognition artifacts derived from L1 events."""

    def __init__(self, *, db_path: str = "~/.magi/data/memories/memory.db") -> None:
        self.db_path = str(Path(db_path).expanduser())
        self._initialized = False

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
                """
            )
            await db.commit()
        self._initialized = True

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
        now = time.time()
        triple_id = f"triple_{uuid.uuid5(uuid.NAMESPACE_DNS, f'{subject_id}:{predicate}:{object_id}')}"

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
                        subject_type,
                        predicate,
                        object_id,
                        object_type,
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
            await db.commit()
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

    async def get_relationships(
        self,
        *,
        subject_id: Optional[str] = None,
        object_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query the knowledge graph."""
        await self.initialize()
        query = "SELECT * FROM knowledge_graph WHERE status = 'active'"
        args: list[Any] = []
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

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM tom_trait_assertions
                WHERE entity_id = ? AND entity_type = ? AND trait_name = ?
                """,
                (candidate["entity_id"], candidate["entity_type"], candidate["trait_name"]),
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
                        candidate["entity_id"],
                        candidate["entity_type"],
                        candidate["trait_name"],
                        candidate["trait_value"],
                        float(candidate["confidence_score"]),
                        json.dumps(candidate["evidence_events"], ensure_ascii=False),
                        float(candidate["volatility_index"]),
                        candidate["source_domain"],
                        candidate["inference_depth"],
                        candidate["validation_state"],
                        float(candidate["first_inferred_at"]),
                        float(candidate["last_validated_at"]),
                        None,
                        now,
                        now,
                    ),
                )
                await db.commit()
                return assertion_id

            evidence = sorted(
                set(json.loads(existing["evidence_events"] or "[]")).union(candidate["evidence_events"])
            )
            first_inferred_at = float(existing["first_inferred_at"])
            last_validated_at = float(candidate["last_validated_at"])
            existing_value = str(existing["trait_value"])
            next_value = str(candidate["trait_value"])

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

        if validation_state == "stable":
            await self._materialize_snapshot(
                entity_id=candidate["entity_id"],
                entity_type=candidate["entity_type"],
                trait_name=candidate["trait_name"],
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
