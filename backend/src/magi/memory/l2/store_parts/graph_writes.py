"""Knowledge-graph write helpers for the L2 cognition store."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Protocol, cast

import aiosqlite

from ....core.logger import get_logger
from ....core.sqlite import sqlite_connection_async
from ..ontology import are_predicates_synonymous
from .utils import (
    DEFAULT_FUTURE_INTENT_TTL_SECONDS,
    MAX_EVIDENCE_EVENT_IDS,
    accumulate_confidence,
    normalize_store_entity_ref,
    normalize_store_entity_type,
)

logger = get_logger(__name__)


class _GraphWriteHostProtocol(Protocol):
    db_path: str

    async def initialize(self) -> None:
        ...

    def _validate_fact_kind(
        self,
        fact_kind: str,
        extraction_method: str,
        confidence: float,
    ) -> str:
        ...

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
        ...


class L2StoreGraphWriteMixin:
    """Insert, refresh, and corroborate knowledge-graph edges."""

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
        """Insert or refresh a knowledge-graph edge."""
        host = cast(_GraphWriteHostProtocol, self)
        await host.initialize()
        normalized_subject_type = normalize_store_entity_type(subject_type) or subject_type
        normalized_object_type = normalize_store_entity_type(object_type) or object_type
        normalized_object_id = normalize_store_entity_ref(object_id, normalized_object_type) or object_id
        normalized_fact_kind = str(fact_kind).strip() if fact_kind is not None else ""
        now = time.time()

        normalized_fact_kind = host._validate_fact_kind(
            normalized_fact_kind, extraction_method, confidence
        )

        effective_expires_at = expires_at
        if normalized_fact_kind == "future_intent" and effective_expires_at is None:
            effective_expires_at = float(observed_at) + DEFAULT_FUTURE_INTENT_TTL_SECONDS

        effective_predicate = predicate
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT triple_id, predicate, observation_count FROM knowledge_graph "
                "WHERE subject_id = ? AND object_id = ? AND status IN ('active', 'archived')",
                (subject_id, normalized_object_id),
            ) as cursor:
                same_pair_edges = await cursor.fetchall()

            if same_pair_edges:
                exact_match = None
                synonym_match = None
                for row in same_pair_edges:
                    existing_predicate = str(row["predicate"])
                    if existing_predicate == predicate:
                        exact_match = row
                        break
                    if synonym_match is None and are_predicates_synonymous(existing_predicate, predicate):
                        if synonym_match is None or int(row["observation_count"]) > int(synonym_match["observation_count"]):
                            synonym_match = row

                if exact_match is not None:
                    pass
                elif synonym_match is not None:
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

        async with sqlite_connection_async(host.db_path) as db:
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
                accumulated_confidence = accumulate_confidence(old_confidence, float(confidence))
                effective_fact_kind = normalized_fact_kind or str(existing["fact_kind"] or "").strip() or "explicit_fact"
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
            await host._resolve_graph_conflicts(
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
        """Accumulate confidence on an existing edge without creating a new triple."""
        host = cast(_GraphWriteHostProtocol, self)
        await host.initialize()
        now = time.time()
        async with sqlite_connection_async(host.db_path) as db:
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
            accumulated_confidence = accumulate_confidence(float(existing["confidence"]), float(new_confidence))
            first_observed_at = min(float(existing["first_observed_at"]), float(observed_at))
            last_observed_at = max(float(existing["last_observed_at"]), float(observed_at))
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
