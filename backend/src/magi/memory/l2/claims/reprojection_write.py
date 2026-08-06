"""Atomic host-owned Claim route reprojection and target retirement."""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Mapping

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ..corrections.fingerprints import canonical_claim_value
from ..semantic_routing import (
    ROUTE_CONTRACT_VERSION,
    RouteDisposition,
    SemanticRouteDecision,
    SemanticRouteInput,
    derive_semantic_route,
)
from ..reviews.repository import (
    close_pending_review_on_connection,
    reconcile_pending_review_support_on_connection,
)
from ..storage.utils import max_evidence_event_ids
from .identity import projection_outcome_id
from .outcomes import (
    ClaimTargetOutcomeContext,
    append_claim_target_outcomes_on_connection,
)

_ROUTE_CHANGED_REASON = "route_contract_changed"
_ROUTE_REVALIDATED_REASON = "route_contract_revalidated"


@dataclass(frozen=True, slots=True)
class ReprojectedClaimRouteResult:
    """Atomic result for one current-contract Claim route recomputation."""

    claim_active: bool
    decision: SemanticRouteDecision | None = None
    route_outcome_appended: bool = False
    target_outcomes_invalidated: int = 0
    target_outcomes_revalidated: int = 0
    targets_archived: int = 0
    shared_targets_preserved: int = 0
    authority_targets_preserved: int = 0


@dataclass(frozen=True, slots=True)
class ClaimTargetRetirementResult:
    """Result of removing one or more Claims' downstream target authority."""

    target_outcomes_invalidated: int = 0
    assertions_archived: int = 0
    relationships_archived: int = 0
    reviews_closed: int = 0
    shared_targets_preserved: int = 0
    authority_targets_preserved: int = 0
    affected_subject_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _TargetSupport:
    claim_ids: tuple[str, ...]
    evidence_event_ids: tuple[str, ...]
    first_event_at: float | None
    last_event_at: float | None
    max_confidence: float


@dataclass(frozen=True, slots=True)
class _CanonicalTarget:
    target_id: str
    target_slot_key: str | None


