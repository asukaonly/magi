"""Knowledge-graph write helpers for the L2 cognition store."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, replace
from typing import Any, Iterable, List, Mapping, Protocol, cast

import aiosqlite

from ....core.logger import get_logger
from ....core.sqlite import sqlite_connection_async
from ...context_scope import normalize_context_scope
from ..batch_models import L2ProjectionLease
from ..claims.outcomes import (
    ClaimTargetOutcomeContext,
    append_claim_target_outcomes_on_connection,
)
from ..corrections.evidence_ledger import append_claim_evidence_event_ids
from ..corrections.fingerprints import (
    canonical_scope_json,
    relationship_claim_fingerprint,
    relationship_slot_key,
    relationship_triple_id,
    scope_key,
)
from ..corrections.forget_governance import (
    append_forget_evidence_event_ids,
    filter_candidate_evidence_by_forget_rules,
)
from ..corrections.models import CorrectionTargetKind
from ..corrections.policy import (
    CORRECTION_GOVERNED_EVIDENCE_ACTIONS,
    CorrectionPolicyAction,
    CorrectionPolicyEvaluator,
)
from ..corrections.relationship_conflict_effects import (
    record_relationship_shadow_conflict_effect,
)
from ..corrections.repository import MemoryCorrectionRepository
from ..graph_conflicts import GraphConflictRule, relationship_predicate_slot
from ..projection.fencing import (
    assert_current_projection_attempt,
    normalize_projection_leases,
)
from .versions import append_knowledge_graph_version
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
    evidence_started_at: float
    confidence: float
    observed_at: float
    source_type: str
    extraction_method: str
    evidence_text: str
    evidence_text_attributable: bool
    expires_at: float | None
    valid_from: float | None
    valid_to: float | None
    evidence_class: str | None
    scope: Mapping[str, Any]
    scope_key: str
    scope_json: str
    slot_key: str
    claim_fingerprint: str
    now: float

    @property
    def triple_id(self) -> str:
        return str(
            relationship_triple_id(
                subject_id=self.subject_id,
                predicate=self.predicate,
                object_id=self.object_id,
                scope_key_value=self.scope_key,
            )
        )

    @property
    def insert_valid_from(self) -> float:
        return self.valid_from if self.valid_from is not None else self.evidence_started_at

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
    scope: object | None


@dataclass(frozen=True)
class _KnowledgeEdgeWriteResult:
    triple_id: str
    slot_key: str
    governance_action: CorrectionPolicyAction
    persisted: bool
    reason_code: str | None = None


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
    if not write.evidence_text_attributable:
        return ""
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


def _relationship_covers_observed_at(
    relationship: Mapping[str, Any],
    observed_at: float,
    *,
    require_closed: bool = False,
) -> bool:
    """Return whether evidence belongs to this relationship validity segment."""
    valid_from = (
        float(relationship["valid_from"]) if relationship["valid_from"] is not None else None
    )
    if valid_from is None:
        valid_from = (
            float(relationship["first_observed_at"])
            if relationship["first_observed_at"] is not None
            else None
        )
    valid_to = float(relationship["valid_to"]) if relationship["valid_to"] is not None else None
    expires_at = (
        float(relationship["expires_at"]) if relationship["expires_at"] is not None else None
    )
    if require_closed and valid_to is None:
        return False
    return (
        (valid_from is None or observed_at >= valid_from)
        and (valid_to is None or observed_at < valid_to)
        and (expires_at is None or observed_at < expires_at)
    )


class _GraphWriteHostProtocol(Protocol):
    db_path: str

    async def initialize(self) -> None: ...

    async def resolve_evidence_timestamps(
        self,
        event_ids: list[str],
    ) -> dict[str, float]: ...

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
        scope_key: str,
        observed_at: float,
        now: float,
    ) -> None: ...


class L2StoreGraphWriteMixin:
    """Insert, refresh, and corroborate knowledge-graph edges."""

    _graph_conflict_rules: Mapping[str, GraphConflictRule]

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
        scope: Mapping[str, Any] | None = None,
        projection_leases: Iterable[L2ProjectionLease] = (),
    ) -> str:
        """Insert or refresh a knowledge-graph edge."""
        host = cast(_GraphWriteHostProtocol, self)
        await host.initialize()
        lease_items = normalize_projection_leases(projection_leases, required=False)

        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                if lease_items:
                    await assert_current_projection_attempt(db, lease_items)
                result = await self._upsert_knowledge_edge_on_connection(
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
                        scope=scope,
                    ),
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        return result.triple_id

    async def upsert_knowledge_edge_with_receipt(
        self,
        edge_write: Mapping[str, Any],
        *,
        claim_outcome_context: ClaimTargetOutcomeContext,
        projection_leases: Iterable[L2ProjectionLease] = (),
    ) -> dict[str, Any]:
        """Atomically persist one edge, its Claim outcome, and a receipt."""

        host = cast(_GraphWriteHostProtocol, self)
        await host.initialize()
        lease_items = normalize_projection_leases(projection_leases, required=True)
        if len(claim_outcome_context.claim_ids) != 1:
            raise ValueError("graph receipts require exactly one supporting Claim")
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                await assert_current_projection_attempt(db, lease_items)
                result = await self._upsert_knowledge_edge_on_connection(
                    db=db,
                    edge=self._knowledge_edge_input_from_mapping(edge_write),
                )
                persisted = bool(result.persisted)
                reason_code = (
                    None if persisted else result.reason_code or result.governance_action.value
                )
                await append_claim_target_outcomes_on_connection(
                    db,
                    context=claim_outcome_context,
                    target_kind="relationship",
                    target_id=result.triple_id,
                    target_slot_key=result.slot_key,
                    outcome="projected" if persisted else "skipped",
                    reason_code=reason_code,
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        return {
            "triple_id": result.triple_id,
            "slot_key": result.slot_key,
            "governance_action": result.governance_action.value,
            "persisted": result.persisted,
            "reason_code": result.reason_code,
        }

    async def upsert_knowledge_edges(
        self,
        edge_writes: Iterable[Mapping[str, Any]],
        *,
        projection_leases: Iterable[L2ProjectionLease] = (),
    ) -> list[str]:
        """Insert or refresh multiple knowledge-graph edges in one transaction."""
        host = cast(_GraphWriteHostProtocol, self)
        await host.initialize()
        lease_items = normalize_projection_leases(projection_leases, required=False)

        triple_ids: list[str] = []
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                if lease_items:
                    await assert_current_projection_attempt(db, lease_items)
                for edge_write in edge_writes:
                    result = await self._upsert_knowledge_edge_on_connection(
                        db=db,
                        edge=self._knowledge_edge_input_from_mapping(edge_write),
                    )
                    triple_ids.append(result.triple_id)
                await db.commit()
            except Exception:
                await db.rollback()
                raise
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
            scope=edge_write.get("scope"),
        )

    async def _upsert_knowledge_edge_on_connection(
        self,
        *,
        db: aiosqlite.Connection,
        edge: _KnowledgeEdgeInput,
    ) -> _KnowledgeEdgeWriteResult:
        host = cast(_GraphWriteHostProtocol, self)
        write = self._build_knowledge_edge_write(
            host=host,
            edge=edge,
        )
        write = await self._canonicalize_edge_predicate(db=db, write=write)
        write = self._with_edge_governance_identity(write)
        triple_id = write.triple_id
        evidence_timestamps = await host.resolve_evidence_timestamps(write.evidence_event_ids)

        original_evidence = list(write.evidence_event_ids)
        semantic_fingerprint = relationship_claim_fingerprint(
            slot_key_value=write.slot_key,
            subject_id=write.subject_id,
            predicate=write.predicate,
            object_id=write.object_id,
        )
        filtered_evidence = await filter_candidate_evidence_by_forget_rules(
            db,
            target_kind=CorrectionTargetKind.EDGE,
            semantic_fingerprint=semantic_fingerprint,
            event_ids=original_evidence,
            event_timestamps=evidence_timestamps,
            observed_at=write.observed_at,
            observed_from=(write.valid_from if write.valid_from is not None else write.observed_at),
            observed_to=write.observed_at,
            entity_ids=(write.subject_id, write.object_id),
        )
        for rule_id, forgotten_event_ids in filtered_evidence.forgotten_by_rule.items():
            await append_forget_evidence_event_ids(
                db,
                rule_id=rule_id,
                event_ids=forgotten_event_ids,
                created_at=write.now,
            )
        if original_evidence and not filtered_evidence.retained_event_ids:
            logger.info(
                "L2 relationship candidate governed without current write",
                triple_id=triple_id,
                governance_action=CorrectionPolicyAction.BLOCKED_BY_FORGET.value,
            )
            return _KnowledgeEdgeWriteResult(
                triple_id=triple_id,
                slot_key=write.slot_key,
                governance_action=CorrectionPolicyAction.BLOCKED_BY_FORGET,
                persisted=False,
                reason_code="all_evidence_forgotten",
            )
        if filtered_evidence.has_forgotten_evidence:
            retained_bounds = filtered_evidence.retained_observation_bounds
            if retained_bounds is None:
                raise RuntimeError("Retained relationship evidence has no observation bounds")
            evidence_started_at, observed_at = retained_bounds
            write = replace(
                write,
                evidence_event_ids=list(filtered_evidence.retained_event_ids),
                evidence_started_at=evidence_started_at,
                observed_at=observed_at,
                evidence_text="",
                evidence_text_attributable=False,
            )
        else:
            normalized_timestamps = [
                filtered_evidence.normalized_timestamps[event_id]
                for event_id in filtered_evidence.retained_event_ids
            ]
            write = replace(
                write,
                evidence_event_ids=list(filtered_evidence.retained_event_ids),
                evidence_started_at=(
                    min(normalized_timestamps)
                    if normalized_timestamps
                    else write.evidence_started_at
                ),
            )

        await append_claim_evidence_event_ids(
            db,
            target_kind=CorrectionTargetKind.EDGE,
            claim_fingerprint=write.claim_fingerprint,
            event_ids=write.evidence_event_ids,
            observed_at=filtered_evidence.fallback_observed_at,
            created_at=write.now,
            event_timestamps=filtered_evidence.resolved_timestamps,
            observed_from=filtered_evidence.fallback_observed_from,
            observed_to=filtered_evidence.fallback_observed_to,
            mark_missing_timestamps_approximate=True,
        )
        policy = await CorrectionPolicyEvaluator().evaluate_relationship(
            db,
            {
                "slot_key": write.slot_key,
                "claim_fingerprint": write.claim_fingerprint,
                "forget_fingerprint": relationship_claim_fingerprint(
                    slot_key_value=write.slot_key,
                    subject_id=write.subject_id,
                    predicate=write.predicate,
                    object_id=write.object_id,
                ),
                "scope_key": write.scope_key,
                "last_validated_at": write.observed_at,
                "forget_prechecked": bool(original_evidence),
            },
        )
        if policy.action == CorrectionPolicyAction.BLOCKED_BY_FORGET:
            if not policy.forget_rule_id:
                raise RuntimeError("Forgotten relationship write has no governance identity")
            await append_forget_evidence_event_ids(
                db,
                rule_id=policy.forget_rule_id,
                event_ids=write.evidence_event_ids,
                created_at=write.now,
            )
        if policy.action in CORRECTION_GOVERNED_EVIDENCE_ACTIONS:
            if not policy.correction_id:
                raise RuntimeError("Governed relationship write has no correction identity")
            await MemoryCorrectionRepository(host.db_path).append_evidence_event_ids(
                db,
                correction_id=policy.correction_id,
                target_kind=CorrectionTargetKind.EDGE,
                event_ids=write.evidence_event_ids,
                created_at=write.now,
            )
        if policy.action in {
            CorrectionPolicyAction.BLOCKED_BY_CORRECTION,
            CorrectionPolicyAction.BLOCKED_BY_FORGET,
            CorrectionPolicyAction.REQUIRES_SCOPE,
        }:
            logger.info(
                "L2 relationship candidate governed without current write",
                triple_id=triple_id,
                correction_id=policy.correction_id,
                governance_action=policy.action.value,
            )
            return _KnowledgeEdgeWriteResult(
                triple_id=policy.target_id or triple_id,
                slot_key=write.slot_key,
                governance_action=policy.action,
                persisted=False,
                reason_code=policy.action.value,
            )
        if policy.action == CorrectionPolicyAction.ACCEPT_HISTORICAL:
            persisted = await self._merge_historical_relationship_version(
                db=db,
                triple_id=policy.target_id,
                write=write,
            )
            return _KnowledgeEdgeWriteResult(
                triple_id=policy.target_id or triple_id,
                slot_key=write.slot_key,
                governance_action=policy.action,
                persisted=persisted,
                reason_code=None if persisted else "historical_target_unavailable",
            )
        if policy.action == CorrectionPolicyAction.CREATE_SHADOW:
            assert policy.correction_id is not None
            await self._upsert_conflicted_relationship(
                db=db,
                triple_id=triple_id,
                write=write,
                correction_id=policy.correction_id,
                authoritative_triple_id=policy.authoritative_target_id,
            )
            return _KnowledgeEdgeWriteResult(
                triple_id=triple_id,
                slot_key=write.slot_key,
                governance_action=policy.action,
                persisted=True,
            )

        existing = await self._fetch_existing_knowledge_edge(db=db, triple_id=triple_id)
        if existing:
            if existing["authority_ref"]:
                if str(existing["scope_key"] or "global") != write.scope_key:
                    logger.info(
                        "L2 relationship scope mismatch left authoritative claim unchanged",
                        triple_id=triple_id,
                        existing_scope_key=str(existing["scope_key"] or "global"),
                        candidate_scope_key=write.scope_key,
                    )
                    return _KnowledgeEdgeWriteResult(
                        triple_id=triple_id,
                        slot_key=write.slot_key,
                        governance_action=policy.action,
                        persisted=False,
                        reason_code="authority_scope_mismatch",
                    )
                await self._merge_authoritative_relationship_evidence(
                    db=db,
                    triple_id=triple_id,
                    write=write,
                    existing=existing,
                )
            else:
                await self._update_existing_knowledge_edge(
                    db=db,
                    triple_id=triple_id,
                    write=write,
                    existing=existing,
                )
        else:
            await self._insert_knowledge_edge(db=db, triple_id=triple_id, write=write)
            await append_knowledge_graph_version(
                db,
                triple_id=triple_id,
                created_at=write.now,
            )
        await host._resolve_graph_conflicts(
            db=db,
            triple_id=triple_id,
            subject_id=write.subject_id,
            predicate=write.predicate,
            object_id=write.object_id,
            scope_key=write.scope_key,
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
        return _KnowledgeEdgeWriteResult(
            triple_id=triple_id,
            slot_key=write.slot_key,
            governance_action=policy.action,
            persisted=True,
        )

    def relationship_slot_key_for(
        self,
        *,
        subject_id: str,
        predicate: str,
        object_id: str,
    ) -> str:
        """Return the governed slot for a relationship candidate."""
        normalized_predicate = str(predicate).strip().upper()
        return str(
            relationship_slot_key(
                subject_id=subject_id,
                predicate=normalized_predicate,
                object_id=object_id,
                predicate_slot=relationship_predicate_slot(
                    self._graph_conflict_rules,
                    predicate=normalized_predicate,
                    object_id=object_id,
                ),
            )
        )

    def _with_edge_governance_identity(
        self,
        write: _KnowledgeEdgeWrite,
    ) -> _KnowledgeEdgeWrite:
        slot_key_value = self.relationship_slot_key_for(
            subject_id=write.subject_id,
            predicate=write.predicate,
            object_id=write.object_id,
        )
        return replace(
            write,
            slot_key=slot_key_value,
            claim_fingerprint=relationship_claim_fingerprint(
                slot_key_value=slot_key_value,
                subject_id=write.subject_id,
                predicate=write.predicate,
                object_id=write.object_id,
                scope_key_value=write.scope_key,
            ),
        )

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
        normalized_scope = normalize_context_scope(edge.scope)
        normalized_scope_key = scope_key(normalized_scope)

        return _KnowledgeEdgeWrite(
            subject_id=edge.subject_id,
            subject_type=normalized_subject_type,
            predicate=edge.predicate,
            object_id=normalized_object_id,
            object_type=normalized_object_type,
            fact_kind=normalized_fact_kind,
            evidence_event_ids=list(edge.evidence_event_ids),
            evidence_started_at=observed_at_float,
            confidence=confidence_float,
            observed_at=observed_at_float,
            source_type=edge.source_type,
            extraction_method=edge.extraction_method,
            evidence_text=_normalize_edge_evidence_text(edge.evidence_text),
            evidence_text_attributable=True,
            expires_at=effective_expires_at,
            valid_from=float(edge.valid_from) if edge.valid_from is not None else None,
            valid_to=float(edge.valid_to) if edge.valid_to is not None else None,
            evidence_class=_normalize_evidence_class(edge.evidence_class),
            scope=normalized_scope,
            scope_key=normalized_scope_key,
            scope_json=canonical_scope_json(normalized_scope),
            slot_key="",
            claim_fingerprint="",
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
            "SELECT * FROM knowledge_graph WHERE triple_id = ?",
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
        effective_evidence_text = (
            _prefer_longer_evidence_text(
                existing=str(existing["evidence_text"] or ""),
                new=write.evidence_text,
            )
            if write.evidence_text_attributable
            else ""
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
                slot_key = ?, claim_fingerprint = ?, scope_key = ?, scope_json = ?,
                status = CASE
                    WHEN status = 'archived' AND COALESCE(status_reason, '') != 'user_forget'
                    THEN 'active'
                    ELSE status
                END,
                updated_at = ?
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
                write.slot_key,
                write.claim_fingerprint,
                write.scope_key,
                write.scope_json,
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
        status: str = "active",
    ) -> None:
        await db.execute(
            """
            INSERT INTO knowledge_graph(
                triple_id, subject_id, subject_type, predicate, object_id, object_type,
                fact_kind, confidence, evidence_event_ids, observation_count, first_observed_at,
                last_observed_at, last_confirmed_at, source_type, extraction_method,
                evidence_text, natural_summary, embedding_status, expires_at,
                valid_from, valid_to, status, evidence_class,
                created_at, updated_at, slot_key, claim_fingerprint, authority_ref,
                scope_key, scope_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
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
                status,
                write.evidence_class,
                write.now,
                write.now,
                write.slot_key,
                write.claim_fingerprint,
                write.scope_key,
                write.scope_json,
            ),
        )

    async def _merge_authoritative_relationship_evidence(
        self,
        *,
        db: aiosqlite.Connection,
        triple_id: str,
        write: _KnowledgeEdgeWrite,
        existing: Mapping[str, Any],
    ) -> None:
        if str(existing["status"] or "") != "active" or not _relationship_covers_observed_at(
            existing,
            write.observed_at,
        ):
            logger.info(
                "L2 relationship evidence fell outside the authoritative segment",
                triple_id=triple_id,
                observed_at=write.observed_at,
            )
            return
        merged = _merge_edge_evidence(
            existing=existing,
            new_event_ids=write.evidence_event_ids,
            new_confidence=write.confidence,
            observed_at=write.observed_at,
        )
        await db.execute(
            """
            UPDATE knowledge_graph
            SET evidence_event_ids = ?, observation_count = ?, first_observed_at = ?,
                last_observed_at = ?, last_confirmed_at = ?,
                evidence_text = CASE WHEN ? THEN evidence_text ELSE '' END,
                natural_summary = CASE WHEN ? THEN natural_summary ELSE '' END,
                embedding_status = CASE WHEN ? THEN embedding_status ELSE 'pending' END,
                updated_at = ?
            WHERE triple_id = ?
            """,
            (
                json.dumps(merged.event_ids, ensure_ascii=False),
                merged.observation_count,
                merged.first_observed_at,
                merged.last_observed_at,
                write.observed_at,
                int(write.evidence_text_attributable),
                int(write.evidence_text_attributable),
                int(write.evidence_text_attributable),
                write.now,
                triple_id,
            ),
        )

    async def _merge_historical_relationship_version(
        self,
        *,
        db: aiosqlite.Connection,
        triple_id: str | None,
        write: _KnowledgeEdgeWrite,
    ) -> bool:
        if not triple_id:
            return False
        existing = await self._fetch_existing_knowledge_edge(db=db, triple_id=triple_id)
        if (
            existing is None
            or str(existing["status"]) == "active"
            or not _relationship_covers_observed_at(
                existing,
                write.observed_at,
                require_closed=True,
            )
        ):
            logger.info(
                "L2 historical relationship evidence had no matching closed segment",
                triple_id=triple_id,
                observed_at=write.observed_at,
            )
            return False
        merged = _merge_edge_evidence(
            existing=existing,
            new_event_ids=write.evidence_event_ids,
            new_confidence=write.confidence,
            observed_at=write.observed_at,
        )
        valid_to = float(existing["valid_to"]) if existing["valid_to"] is not None else None
        last_observed_at = merged.last_observed_at
        if valid_to is not None:
            last_observed_at = min(last_observed_at, valid_to)
        await db.execute(
            """
            UPDATE knowledge_graph
            SET evidence_event_ids = ?, observation_count = ?, first_observed_at = ?,
                last_observed_at = ?,
                evidence_text = CASE WHEN ? THEN evidence_text ELSE '' END,
                natural_summary = CASE WHEN ? THEN natural_summary ELSE '' END,
                embedding_status = CASE WHEN ? THEN embedding_status ELSE 'pending' END,
                updated_at = ?
            WHERE triple_id = ?
            """,
            (
                json.dumps(merged.event_ids, ensure_ascii=False),
                merged.observation_count,
                merged.first_observed_at,
                last_observed_at,
                int(write.evidence_text_attributable),
                int(write.evidence_text_attributable),
                int(write.evidence_text_attributable),
                write.now,
                triple_id,
            ),
        )
        await append_knowledge_graph_version(
            db,
            triple_id=triple_id,
            created_at=write.now,
        )
        return True

    async def _upsert_conflicted_relationship(
        self,
        *,
        db: aiosqlite.Connection,
        triple_id: str,
        write: _KnowledgeEdgeWrite,
        correction_id: str,
        authoritative_triple_id: str | None,
    ) -> None:
        if not authoritative_triple_id:
            raise ValueError("Authoritative relationship id is required for a shadow")
        existing = await self._fetch_existing_knowledge_edge(db=db, triple_id=triple_id)
        if existing is None:
            await self._insert_knowledge_edge(
                db=db,
                triple_id=triple_id,
                write=write,
            )
        else:
            if existing["authority_ref"]:
                logger.info(
                    "L2 conflicting evidence left authoritative relationship unchanged",
                    triple_id=triple_id,
                    authoritative_triple_id=authoritative_triple_id,
                    observed_at=write.observed_at,
                )
                return
            await self._update_existing_knowledge_edge(
                db=db,
                triple_id=triple_id,
                write=write,
                existing=existing,
            )
        victim = await self._fetch_existing_knowledge_edge(db=db, triple_id=triple_id)
        assert victim is not None
        await record_relationship_shadow_conflict_effect(
            db,
            correction_id=correction_id,
            victim=victim,
            replacement_id=authoritative_triple_id,
            now=write.now,
        )
        async with db.execute(
            """
            SELECT MAX(created_at)
            FROM knowledge_graph_versions
            WHERE triple_id = ?
            """,
            (triple_id,),
        ) as cursor:
            latest_version = await cursor.fetchone()
        latest_created_at = (
            float(latest_version[0])
            if latest_version is not None and latest_version[0] is not None
            else write.now
        )
        preimage_created_at = max(write.now, latest_created_at + 0.000001)
        await append_knowledge_graph_version(
            db,
            triple_id=triple_id,
            correction_id=correction_id,
            created_at=preimage_created_at,
        )
        await db.execute(
            """
            UPDATE knowledge_graph
            SET status = 'conflicted', status_reason = 'user_authority_conflict',
                deprecated_by = ?, deprecated_at = ?, updated_at = ?
            WHERE triple_id = ?
            """,
            (authoritative_triple_id, write.observed_at, write.now, triple_id),
        )
        await append_knowledge_graph_version(
            db,
            triple_id=triple_id,
            correction_id=correction_id,
            created_at=preimage_created_at + 0.000001,
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
        """Corroborate an edge through the same governed write path as every upsert."""
        host = cast(_GraphWriteHostProtocol, self)
        await host.initialize()
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                existing = await self._fetch_existing_knowledge_edge(
                    db=db,
                    triple_id=triple_id,
                )
                if existing is None or str(existing["status"]) != "active":
                    await db.commit()
                    return False
                raw_scope = existing["scope_json"] or "{}"
                scope = json.loads(raw_scope) if isinstance(raw_scope, str) else raw_scope
                await self._upsert_knowledge_edge_on_connection(
                    db=db,
                    edge=_KnowledgeEdgeInput(
                        subject_id=str(existing["subject_id"]),
                        subject_type=str(existing["subject_type"]),
                        predicate=str(existing["predicate"]),
                        object_id=str(existing["object_id"]),
                        object_type=str(existing["object_type"]),
                        fact_kind=str(existing["fact_kind"] or "explicit_fact"),
                        evidence_event_ids=evidence_event_ids,
                        confidence=float(new_confidence),
                        observed_at=float(observed_at),
                        source_type=str(existing["source_type"] or "corroboration"),
                        extraction_method=str(existing["extraction_method"] or "rule"),
                        evidence_text=str(evidence_text or ""),
                        expires_at=(
                            float(existing["expires_at"])
                            if existing["expires_at"] is not None
                            else None
                        ),
                        valid_from=(
                            float(existing["valid_from"])
                            if existing["valid_from"] is not None
                            else None
                        ),
                        valid_to=(
                            float(existing["valid_to"])
                            if existing["valid_to"] is not None
                            else None
                        ),
                        evidence_class=(
                            str(existing["evidence_class"])
                            if existing["evidence_class"] is not None
                            else None
                        ),
                        scope=scope,
                    ),
                )
                updated = await self._fetch_existing_knowledge_edge(
                    db=db,
                    triple_id=triple_id,
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise

        logger.debug(
            "L2 knowledge edge corroborated",
            triple_id=triple_id,
            new_observation_count=(updated["observation_count"] if updated else None),
            accumulated_confidence=(updated["confidence"] if updated else None),
        )
        return True
