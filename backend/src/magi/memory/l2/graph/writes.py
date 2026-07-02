"""Knowledge-graph write helpers for the L2 cognition store."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, replace
from typing import Any, Iterable, List, Mapping, Protocol, cast

import aiosqlite

from ....core.logger import get_logger
from ....core.sqlite import sqlite_connection_async
from ..ontology import are_predicates_synonymous
from ..storage.utils import (
    DEFAULT_FUTURE_INTENT_TTL_SECONDS,
    accumulate_confidence,
    max_evidence_event_ids,
    normalize_store_entity_ref,
    normalize_store_entity_type,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class _KnowledgeEdgeWrite:
    subject_id: str
    subject_type: str
    predicate: str
    object_id: str
    object_type: str
    fact_kind: str
    evidence_event_ids: list[str]
    confidence: float
    observed_at: float
    source_type: str
    extraction_method: str
    evidence_text: str
    expires_at: float | None
    valid_from: float | None
    valid_to: float | None
    evidence_class: str | None
    now: float

    @property
    def triple_id(self) -> str:
        triple_key = f"{self.subject_id}:{self.predicate}:{self.object_id}"
        return f"triple_{uuid.uuid5(uuid.NAMESPACE_DNS, triple_key)}"

    @property
    def insert_valid_from(self) -> float:
        return self.valid_from if self.valid_from is not None else self.observed_at

    @property
    def natural_summary(self) -> str:
        return _edge_natural_summary(self)


@dataclass(frozen=True)
class _KnowledgeEdgeInput:
    subject_id: str
    subject_type: str
    predicate: str
    object_id: str
    object_type: str
    fact_kind: str | None
    evidence_event_ids: list[str]
    confidence: float
    observed_at: float
    source_type: str
    extraction_method: str
    evidence_text: str
    expires_at: float | None
    valid_from: float | None
    valid_to: float | None
    evidence_class: str | None


@dataclass(frozen=True)
class _MergedEdgeEvidence:
    event_ids: list[str]
    observation_count: int
    confidence: float
    first_observed_at: float
    last_observed_at: float


def _normalize_evidence_class(evidence_class: str | None) -> str | None:
    if evidence_class is None:
        return None
    stripped_evidence_class = str(evidence_class).strip()
    return stripped_evidence_class or None


def _normalize_edge_evidence_text(evidence_text: str) -> str:
    return str(evidence_text).strip() if evidence_text else ""


def _optional_mapping_text(mapping: Mapping[str, Any], key: str) -> str | None:
    if mapping.get(key) is None:
        return None
    return str(mapping[key]).strip() or None


def _optional_mapping_float(mapping: Mapping[str, Any], key: str) -> float | None:
    if mapping.get(key) is None:
        return None
    return float(mapping[key])


def _edge_natural_summary(
    write: _KnowledgeEdgeWrite,
    *,
    evidence_text: str | None = None,
) -> str:
    effective_evidence_text = write.evidence_text if evidence_text is None else evidence_text
    return effective_evidence_text or f"{write.subject_id} {write.predicate} {write.object_id}"


def _bounded_evidence_ids(evidence_ids: set[str]) -> list[str]:
    merged_evidence = sorted(evidence_ids)
    evidence_cap = max_evidence_event_ids()
    if len(merged_evidence) > evidence_cap:
        return merged_evidence[-evidence_cap:]
    return merged_evidence


def _merge_edge_evidence(
    *,
    existing: Mapping[str, Any],
    new_event_ids: list[str],
    new_confidence: float,
    observed_at: float,
) -> _MergedEdgeEvidence:
    existing_evidence = set(json.loads(existing["evidence_event_ids"] or "[]"))
    merged_set = existing_evidence.union(new_event_ids)
    event_ids = _bounded_evidence_ids(merged_set)

    # Only count corroboration when genuinely new evidence arrived. Replays
    # (requeue, stale-job retry, overlapping windows) re-apply identical
    # evidence; bumping unconditionally inflates confidence/observation_count
    # without new support and is irreversible (#137).
    evidence_grew = len(merged_set) > len(existing_evidence)
    old_confidence = float(existing["confidence"])
    if evidence_grew:
        observation_count = int(existing["observation_count"]) + 1
        accumulated_confidence = accumulate_confidence(old_confidence, new_confidence)
    else:
        observation_count = int(existing["observation_count"])
        accumulated_confidence = old_confidence

    return _MergedEdgeEvidence(
        event_ids=event_ids,
        observation_count=observation_count,
        confidence=accumulated_confidence,
        first_observed_at=min(float(existing["first_observed_at"]), observed_at),
        last_observed_at=max(float(existing["last_observed_at"]), observed_at),
    )


def _prefer_longer_evidence_text(*, existing: str, new: str) -> str:
    return new if len(new) > len(existing) else existing


class _GraphWriteHostProtocol(Protocol):
    db_path: str

    async def initialize(self) -> None: ...

    def _validate_fact_kind(
        self,
        fact_kind: str,
        extraction_method: str,
        confidence: float,
    ) -> str: ...

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
    ) -> None: ...


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
        valid_from: float | None = None,
        valid_to: float | None = None,
        evidence_class: str | None = None,
    ) -> str:
        """Insert or refresh a knowledge-graph edge."""
        host = cast(_GraphWriteHostProtocol, self)
        await host.initialize()

        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            triple_id = await self._upsert_knowledge_edge_on_connection(
                db=db,
                edge=_KnowledgeEdgeInput(
                    subject_id=subject_id,
                    subject_type=subject_type,
                    predicate=predicate,
                    object_id=object_id,
                    object_type=object_type,
                    fact_kind=fact_kind,
                    evidence_event_ids=evidence_event_ids,
                    confidence=confidence,
                    observed_at=observed_at,
                    source_type=source_type,
                    extraction_method=extraction_method,
                    evidence_text=evidence_text,
                    expires_at=expires_at,
                    valid_from=valid_from,
                    valid_to=valid_to,
                    evidence_class=evidence_class,
                ),
            )
            await db.commit()
        return triple_id

    async def upsert_knowledge_edges(self, edge_writes: Iterable[Mapping[str, Any]]) -> list[str]:
        """Insert or refresh multiple knowledge-graph edges in one transaction."""
        host = cast(_GraphWriteHostProtocol, self)
        await host.initialize()

        triple_ids: list[str] = []
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            for edge_write in edge_writes:
                triple_ids.append(
                    await self._upsert_knowledge_edge_on_connection(
                        db=db,
                        edge=self._knowledge_edge_input_from_mapping(edge_write),
                    )
                )
            await db.commit()
        return triple_ids

    @staticmethod
    def _knowledge_edge_input_from_mapping(edge_write: Mapping[str, Any]) -> _KnowledgeEdgeInput:
        return _KnowledgeEdgeInput(
            subject_id=str(edge_write["subject_id"]),
            subject_type=str(edge_write["subject_type"]),
            predicate=str(edge_write["predicate"]),
            object_id=str(edge_write["object_id"]),
            object_type=str(edge_write["object_type"]),
            fact_kind=_optional_mapping_text(edge_write, "fact_kind"),
            evidence_event_ids=[str(item) for item in edge_write.get("evidence_event_ids", [])],
            confidence=float(edge_write["confidence"]),
            observed_at=float(edge_write["observed_at"]),
            source_type=str(edge_write["source_type"]),
            extraction_method=str(edge_write.get("extraction_method") or "rule"),
            evidence_text=str(edge_write.get("evidence_text") or ""),
            expires_at=_optional_mapping_float(edge_write, "expires_at"),
            valid_from=_optional_mapping_float(edge_write, "valid_from"),
            valid_to=_optional_mapping_float(edge_write, "valid_to"),
            evidence_class=_optional_mapping_text(edge_write, "evidence_class"),
        )

    async def _upsert_knowledge_edge_on_connection(
        self,
        *,
        db: aiosqlite.Connection,
        edge: _KnowledgeEdgeInput,
    ) -> str:
        host = cast(_GraphWriteHostProtocol, self)
        write = self._build_knowledge_edge_write(
            host=host,
            edge=edge,
        )
        write = await self._canonicalize_edge_predicate(db=db, write=write)
        triple_id = write.triple_id

        existing = await self._fetch_existing_knowledge_edge(db=db, triple_id=triple_id)
        if existing:
            await self._update_existing_knowledge_edge(
                db=db,
                triple_id=triple_id,
                write=write,
                existing=existing,
            )
        else:
            await self._insert_knowledge_edge(db=db, triple_id=triple_id, write=write)
        await host._resolve_graph_conflicts(
            db=db,
            triple_id=triple_id,
            subject_id=write.subject_id,
            predicate=write.predicate,
            object_id=write.object_id,
            observed_at=write.observed_at,
            now=write.now,
        )
        logger.debug(
            "L2 knowledge edge upserted",
            triple_id=triple_id,
            subject_id=write.subject_id,
            predicate=write.predicate,
            object_id=write.object_id,
            confidence=write.confidence,
            source_type=write.source_type,
            extraction_method=write.extraction_method,
        )
        return triple_id

    def _build_knowledge_edge_write(
        self,
        *,
        host: _GraphWriteHostProtocol,
        edge: _KnowledgeEdgeInput,
    ) -> _KnowledgeEdgeWrite:
        observed_at_float = float(edge.observed_at)
        confidence_float = float(edge.confidence)
        normalized_fact_kind = str(edge.fact_kind).strip() if edge.fact_kind is not None else ""
        normalized_fact_kind = host._validate_fact_kind(
            normalized_fact_kind,
            edge.extraction_method,
            confidence_float,
        )

        effective_expires_at = edge.expires_at
        if normalized_fact_kind == "future_intent" and effective_expires_at is None:
            effective_expires_at = observed_at_float + DEFAULT_FUTURE_INTENT_TTL_SECONDS

        normalized_subject_type = (
            normalize_store_entity_type(edge.subject_type) or edge.subject_type
        )
        normalized_object_type = normalize_store_entity_type(edge.object_type) or edge.object_type
        normalized_object_id = (
            normalize_store_entity_ref(edge.object_id, normalized_object_type) or edge.object_id
        )

        return _KnowledgeEdgeWrite(
            subject_id=edge.subject_id,
            subject_type=normalized_subject_type,
            predicate=edge.predicate,
            object_id=normalized_object_id,
            object_type=normalized_object_type,
            fact_kind=normalized_fact_kind,
            evidence_event_ids=list(edge.evidence_event_ids),
            confidence=confidence_float,
            observed_at=observed_at_float,
            source_type=edge.source_type,
            extraction_method=edge.extraction_method,
            evidence_text=_normalize_edge_evidence_text(edge.evidence_text),
            expires_at=effective_expires_at,
            valid_from=float(edge.valid_from) if edge.valid_from is not None else None,
            valid_to=float(edge.valid_to) if edge.valid_to is not None else None,
            evidence_class=_normalize_evidence_class(edge.evidence_class),
            now=time.time(),
        )

    async def _canonicalize_edge_predicate(
        self,
        *,
        db: aiosqlite.Connection,
        write: _KnowledgeEdgeWrite,
    ) -> _KnowledgeEdgeWrite:
        async with db.execute(
            "SELECT triple_id, predicate, observation_count FROM knowledge_graph "
            "WHERE subject_id = ? AND object_id = ? AND status IN ('active', 'archived')",
            (write.subject_id, write.object_id),
        ) as cursor:
            same_pair_edges = await cursor.fetchall()

        synonym_match = self._first_synonymous_edge(
            same_pair_edges,
            requested_predicate=write.predicate,
        )
        if synonym_match is None:
            return write

        canonical_predicate = str(synonym_match["predicate"])
        logger.debug(
            "L2 same-pair interception: reusing synonymous predicate",
            subject_id=write.subject_id,
            object_id=write.object_id,
            requested_predicate=write.predicate,
            canonical_predicate=canonical_predicate,
        )
        return replace(write, predicate=canonical_predicate)

    @staticmethod
    def _first_synonymous_edge(
        same_pair_edges: list[Mapping[str, Any]],
        *,
        requested_predicate: str,
    ) -> Mapping[str, Any] | None:
        synonym_match: Mapping[str, Any] | None = None
        for row in same_pair_edges:
            existing_predicate = str(row["predicate"])
            if existing_predicate == requested_predicate:
                return None
            if synonym_match is None and are_predicates_synonymous(
                existing_predicate,
                requested_predicate,
            ):
                synonym_match = row
        return synonym_match

    @staticmethod
    async def _fetch_existing_knowledge_edge(
        *,
        db: aiosqlite.Connection,
        triple_id: str,
    ) -> Mapping[str, Any] | None:
        async with db.execute(
            "SELECT confidence, evidence_event_ids, observation_count, first_observed_at, "
            "last_observed_at, fact_kind, evidence_text FROM knowledge_graph "
            "WHERE triple_id = ?",
            (triple_id,),
        ) as cursor:
            return cast(Mapping[str, Any] | None, await cursor.fetchone())

    @staticmethod
    async def _update_existing_knowledge_edge(
        *,
        db: aiosqlite.Connection,
        triple_id: str,
        write: _KnowledgeEdgeWrite,
        existing: Mapping[str, Any],
    ) -> None:
        merged = _merge_edge_evidence(
            existing=existing,
            new_event_ids=write.evidence_event_ids,
            new_confidence=write.confidence,
            observed_at=write.observed_at,
        )
        effective_fact_kind = (
            write.fact_kind or str(existing["fact_kind"] or "").strip() or "explicit_fact"
        )
        effective_evidence_text = _prefer_longer_evidence_text(
            existing=str(existing["evidence_text"] or ""),
            new=write.evidence_text,
        )
        natural_summary = _edge_natural_summary(
            write,
            evidence_text=effective_evidence_text,
        )

        await db.execute(
            """
            UPDATE knowledge_graph
            SET fact_kind = ?, confidence = ?, evidence_event_ids = ?, observation_count = ?,
                first_observed_at = ?, last_observed_at = ?, last_confirmed_at = ?, source_type = ?,
                extraction_method = ?, evidence_text = ?, natural_summary = ?,
                embedding_status = 'pending', expires_at = COALESCE(?, expires_at),
                valid_from = COALESCE(?, valid_from), valid_to = COALESCE(?, valid_to),
                evidence_class = COALESCE(?, evidence_class),
                updated_at = ?, status = 'active'
            WHERE triple_id = ?
            """,
            (
                effective_fact_kind,
                merged.confidence,
                json.dumps(merged.event_ids, ensure_ascii=False),
                merged.observation_count,
                merged.first_observed_at,
                merged.last_observed_at,
                write.observed_at,
                write.source_type,
                write.extraction_method,
                effective_evidence_text,
                natural_summary,
                write.expires_at,
                write.valid_from,
                write.valid_to,
                write.evidence_class,
                write.now,
                triple_id,
            ),
        )

    @staticmethod
    async def _insert_knowledge_edge(
        *,
        db: aiosqlite.Connection,
        triple_id: str,
        write: _KnowledgeEdgeWrite,
    ) -> None:
        await db.execute(
            """
            INSERT INTO knowledge_graph(
                triple_id, subject_id, subject_type, predicate, object_id, object_type,
                fact_kind, confidence, evidence_event_ids, observation_count, first_observed_at,
                last_observed_at, last_confirmed_at, source_type, extraction_method,
                evidence_text, natural_summary, embedding_status, expires_at,
                valid_from, valid_to, status, evidence_class,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, 'active', ?, ?, ?)
            """,
            (
                triple_id,
                write.subject_id,
                write.subject_type,
                write.predicate,
                write.object_id,
                write.object_type,
                write.fact_kind or "explicit_fact",
                write.confidence,
                json.dumps(sorted(set(write.evidence_event_ids)), ensure_ascii=False),
                1,
                write.observed_at,
                write.observed_at,
                write.observed_at,
                write.source_type,
                write.extraction_method,
                write.evidence_text,
                write.natural_summary,
                write.expires_at,
                write.insert_valid_from,
                write.valid_to,
                write.evidence_class,
                write.now,
                write.now,
            ),
        )

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

            merged = _merge_edge_evidence(
                existing=existing,
                new_event_ids=evidence_event_ids,
                new_confidence=float(new_confidence),
                observed_at=float(observed_at),
            )
            new_evidence_text = str(evidence_text).strip() if evidence_text else ""
            existing_evidence_text = str(existing["evidence_text"] or "")
            effective_evidence_text = _prefer_longer_evidence_text(
                existing=existing_evidence_text,
                new=new_evidence_text,
            )

            await db.execute(
                """
                UPDATE knowledge_graph
                SET confidence = ?, evidence_event_ids = ?, observation_count = ?,
                    first_observed_at = ?, last_observed_at = ?, last_confirmed_at = ?,
                    evidence_text = ?, embedding_status = 'pending', updated_at = ?
                WHERE triple_id = ?
                """,
                (
                    merged.confidence,
                    json.dumps(merged.event_ids, ensure_ascii=False),
                    merged.observation_count,
                    merged.first_observed_at,
                    merged.last_observed_at,
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
            new_observation_count=merged.observation_count,
            accumulated_confidence=merged.confidence,
        )
        return True