async def reproject_claim_route(
    db_path: str,
    *,
    claim_id: str,
) -> ReprojectedClaimRouteResult:
    """Recompute one Claim under the current host contract in one transaction.

    The caller supplies only the Claim identity. Route version, resolution-aware
    attempt identity, route decision, outcome payload, and downstream retirement
    are all derived from current durable state while holding the write lock.
    """

    normalized_claim_id = str(claim_id or "").strip()
    if not normalized_claim_id:
        raise ValueError("claim_id must not be blank")
    async with sqlite_connection_async(db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("BEGIN IMMEDIATE")
        try:
            candidate = await _load_route_candidate(db, normalized_claim_id)
            if candidate is None:
                await db.commit()
                return ReprojectedClaimRouteResult(claim_active=False)

            changed_at = time.time()
            decision = _derive_candidate_route(candidate)
            attempt_key = _reprojection_attempt_key(candidate)
            route_target_id = decision.route_key or (
                "predicate:" + str(candidate["canonical_predicate"] or "").strip().upper()
            )
            route_outcome_id = projection_outcome_id(
                claim_id=normalized_claim_id,
                attempt_key=attempt_key,
                target_kind="route",
                target_id=route_target_id,
            )
            route_existed = await _outcome_exists(db, route_outcome_id)
            await append_claim_target_outcomes_on_connection(
                db,
                context=ClaimTargetOutcomeContext.for_claim(
                    claim_id=normalized_claim_id,
                    attempt_key=attempt_key,
                    route_contract_version=ROUTE_CONTRACT_VERSION,
                ),
                target_kind="route",
                target_id=route_target_id,
                target_slot_key=decision.slot_key,
                outcome=decision.disposition.value,
                reason_code=decision.reason_code,
                details=_route_outcome_details(
                    decision,
                    subject_resolution_version=int(
                        candidate.get("subject_resolution_version") or 0
                    ),
                    object_resolution_version=int(
                        candidate.get("object_resolution_version") or 0
                    ),
                ),
                created_at=changed_at,
            )
            retirement = await _reconcile_downstream_provenance(
                db,
                claim_id=normalized_claim_id,
                candidate=candidate,
                decision=decision,
                attempt_key=attempt_key,
                changed_at=changed_at,
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    return ReprojectedClaimRouteResult(
        claim_active=True,
        decision=decision,
        route_outcome_appended=not route_existed,
        target_outcomes_invalidated=retirement.target_outcomes_invalidated,
        target_outcomes_revalidated=retirement.target_outcomes_revalidated,
        targets_archived=retirement.targets_archived,
        shared_targets_preserved=retirement.shared_targets_preserved,
        authority_targets_preserved=retirement.authority_targets_preserved,
    )


async def _load_route_candidate(
    db: aiosqlite.Connection,
    claim_id: str,
) -> dict[str, Any] | None:
    async with db.execute(
        """
        WITH latest_entity_refs AS (
            SELECT
                refs.claim_id,
                refs.ref_role,
                refs.entity_id,
                refs.resolution_version,
                ROW_NUMBER() OVER (
                    PARTITION BY refs.claim_id, refs.ref_role
                    ORDER BY refs.resolution_version DESC,
                             refs.created_at DESC,
                             refs.entity_id
                ) AS row_number
            FROM l2_claim_entity_refs AS refs
            WHERE refs.invalidated_at IS NULL
              AND refs.claim_id = ?
        )
        SELECT
            claims.claim_id,
            COALESCE(subject_refs.entity_id, claims.subject_ref) AS subject_ref,
            claims.subject_type,
            claims.canonical_predicate,
            claims.fact_kind,
            claims.object_type,
            claims.object_value_json,
            claims.temporal_cue,
            claims.specificity,
            claims.confidence,
            claims.target_from,
            claims.target_to,
            claims.raw_time_frame_json,
            object_refs.entity_id AS object_entity_id,
            COALESCE(subject_refs.resolution_version, 0)
                AS subject_resolution_version,
            COALESCE(object_refs.resolution_version, 0)
                AS object_resolution_version
        FROM l2_grounded_claims AS claims
        LEFT JOIN latest_entity_refs AS subject_refs
          ON subject_refs.claim_id = claims.claim_id
         AND subject_refs.ref_role = 'subject'
         AND subject_refs.row_number = 1
        LEFT JOIN latest_entity_refs AS object_refs
          ON object_refs.claim_id = claims.claim_id
         AND object_refs.ref_role = 'object'
         AND object_refs.row_number = 1
        WHERE claims.claim_id = ?
          AND claims.availability = 'active'
        """,
        (claim_id, claim_id),
    ) as cursor:
        row = await cursor.fetchone()
    return dict(row) if row is not None else None


def _derive_candidate_route(candidate: Mapping[str, Any]) -> SemanticRouteDecision:
    raw_time_frame = _decode_json(candidate.get("raw_time_frame_json"))
    temporal_payload = raw_time_frame if isinstance(raw_time_frame, dict) else {}
    return derive_semantic_route(
        SemanticRouteInput(
            claim_id=str(candidate["claim_id"]),
            subject_id=str(candidate["subject_ref"]),
            subject_type=str(candidate["subject_type"]),
            canonical_predicate=str(candidate["canonical_predicate"]),
            fact_kind=str(candidate["fact_kind"]),
            object_type=str(candidate["object_type"]),
            object_value=_decode_json(candidate.get("object_value_json")),
            object_entity_id=(
                str(candidate["object_entity_id"])
                if candidate.get("object_entity_id") is not None
                else None
            ),
            temporal_cue=str(candidate["temporal_cue"]),
            specificity=str(candidate["specificity"]),
            target_from=(
                float(candidate["target_from"])
                if candidate.get("target_from") is not None
                else None
            ),
            target_to=(
                float(candidate["target_to"]) if candidate.get("target_to") is not None else None
            ),
            raw_time_expression=str(temporal_payload.get("raw") or ""),
            time_resolution=str(temporal_payload.get("resolution") or "unscheduled"),
            time_frame=temporal_payload,
        )
    )


def _reprojection_attempt_key(candidate: Mapping[str, Any]) -> str:
    subject_resolution = max(
        0,
        int(candidate.get("subject_resolution_version") or 0),
    )
    object_resolution = max(
        0,
        int(candidate.get("object_resolution_version") or 0),
    )
    resolution_key = (
        f"s{subject_resolution}:r{object_resolution}"
        if subject_resolution > 0
        else f"r{object_resolution}"
    )
    return (
        f"route-reproject:v{ROUTE_CONTRACT_VERSION}:"
        f"{resolution_key}:{str(candidate['claim_id'])}"
    )


def _route_outcome_details(
    decision: SemanticRouteDecision,
    *,
    subject_resolution_version: int,
    object_resolution_version: int,
) -> dict[str, Any]:
    return {
        "semantic_route_id": decision.semantic_route_id,
        "family": decision.family,
        "trait_code": decision.trait_code,
        "object_role": decision.object_role.value,
        "value_fingerprint": decision.value_fingerprint,
        "semantic_target_key": decision.semantic_target_key,
        "object_surface": decision.object_surface,
        "normalized_target_text": decision.normalized_target_text,
        "target_entity_type": decision.target_entity_type,
        "goal_lineage_key": decision.goal_lineage_key,
        "target_window_key": decision.target_window_key,
        "scope_key": decision.scope_key,
        "subject_resolution_version": max(0, int(subject_resolution_version)),
        "object_resolution_version": max(0, int(object_resolution_version)),
    }


async def _outcome_exists(db: aiosqlite.Connection, outcome_id: str) -> bool:
    async with db.execute(
        "SELECT 1 FROM l2_claim_projection_outcomes WHERE outcome_id = ?",
        (outcome_id,),
    ) as cursor:
        return await cursor.fetchone() is not None


@dataclass(frozen=True, slots=True)
class _RetirementResult:
    target_outcomes_invalidated: int = 0
    target_outcomes_revalidated: int = 0
    targets_archived: int = 0
    shared_targets_preserved: int = 0
    authority_targets_preserved: int = 0


async def retire_claim_target_authority_on_connection(
    db: aiosqlite.Connection,
    *,
    claim_ids: Iterable[str],
    invalidated_reason: str,
    changed_at: float,
) -> ClaimTargetRetirementResult:
    """Remove exact Claim target receipts and reconcile their canonical targets.

    Entity rekeys intentionally leave immutable Claim target receipts pointing at
    their original projection attempt. Before a Claim is irreversibly redacted,
    expand those receipts through the current entity-resolution lineage so the
    canonical assertion or relationship loses only this Claim's authority.
    """

    if not db.in_transaction:
        raise RuntimeError("Claim target retirement requires an active transaction")
    normalized_claim_ids = tuple(
        sorted({str(claim_id).strip() for claim_id in claim_ids if str(claim_id).strip()})
    )
    reason = str(invalidated_reason or "").strip()
    if not reason:
        raise ValueError("invalidated_reason must not be blank")
    if not normalized_claim_ids:
        return ClaimTargetRetirementResult()

    affected_targets: set[tuple[str, str]] = set()
    retired_evidence_event_ids: set[str] = set()
    invalidated = 0
    for claim_id in normalized_claim_ids:
        candidate = await _load_route_candidate(db, claim_id)
        decision = _derive_candidate_route(candidate) if candidate is not None else None
        retired_evidence_event_ids.update(
            await _claim_supporting_evidence_event_ids(db, claim_id=claim_id)
        )
        receipts = await _active_target_receipts(db, claim_id=claim_id)
        for receipt in receipts:
            target_kind = str(receipt["target_kind"])
            target_id = str(receipt["target_id"])
            affected_targets.add((target_kind, target_id))
            if candidate is not None and decision is not None:
                canonical_target = await _authorized_receipt_target(
                    db,
                    receipt=receipt,
                    candidate=candidate,
                    decision=decision,
                )
                if canonical_target is not None:
                    affected_targets.add((target_kind, canonical_target.target_id))
            invalidated += await _invalidate_target_receipt(
                db,
                outcome_id=str(receipt["outcome_id"]),
                reason=reason,
                changed_at=changed_at,
            )

    assertion_archives = 0
    relationship_archives = 0
    review_closures = 0
    shared_preserved = 0
    authority_preserved = 0
    affected_subject_keys: set[str] = set()
    for target_kind, target_id in sorted(affected_targets):
        affected_subject_keys.update(
            await _target_subject_keys(
                db,
                target_kind=target_kind,
                target_id=target_id,
            )
        )
        support = await _current_target_support(
            db,
            target_kind=target_kind,
            target_id=target_id,
        )
        authority = await _target_has_independent_authority(
            db,
            target_kind=target_kind,
            target_id=target_id,
        )
        if support.claim_ids or authority:
            await _refresh_target_evidence(
                db,
                target_kind=target_kind,
                target_id=target_id,
                support=support,
                preserve_existing=authority,
                retired_evidence_event_ids=retired_evidence_event_ids,
                changed_at=changed_at,
            )
            if authority:
                authority_preserved += 1
            else:
                shared_preserved += 1
            continue
        archived = await _archive_target(
            db,
            target_kind=target_kind,
            target_id=target_id,
            changed_at=changed_at,
            reason=reason,
        )
        if target_kind == "assertion":
            assertion_archives += archived
        elif target_kind == "review":
            review_closures += archived
        else:
            relationship_archives += archived

    return ClaimTargetRetirementResult(
        target_outcomes_invalidated=invalidated,
        assertions_archived=assertion_archives,
        relationships_archived=relationship_archives,
        reviews_closed=review_closures,
        shared_targets_preserved=shared_preserved,
        authority_targets_preserved=authority_preserved,
        affected_subject_keys=tuple(sorted(affected_subject_keys)),
    )


async def _reconcile_downstream_provenance(
    db: aiosqlite.Connection,
    *,
    claim_id: str,
    candidate: Mapping[str, Any],
    decision: SemanticRouteDecision,
    attempt_key: str,
    changed_at: float,
) -> _RetirementResult:
    receipts = await _active_target_receipts(db, claim_id=claim_id)

    invalidated = 0
    revalidated = 0
    affected_targets: set[tuple[str, str]] = set()
    retired_evidence_event_ids = await _claim_supporting_evidence_event_ids(
        db,
        claim_id=claim_id,
    )
    authorized_groups: dict[
        tuple[str, str, str],
        list[tuple[dict[str, Any], _CanonicalTarget]],
    ] = {}
    unauthorized_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for receipt in receipts:
        target_kind = str(receipt["target_kind"])
        target_id = str(receipt["target_id"])
        canonical_target = await _authorized_receipt_target(
            db,
            receipt=receipt,
            candidate=candidate,
            decision=decision,
        )
        if canonical_target is None:
            unauthorized_groups.setdefault((target_kind, target_id), []).append(receipt)
            continue
        authorized_groups.setdefault(
            (
                target_kind,
                canonical_target.target_id,
                canonical_target.target_slot_key or "",
            ),
            [],
        ).append((receipt, canonical_target))

    for (
        target_kind,
        canonical_target_id,
        _canonical_slot_key,
    ), entries in sorted(authorized_groups.items()):
        canonical_target = entries[0][1]
        current_receipts = [
            receipt
            for receipt, _target in entries
            if _receipt_is_current(
                receipt,
                attempt_key=attempt_key,
                decision=decision,
                canonical_target=canonical_target,
            )
        ]
        current_receipts.sort(key=lambda receipt: str(receipt["outcome_id"]))
        keep_outcome_id = str(current_receipts[0]["outcome_id"]) if current_receipts else None
        if keep_outcome_id is None:
            revalidated_outcome_id = projection_outcome_id(
                claim_id=claim_id,
                attempt_key=attempt_key,
                target_kind=target_kind,
                target_id=canonical_target_id,
            )
            existed = await _outcome_exists(db, revalidated_outcome_id)
            superseded_outcome_ids = sorted(
                str(receipt["outcome_id"]) for receipt, _target in entries
            )
            await append_claim_target_outcomes_on_connection(
                db,
                context=ClaimTargetOutcomeContext.for_claim(
                    claim_id=claim_id,
                    attempt_key=attempt_key,
                    route_contract_version=ROUTE_CONTRACT_VERSION,
                ),
                target_kind=target_kind,
                target_id=canonical_target_id,
                target_slot_key=canonical_target.target_slot_key,
                outcome="pending" if target_kind == "review" else "projected",
                reason_code=_ROUTE_REVALIDATED_REASON,
                details={"supersedes_outcome_ids": superseded_outcome_ids},
                created_at=changed_at,
            )
            if not existed:
                revalidated += 1
            keep_outcome_id = revalidated_outcome_id

        group_invalidated = 0
        for receipt, _target in entries:
            receipt_outcome_id = str(receipt["outcome_id"])
            if receipt_outcome_id == keep_outcome_id:
                continue
            group_invalidated += await _invalidate_target_receipt(
                db,
                outcome_id=receipt_outcome_id,
                reason=_ROUTE_REVALIDATED_REASON,
                changed_at=changed_at,
            )
            affected_targets.add((target_kind, str(receipt["target_id"])))
        invalidated += group_invalidated
        if group_invalidated:
            affected_targets.add((target_kind, canonical_target_id))

    for (target_kind, target_id), grouped_receipts in sorted(unauthorized_groups.items()):
        for receipt in grouped_receipts:
            invalidated += await _invalidate_target_receipt(
                db,
                outcome_id=str(receipt["outcome_id"]),
                reason=_ROUTE_CHANGED_REASON,
                changed_at=changed_at,
            )
        affected_targets.add((target_kind, target_id))

    targets_archived = 0
    shared_preserved = 0
    authority_preserved = 0
    for target_kind, target_id in sorted(affected_targets):
        support = await _current_target_support(
            db,
            target_kind=target_kind,
            target_id=target_id,
        )
        authority = await _target_has_independent_authority(
            db,
            target_kind=target_kind,
            target_id=target_id,
        )
        if support.claim_ids or authority:
            await _refresh_target_evidence(
                db,
                target_kind=target_kind,
                target_id=target_id,
                support=support,
                preserve_existing=authority,
                retired_evidence_event_ids=retired_evidence_event_ids,
                changed_at=changed_at,
            )
            if authority:
                authority_preserved += 1
            elif any(supporting_id != claim_id for supporting_id in support.claim_ids):
                shared_preserved += 1
            continue
        targets_archived += await _archive_target(
            db,
            target_kind=target_kind,
            target_id=target_id,
            changed_at=changed_at,
        )

    return _RetirementResult(
        target_outcomes_invalidated=invalidated,
        target_outcomes_revalidated=revalidated,
        targets_archived=targets_archived,
        shared_targets_preserved=shared_preserved,
        authority_targets_preserved=authority_preserved,
    )


async def _active_target_receipts(
    db: aiosqlite.Connection,
    *,
    claim_id: str,
) -> list[dict[str, Any]]:
    async with db.execute(
        """
        SELECT
            targets.*,
            routes.outcome AS source_route_outcome,
            routes.target_slot_key AS source_route_slot_key,
            routes.details_json AS source_route_details_json,
            routes.invalidated_at AS source_route_invalidated_at,
            routes.invalidated_reason AS source_route_invalidated_reason
        FROM l2_claim_projection_outcomes AS targets
        LEFT JOIN l2_claim_projection_outcomes AS routes
          ON routes.outcome_id = (
              SELECT source_routes.outcome_id
              FROM l2_claim_projection_outcomes AS source_routes
              WHERE source_routes.claim_id = targets.claim_id
                AND source_routes.attempt_key = targets.attempt_key
                AND source_routes.target_kind = 'route'
              ORDER BY CASE WHEN source_routes.invalidated_at IS NULL
                            THEN 1 ELSE 0 END DESC,
                       source_routes.route_contract_version DESC,
                       source_routes.created_at DESC,
                       source_routes.outcome_id DESC
              LIMIT 1
          )
        WHERE targets.claim_id = ?
          AND targets.target_kind IN ('assertion', 'relationship', 'review')
          AND (
                targets.outcome = 'projected'
                OR (targets.target_kind = 'review' AND targets.outcome = 'pending')
          )
          AND targets.invalidated_at IS NULL
        ORDER BY targets.created_at, targets.outcome_id
        """,
        (claim_id,),
    ) as cursor:
        return [dict(row) for row in await cursor.fetchall()]


async def _invalidate_target_receipt(
    db: aiosqlite.Connection,
    *,
    outcome_id: str,
    reason: str,
    changed_at: float,
) -> int:
    cursor = await db.execute(
        """
        UPDATE l2_claim_projection_outcomes
        SET invalidated_at = ?, invalidated_reason = ?
        WHERE outcome_id = ? AND invalidated_at IS NULL
        """,
        (changed_at, reason, outcome_id),
    )
    return max(int(cursor.rowcount or 0), 0)


def _receipt_is_current(
    receipt: Mapping[str, Any],
    *,
    attempt_key: str,
    decision: SemanticRouteDecision,
    canonical_target: _CanonicalTarget,
) -> bool:
    return bool(
        receipt.get("source_route_invalidated_at") is None
        and int(receipt.get("route_contract_version") or 0) == ROUTE_CONTRACT_VERSION
        and str(receipt.get("attempt_key") or "") == attempt_key
        and str(receipt.get("target_id") or "") == canonical_target.target_id
        and _optional_text(receipt.get("target_slot_key"))
        == _optional_text(canonical_target.target_slot_key)
        and _stored_route_signature(receipt) == _decision_signature(decision)
    )


async def _authorized_receipt_target(
    db: aiosqlite.Connection,
    *,
    receipt: Mapping[str, Any],
    candidate: Mapping[str, Any],
    decision: SemanticRouteDecision,
) -> _CanonicalTarget | None:
    target_kind = str(receipt.get("target_kind") or "")
    if not _decision_allows_target(decision, target_kind):
        return None
    source_signature = _stored_route_signature(receipt)
    if receipt.get("source_route_invalidated_at") is None:
        if source_signature != _decision_signature(decision):
            return None
        return _CanonicalTarget(
            target_id=str(receipt.get("target_id") or ""),
            target_slot_key=_optional_text(receipt.get("target_slot_key")),
        )
    if str(receipt.get("source_route_invalidated_reason") or "") != "entity_merged":
        return None
    if not _entity_merge_route_semantics_match(
        source_signature=source_signature,
        decision=decision,
    ):
        return None
    return await _canonical_target_after_entity_merge(
        db,
        receipt=receipt,
        candidate=candidate,
        decision=decision,
    )


def _entity_merge_route_semantics_match(
    *,
    source_signature: tuple[Any, ...] | None,
    decision: SemanticRouteDecision,
) -> bool:
    if source_signature is None:
        return False
    current_signature = _decision_signature(decision)
    invariant_indexes = (0, 2, 3, 4, 5, 8, 9)
    return all(source_signature[index] == current_signature[index] for index in invariant_indexes)


async def _canonical_target_after_entity_merge(
    db: aiosqlite.Connection,
    *,
    receipt: Mapping[str, Any],
    candidate: Mapping[str, Any],
    decision: SemanticRouteDecision,
) -> _CanonicalTarget | None:
    target_kind = str(receipt.get("target_kind") or "")
    if target_kind == "assertion":
        return await _canonical_assertion_target_after_entity_merge(
            db,
            original_target_id=str(receipt.get("target_id") or ""),
            decision=decision,
        )
    if target_kind == "relationship":
        return await _canonical_relationship_target_after_entity_merge(
            db,
            original_target_id=str(receipt.get("target_id") or ""),
            claim_id=str(candidate.get("claim_id") or ""),
            candidate=candidate,
            decision=decision,
        )
    if target_kind == "review" and decision.can_project_assertion:
        return _CanonicalTarget(
            target_id=str(receipt.get("target_id") or ""),
            target_slot_key=decision.slot_key,
        )
    return None


async def _canonical_assertion_target_after_entity_merge(
    db: aiosqlite.Connection,
    *,
    original_target_id: str,
    decision: SemanticRouteDecision,
) -> _CanonicalTarget | None:
    if not decision.can_project_assertion or not decision.slot_key:
        return None
    async with db.execute(
        """
        SELECT assertion_id, slot_key, entity_id, entity_type, trait_family,
               trait_name, trait_value, target_entity_id, target_entity_type,
               scope_key, status, updated_at
        FROM tom_trait_assertions
        WHERE assertion_id = ?
           OR (
                entity_id = ?
                AND LOWER(TRIM(entity_type)) = LOWER(TRIM(?))
                AND LOWER(TRIM(trait_family)) = LOWER(TRIM(?))
                AND LOWER(TRIM(trait_name)) = LOWER(TRIM(?))
                AND COALESCE(target_entity_id, '') = ?
                AND LOWER(TRIM(COALESCE(target_entity_type, ''))) =
                    LOWER(TRIM(?))
                AND COALESCE(scope_key, 'global') = ?
           )
        ORDER BY CASE WHEN assertion_id = ? THEN 1 ELSE 0 END DESC,
                 updated_at DESC, assertion_id
        """,
        (
            original_target_id,
            str(decision.subject_id or ""),
            str(decision.subject_type or ""),
            str(decision.family or ""),
            str(decision.trait_code or ""),
            str(decision.target_entity_id or ""),
            str(decision.target_entity_type or ""),
            str(decision.scope_key or "global"),
            original_target_id,
        ),
    ) as cursor:
        rows = await cursor.fetchall()
    for row in rows:
        record = dict(row)
        if str(record.get("status") or "active") in {
            "superseded",
            "archived",
            "expired",
            "user_rejected",
            "shadow",
            "invalidated",
        }:
            continue
        if not (
            _same_text(record.get("entity_id"), decision.subject_id)
            and _same_folded_text(record.get("entity_type"), decision.subject_type)
            and _same_folded_text(record.get("trait_family"), decision.family)
            and _same_folded_text(record.get("trait_name"), decision.trait_code)
            and _same_text(record.get("target_entity_id"), decision.target_entity_id)
            and _same_folded_text(
                record.get("target_entity_type"),
                decision.target_entity_type,
            )
            and _same_text(record.get("scope_key") or "global", decision.scope_key)
            and canonical_claim_value(record.get("trait_value"))
            == canonical_claim_value(decision.canonical_value)
        ):
            continue
        return _CanonicalTarget(
            target_id=str(record["assertion_id"]),
            target_slot_key=str(record["slot_key"]),
        )
    return None


async def _canonical_relationship_target_after_entity_merge(
    db: aiosqlite.Connection,
    *,
    original_target_id: str,
    claim_id: str,
    candidate: Mapping[str, Any],
    decision: SemanticRouteDecision,
) -> _CanonicalTarget | None:
    subject_id = str(decision.subject_id or candidate.get("subject_ref") or "").strip()
    predicate = str(candidate.get("canonical_predicate") or "").strip().upper()
    object_entity_id = str(candidate.get("object_entity_id") or "").strip()
    if not subject_id or not predicate:
        return None
    supporting_event_ids = await _claim_supporting_evidence_event_ids(
        db,
        claim_id=claim_id,
    )
    async with db.execute(
        """
        SELECT triple_id, slot_key, subject_id, subject_type, predicate,
               object_id, object_type, scope_key, status, evidence_event_ids
        FROM knowledge_graph
        WHERE status = 'active'
          AND subject_id = ?
          AND UPPER(TRIM(predicate)) = ?
          AND COALESCE(scope_key, 'global') = ?
          AND (? = '' OR object_id = ?)
        ORDER BY CASE WHEN triple_id = ? THEN 1 ELSE 0 END DESC, triple_id
        """,
        (
            subject_id,
            predicate,
            str(decision.scope_key or "global"),
            object_entity_id,
            object_entity_id,
            original_target_id,
        ),
    ) as cursor:
        rows = await cursor.fetchall()
    matches: list[_CanonicalTarget] = []
    for row in rows:
        record = dict(row)
        if not (
            _same_folded_text(record.get("subject_type"), decision.subject_type)
            and _same_folded_text(record.get("object_type"), candidate.get("object_type"))
        ):
            continue
        if not object_entity_id:
            target_is_original = str(record.get("triple_id") or "") == original_target_id
            target_evidence = _event_ids(record.get("evidence_event_ids"))
            if not target_is_original and not target_evidence.intersection(supporting_event_ids):
                continue
        matches.append(
            _CanonicalTarget(
                target_id=str(record["triple_id"]),
                target_slot_key=_optional_text(record.get("slot_key")),
            )
        )
    return matches[0] if len(matches) == 1 else None


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _same_text(left: Any, right: Any) -> bool:
    return str(left or "").strip() == str(right or "").strip()


def _same_folded_text(left: Any, right: Any) -> bool:
    return str(left or "").strip().casefold() == str(right or "").strip().casefold()


async def _claim_supporting_evidence_event_ids(
    db: aiosqlite.Connection,
    *,
    claim_id: str,
) -> set[str]:
    async with db.execute(
        """
        SELECT event_id
        FROM l2_claim_evidence
        WHERE claim_id = ? AND link_role = 'supporting'
        """,
        (claim_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    return {str(row[0]).strip() for row in rows if str(row[0]).strip()}


def _decision_signature(decision: SemanticRouteDecision) -> tuple[Any, ...]:
    return (
        decision.disposition.value,
        decision.slot_key,
        decision.semantic_route_id,
        decision.family,
        decision.trait_code,
        decision.object_role.value,
        decision.value_fingerprint,
        decision.target_entity_type,
        decision.target_window_key,
        decision.scope_key,
    )


def _stored_route_signature(row: Mapping[str, Any]) -> tuple[Any, ...] | None:
    details = _decode_json(row.get("source_route_details_json"))
    if not isinstance(details, dict):
        return None
    required_detail_keys = {
        "semantic_route_id",
        "family",
        "trait_code",
        "object_role",
        "value_fingerprint",
        "target_entity_type",
        "target_window_key",
        "scope_key",
    }
    if not required_detail_keys.issubset(details):
        return None
    return (
        str(row.get("source_route_outcome") or ""),
        row.get("source_route_slot_key"),
        details.get("semantic_route_id"),
        details.get("family"),
        details.get("trait_code"),
        details.get("object_role"),
        details.get("value_fingerprint"),
        details.get("target_entity_type"),
        details.get("target_window_key"),
        details.get("scope_key"),
    )


def _decision_allows_target(
    decision: SemanticRouteDecision,
    target_kind: str,
) -> bool:
    if target_kind == "assertion":
        return decision.can_project_assertion
    if target_kind == "relationship":
        return decision.disposition is RouteDisposition.ROUTED or (
            decision.disposition is RouteDisposition.NOT_APPLICABLE
            and decision.reason_code == "relationship_only"
        )
    if target_kind == "review":
        return decision.can_project_assertion
    return False


async def _current_target_support(
    db: aiosqlite.Connection,
    *,
    target_kind: str,
    target_id: str,
) -> _TargetSupport:
    async with db.execute(
        """
        SELECT
            receipts.claim_id,
            receipts.attempt_key,
            receipts.target_kind,
            receipts.target_id,
            receipts.target_slot_key,
            receipts.route_contract_version,
            routes.outcome AS source_route_outcome,
            routes.target_slot_key AS source_route_slot_key,
            routes.details_json AS source_route_details_json,
            routes.invalidated_at AS source_route_invalidated_at,
            routes.invalidated_reason AS source_route_invalidated_reason
        FROM l2_claim_projection_outcomes AS receipts
        JOIN l2_grounded_claims AS claims
          ON claims.claim_id = receipts.claim_id
         AND claims.availability = 'active'
        JOIN l2_claim_projection_outcomes AS routes
          ON routes.outcome_id = (
              SELECT source_routes.outcome_id
              FROM l2_claim_projection_outcomes AS source_routes
              WHERE source_routes.claim_id = receipts.claim_id
                AND source_routes.attempt_key = receipts.attempt_key
                AND source_routes.target_kind = 'route'
              ORDER BY CASE WHEN source_routes.invalidated_at IS NULL
                            THEN 1 ELSE 0 END DESC,
                       source_routes.route_contract_version DESC,
                       source_routes.created_at DESC,
                       source_routes.outcome_id DESC
              LIMIT 1
          )
        WHERE receipts.target_kind = ?
          AND (
                receipts.target_id = ?
                OR routes.invalidated_reason = 'entity_merged'
          )
          AND (
                receipts.outcome = 'projected'
                OR (receipts.target_kind = 'review' AND receipts.outcome = 'pending')
          )
          AND receipts.invalidated_at IS NULL
        ORDER BY receipts.claim_id, receipts.created_at DESC, receipts.outcome_id DESC
        """,
        (target_kind, target_id),
    ) as cursor:
        receipt_rows = [dict(row) for row in await cursor.fetchall()]

    valid_claim_ids: set[str] = set()
    confidence_by_claim: dict[str, float] = {}
    for receipt in receipt_rows:
        supporting_claim_id = str(receipt["claim_id"])
        if supporting_claim_id in valid_claim_ids:
            continue
        candidate = await _load_route_candidate(db, supporting_claim_id)
        if candidate is None:
            continue
        decision = _derive_candidate_route(candidate)
        canonical_target = await _authorized_receipt_target(
            db,
            receipt=receipt,
            candidate=candidate,
            decision=decision,
        )
        if canonical_target is None or canonical_target.target_id != target_id:
            continue
        valid_claim_ids.add(supporting_claim_id)
        confidence_by_claim[supporting_claim_id] = float(candidate.get("confidence") or 0.0)

    if not valid_claim_ids:
        return _TargetSupport((), (), None, None, 0.0)
    placeholders = ", ".join("?" for _ in valid_claim_ids)
    async with db.execute(
        f"""
        SELECT event_id, event_time
        FROM l2_claim_evidence
        WHERE claim_id IN ({placeholders})
          AND link_role = 'supporting'
        ORDER BY event_time, event_id
        """,
        tuple(sorted(valid_claim_ids)),
    ) as cursor:
        evidence_rows = await cursor.fetchall()
    event_ids = tuple(sorted({str(row[0]) for row in evidence_rows if str(row[0]).strip()}))
    event_times = [float(row[1]) for row in evidence_rows if row[1] is not None]
    return _TargetSupport(
        claim_ids=tuple(sorted(valid_claim_ids)),
        evidence_event_ids=event_ids,
        first_event_at=min(event_times) if event_times else None,
        last_event_at=max(event_times) if event_times else None,
        max_confidence=max(confidence_by_claim.values(), default=0.0),
    )


async def _target_has_independent_authority(
    db: aiosqlite.Connection,
    *,
    target_kind: str,
    target_id: str,
) -> bool:
    if target_kind == "assertion":
        async with db.execute(
            """
            SELECT 1
            FROM tom_trait_assertions
            WHERE assertion_id = ?
              AND status NOT IN (
                    'superseded', 'archived', 'expired',
                    'user_rejected', 'shadow', 'invalidated'
              )
              AND (
                    COALESCE(authority_ref, '') != ''
                    OR COALESCE(user_feedback, '') != ''
              )
            """,
            (target_id,),
        ) as cursor:
            return await cursor.fetchone() is not None
    if target_kind == "review":
        return False
    async with db.execute(
        """
        SELECT 1
        FROM knowledge_graph
        WHERE triple_id = ?
          AND status = 'active'
          AND (
                COALESCE(authority_ref, '') != ''
                OR COALESCE(status_reason, '') = 'user_correction'
                OR COALESCE(extraction_method, '') NOT IN ('', 'llm_phase1_grounded')
          )
        """,
        (target_id,),
    ) as cursor:
        return await cursor.fetchone() is not None


async def _target_subject_keys(
    db: aiosqlite.Connection,
    *,
    target_kind: str,
    target_id: str,
) -> set[str]:
    if target_kind == "assertion":
        query = """
            SELECT entity_id, target_entity_id
            FROM tom_trait_assertions
            WHERE assertion_id = ?
        """
    elif target_kind == "relationship":
        query = """
            SELECT subject_id AS entity_id, object_id AS target_entity_id
            FROM knowledge_graph
            WHERE triple_id = ?
        """
    else:
        query = """
            SELECT subject_id AS entity_id, '' AS target_entity_id
            FROM l2_pending_reviews
            WHERE review_id = ?
        """
    async with db.execute(query, (target_id,)) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return set()
    subject = str(row[0] or "").strip()
    target = str(row[1] or "").strip()
    return {value for value in (subject, target if ":" in target else "") if value}


async def _refresh_target_evidence(
    db: aiosqlite.Connection,
    *,
    target_kind: str,
    target_id: str,
    support: _TargetSupport,
    preserve_existing: bool,
    retired_evidence_event_ids: set[str],
    changed_at: float,
) -> None:
    if target_kind == "assertion":
        await _refresh_assertion_evidence(
            db,
            assertion_id=target_id,
            support=support,
            preserve_existing=preserve_existing,
            retired_evidence_event_ids=retired_evidence_event_ids,
            changed_at=changed_at,
        )
        return
    if target_kind == "review":
        await reconcile_pending_review_support_on_connection(
            db,
            review_id=target_id,
            claim_ids=support.claim_ids,
            evidence_event_ids=support.evidence_event_ids,
            changed_at=changed_at,
            close_reason=_ROUTE_CHANGED_REASON,
        )
        return
    await _refresh_relationship_evidence(
        db,
        triple_id=target_id,
        support=support,
        preserve_existing=preserve_existing,
        retired_evidence_event_ids=retired_evidence_event_ids,
        changed_at=changed_at,
    )


async def _refresh_assertion_evidence(
    db: aiosqlite.Connection,
    *,
    assertion_id: str,
    support: _TargetSupport,
    preserve_existing: bool,
    retired_evidence_event_ids: set[str],
    changed_at: float,
) -> None:
    async with db.execute(
        "SELECT evidence_events FROM tom_trait_assertions WHERE assertion_id = ?",
        (assertion_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return
    existing = _event_ids(row[0])
    evidence = _bounded_event_ids(
        (existing.difference(retired_evidence_event_ids).union(support.evidence_event_ids))
        if preserve_existing
        else support.evidence_event_ids
    )
    if preserve_existing:
        await db.execute(
            """
            UPDATE tom_trait_assertions
            SET evidence_events = ?, updated_at = ?
            WHERE assertion_id = ?
            """,
            (json.dumps(evidence, ensure_ascii=False), changed_at, assertion_id),
        )
        return
    await db.execute(
        """
        UPDATE tom_trait_assertions
        SET evidence_events = ?, confidence_score = ?,
            first_inferred_at = COALESCE(?, first_inferred_at),
            last_validated_at = COALESCE(?, last_validated_at),
            updated_at = ?
        WHERE assertion_id = ?
        """,
        (
            json.dumps(evidence, ensure_ascii=False),
            support.max_confidence,
            support.first_event_at,
            support.last_event_at,
            changed_at,
            assertion_id,
        ),
    )


async def _refresh_relationship_evidence(
    db: aiosqlite.Connection,
    *,
    triple_id: str,
    support: _TargetSupport,
    preserve_existing: bool,
    retired_evidence_event_ids: set[str],
    changed_at: float,
) -> None:
    async with db.execute(
        "SELECT evidence_event_ids FROM knowledge_graph WHERE triple_id = ?",
        (triple_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return
    existing = _event_ids(row[0])
    evidence = _bounded_event_ids(
        (existing.difference(retired_evidence_event_ids).union(support.evidence_event_ids))
        if preserve_existing
        else support.evidence_event_ids
    )
    if preserve_existing:
        await db.execute(
            """
            UPDATE knowledge_graph
            SET evidence_event_ids = ?, updated_at = ?
            WHERE triple_id = ?
            """,
            (json.dumps(evidence, ensure_ascii=False), changed_at, triple_id),
        )
        return
    await db.execute(
        """
        UPDATE knowledge_graph
        SET evidence_event_ids = ?, observation_count = ?, confidence = ?,
            first_observed_at = COALESCE(?, first_observed_at),
            last_observed_at = COALESCE(?, last_observed_at),
            evidence_text = '', embedding_status = 'pending', updated_at = ?
        WHERE triple_id = ?
        """,
        (
            json.dumps(evidence, ensure_ascii=False),
            max(1, len(support.claim_ids)),
            support.max_confidence,
            support.first_event_at,
            support.last_event_at,
            changed_at,
            triple_id,
        ),
    )


async def _archive_target(
    db: aiosqlite.Connection,
    *,
    target_kind: str,
    target_id: str,
    changed_at: float,
    reason: str = _ROUTE_CHANGED_REASON,
) -> int:
    if target_kind == "assertion":
        cursor = await db.execute(
            """
            UPDATE tom_trait_assertions
            SET status = 'archived', valid_to = COALESCE(valid_to, ?), updated_at = ?
            WHERE assertion_id = ?
              AND status NOT IN (
                    'superseded', 'archived', 'expired',
                    'user_rejected', 'shadow', 'invalidated'
              )
            """,
            (changed_at, changed_at, target_id),
        )
        return max(int(cursor.rowcount or 0), 0)
    if target_kind == "review":
        return await close_pending_review_on_connection(
            db,
            review_id=target_id,
            reason=reason,
            changed_at=changed_at,
        )
    cursor = await db.execute(
        """
        UPDATE knowledge_graph
        SET status = 'archived', status_reason = ?,
            valid_to = COALESCE(valid_to, ?), deprecated_at = COALESCE(deprecated_at, ?),
            updated_at = ?
        WHERE triple_id = ? AND status = 'active'
        """,
        (
            reason,
            changed_at,
            changed_at,
            changed_at,
            target_id,
        ),
    )
    return max(int(cursor.rowcount or 0), 0)


def _event_ids(raw: Any) -> set[str]:
    decoded = _decode_json(raw)
    if not isinstance(decoded, list):
        return set()
    return {str(item).strip() for item in decoded if str(item).strip()}


def _bounded_event_ids(event_ids: Any) -> list[str]:
    normalized = sorted({str(item).strip() for item in event_ids if str(item).strip()})
    limit = max_evidence_event_ids()
    return normalized[-limit:] if len(normalized) > limit else normalized


def _decode_json(raw: Any) -> Any | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


__all__ = [
    "ClaimTargetRetirementResult",
    "ReprojectedClaimRouteResult",
    "reproject_claim_route",
    "retire_claim_target_authority_on_connection",
]
