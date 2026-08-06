"""Idempotent persistence for governed pending-memory reviews."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ...clear_generation import memory_clear_generation_on_connection
from ..batch_models import L2ProjectionLease
from ..claims.identity import canonical_json
from ..claims.outcomes import (
    ClaimTargetOutcomeContext,
    append_claim_target_outcomes_on_connection,
)
from ..projection.fencing import (
    assert_current_projection_attempt,
    assert_projection_attempt_key,
    normalize_projection_leases,
)
from ..assertions.write import normalize_assertion_candidate
from .models import (
    PendingReviewAction,
    PendingReviewProposal,
    PendingReviewResolution,
    PendingReviewWriteResult,
)


class PendingReviewNotFoundError(LookupError):
    """Raised when a review ID does not exist."""


class PendingReviewConflictError(RuntimeError):
    """Raised when optimistic version or governing inputs are stale."""


class PendingReviewRepository:
    """Persist review work items and Claim receipts in one transaction."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def upsert_with_receipt(
        self,
        proposal: PendingReviewProposal,
        *,
        claim_outcome_context: ClaimTargetOutcomeContext,
        projection_leases: Iterable[L2ProjectionLease],
    ) -> PendingReviewWriteResult:
        """Create or merge one pending item without replay timestamp churn."""

        normalized = _normalize_proposal(proposal)
        leases = normalize_projection_leases(projection_leases, required=True)
        assert_projection_attempt_key(claim_outcome_context.attempt_key, leases)
        if tuple(sorted(claim_outcome_context.claim_ids)) != normalized.claim_ids:
            raise ValueError("review Claim IDs must match the projection receipt context")

        async with sqlite_connection_async(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                await assert_current_projection_attempt(db, leases)
                generation = await memory_clear_generation_on_connection(db)
                dedupe_key = _dedupe_key(normalized)
                decision_key = _decision_key(
                    normalized,
                    dedupe_key=dedupe_key,
                    source_generation=generation,
                )
                existing = await _review_by_decision_key(db, decision_key)
                created = False
                changed = False
                if existing is None:
                    existing = await _pending_review_by_dedupe_key(db, dedupe_key)
                    now = time.time()
                    if existing is None:
                        review_id = f"rev_{uuid.uuid4().hex}"
                        await db.execute(
                            """
                            INSERT INTO l2_pending_reviews(
                                review_id, decision_key, dedupe_key, subject_id, kind,
                                slot_key, value_fingerprint, semantic_lineage_key,
                                claim_ids_json, reason_code, proposed_json,
                                route_contract_version, evidence_rule_version,
                                source_generation, status, version, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 1, ?, ?)
                            """,
                            (
                                review_id,
                                decision_key,
                                dedupe_key,
                                normalized.subject_id,
                                normalized.kind,
                                normalized.slot_key,
                                normalized.value_fingerprint,
                                normalized.semantic_lineage_key,
                                canonical_json(normalized.claim_ids),
                                normalized.reason_code,
                                canonical_json(normalized.proposed),
                                normalized.route_contract_version,
                                normalized.evidence_rule_version,
                                generation,
                                now,
                                now,
                            ),
                        )
                        created = True
                        changed = True
                        existing = await _review_by_id(db, review_id)
                    else:
                        await db.execute(
                            """
                            UPDATE l2_pending_reviews
                            SET decision_key = ?, claim_ids_json = ?, reason_code = ?,
                                proposed_json = ?, route_contract_version = ?,
                                evidence_rule_version = ?, source_generation = ?,
                                version = version + 1, updated_at = ?
                            WHERE review_id = ? AND status = 'pending'
                            """,
                            (
                                decision_key,
                                canonical_json(normalized.claim_ids),
                                normalized.reason_code,
                                canonical_json(normalized.proposed),
                                normalized.route_contract_version,
                                normalized.evidence_rule_version,
                                generation,
                                now,
                                str(existing["review_id"]),
                            ),
                        )
                        changed = True
                        existing = await _review_by_id(db, str(existing["review_id"]))
                if existing is None:
                    raise RuntimeError("pending review write did not produce a row")

                review_id = str(existing["review_id"])
                status = str(existing["status"])
                version = int(existing["version"])
                await append_claim_target_outcomes_on_connection(
                    db,
                    context=claim_outcome_context,
                    target_kind="review",
                    target_id=review_id,
                    target_slot_key=normalized.slot_key,
                    outcome="pending" if status == "pending" else status,
                    reason_code=normalized.reason_code,
                    details={"decision_key": decision_key, "review_version": version},
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise

        return PendingReviewWriteResult(
            review_id=review_id,
            status=status,
            version=version,
            created=created,
            changed=changed,
            atomically_completed_claim_ids=normalized.claim_ids,
        )

    async def list(
        self,
        *,
        subject_id: str | None = None,
        status: str = "pending",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List normalized review records for product read models."""

        clauses = ["status = ?"]
        args: list[Any] = [str(status or "pending").strip()]
        if subject_id:
            clauses.append("subject_id = ?")
            args.append(str(subject_id).strip())
        args.append(max(1, min(int(limit), 500)))
        async with sqlite_connection_async(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"""
                SELECT * FROM l2_pending_reviews
                WHERE {' AND '.join(clauses)}
                ORDER BY updated_at DESC, review_id
                LIMIT ?
                """,
                tuple(args),
            ) as cursor:
                return [_decode_review(row) for row in await cursor.fetchall()]

    async def resolve(
        self,
        *,
        store: Any,
        review_id: str,
        action: PendingReviewAction,
        expected_version: int,
        resolved_by: str,
        resolution_event_id: str,
        edit: Mapping[str, Any] | None,
        route_contract_version: int,
        evidence_rule_version: int,
    ) -> PendingReviewResolution:
        """Resolve a review and its optional Assertion in one write transaction."""

        normalized_review_id = _required_text(review_id, "review_id")
        normalized_action = _required_text(action, "action")
        if normalized_action not in {"confirm", "reject", "confirm_with_edit"}:
            raise ValueError("unsupported pending review action")
        if normalized_action == "confirm_with_edit" and not edit:
            raise ValueError("confirm_with_edit requires an edit payload")
        if normalized_action != "confirm_with_edit" and edit:
            raise ValueError("edit payload is only valid for confirm_with_edit")

        assertion_id: str | None = None
        assertion_slot_key: str | None = None
        now = time.time()
        async with sqlite_connection_async(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            try:
                review = await _review_by_id(db, normalized_review_id)
                if review is None:
                    raise PendingReviewNotFoundError("pending review was not found")
                if str(review["status"]) != "pending" or int(review["version"]) != int(
                    expected_version
                ):
                    raise PendingReviewConflictError("pending review version is stale")
                generation = await memory_clear_generation_on_connection(db)
                if (
                    int(review["source_generation"]) != generation
                    or int(review["route_contract_version"]) != route_contract_version
                    or int(review["evidence_rule_version"]) != evidence_rule_version
                ):
                    raise PendingReviewConflictError("pending review policy inputs are stale")

                claim_ids = await _active_review_claim_ids(
                    db,
                    review_id=normalized_review_id,
                )
                stored_claim_ids = tuple(sorted(json.loads(str(review["claim_ids_json"]))))
                if not claim_ids or claim_ids != stored_claim_ids:
                    raise PendingReviewConflictError("pending review Claim support is stale")

                resolution_payload: dict[str, Any] = {
                    "action": normalized_action,
                    "edit": dict(edit or {}),
                }
                if normalized_action != "reject":
                    proposal = json.loads(str(review["proposed_json"]))
                    if not isinstance(proposal, dict):
                        raise RuntimeError("pending review proposal is invalid")
                    candidate = await _confirmed_candidate(
                        db,
                        proposal=proposal,
                        claim_ids=claim_ids,
                        action=normalized_action,
                        edit=edit,
                        now=now,
                    )
                    normalized_candidate = normalize_assertion_candidate(
                        candidate,
                        store,
                        now=now,
                    )
                    existing = await store._fetch_active_assertion(db, normalized_candidate)
                    trait_name = str(normalized_candidate["trait_name"])
                    if existing is None:
                        result = await store._insert_new_assertion(
                            db=db,
                            candidate=normalized_candidate,
                            trait_name=trait_name,
                            now=now,
                        )
                    else:
                        result = await store._merge_existing_assertion(
                            db=db,
                            existing=existing,
                            candidate=normalized_candidate,
                            trait_name=trait_name,
                            now=now,
                        )
                    assertion_id = result.assertion_id
                    assertion_slot_key = str(normalized_candidate["slot_key"])
                    await db.execute(
                        """
                        UPDATE tom_trait_assertions
                        SET authority_ref = ?, user_feedback = ?, user_feedback_at = ?,
                            source_domain = 'user_feedback', validation_state = 'stable',
                            status = 'stable', confidence_score = MAX(confidence_score, 0.95),
                            updated_at = ?
                        WHERE assertion_id = ?
                        """,
                        (
                            normalized_review_id,
                            normalized_action,
                            now,
                            now,
                            assertion_id,
                        ),
                    )

                receipt_context = ClaimTargetOutcomeContext(
                    claim_ids=claim_ids,
                    attempt_key=(
                        f"review-resolve:{normalized_review_id}:v{int(expected_version)}"
                    ),
                    route_contract_version=route_contract_version,
                )
                await db.execute(
                    """
                    UPDATE l2_claim_projection_outcomes
                    SET invalidated_at = ?, invalidated_reason = 'review_resolved'
                    WHERE target_kind = 'review' AND target_id = ?
                      AND outcome = 'pending' AND invalidated_at IS NULL
                    """,
                    (now, normalized_review_id),
                )
                await append_claim_target_outcomes_on_connection(
                    db,
                    context=receipt_context,
                    target_kind="review",
                    target_id=normalized_review_id,
                    target_slot_key=str(review["slot_key"]),
                    outcome="rejected" if normalized_action == "reject" else "confirmed",
                    reason_code=f"user_{normalized_action}",
                    details={"resolution_event_id": resolution_event_id},
                    created_at=now,
                )
                if assertion_id is not None:
                    await append_claim_target_outcomes_on_connection(
                        db,
                        context=receipt_context,
                        target_kind="assertion",
                        target_id=assertion_id,
                        target_slot_key=assertion_slot_key,
                        outcome="projected",
                        reason_code=f"review_{normalized_action}",
                        details={"review_id": normalized_review_id},
                        created_at=now,
                    )
                status = "rejected" if normalized_action == "reject" else "confirmed"
                await db.execute(
                    """
                    UPDATE l2_pending_reviews
                    SET status = ?, version = version + 1,
                        resolution_action = ?, resolution_payload_json = ?,
                        resolution_event_id = ?, resolved_by = ?,
                        resolved_at = ?, updated_at = ?
                    WHERE review_id = ? AND status = 'pending' AND version = ?
                    """,
                    (
                        status,
                        normalized_action,
                        canonical_json(resolution_payload),
                        _required_text(resolution_event_id, "resolution_event_id"),
                        _required_text(resolved_by, "resolved_by"),
                        now,
                        now,
                        normalized_review_id,
                        int(expected_version),
                    ),
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise

        return PendingReviewResolution(
            review_id=normalized_review_id,
            status=status,
            version=int(expected_version) + 1,
            assertion_id=assertion_id,
        )


async def reconcile_pending_review_support_on_connection(
    db: aiosqlite.Connection,
    *,
    review_id: str,
    claim_ids: tuple[str, ...],
    evidence_event_ids: tuple[str, ...],
    changed_at: float,
    close_reason: str,
) -> bool:
    """Recompute one pending review after Claim authority changes."""

    review = await _review_by_id(db, review_id)
    if review is None or str(review["status"]) != "pending":
        return False
    normalized_claim_ids = tuple(sorted({str(item) for item in claim_ids if str(item).strip()}))
    if not normalized_claim_ids:
        cursor = await db.execute(
            """
            UPDATE l2_pending_reviews
            SET status = 'closed', close_reason = ?, version = version + 1,
                resolved_at = ?, updated_at = ?
            WHERE review_id = ? AND status = 'pending'
            """,
            (close_reason, changed_at, changed_at, review_id),
        )
        return bool(cursor.rowcount)

    proposal_payload = json.loads(str(review["proposed_json"]))
    if not isinstance(proposal_payload, dict):
        raise RuntimeError("pending review proposal is invalid")
    proposal_payload["evidence_events"] = list(evidence_event_ids)
    proposal_payload["supporting_claim_ids"] = list(normalized_claim_ids)
    normalized = PendingReviewProposal(
        subject_id=str(review["subject_id"]),
        kind=str(review["kind"]),  # type: ignore[arg-type]
        slot_key=str(review["slot_key"]),
        value_fingerprint=str(review["value_fingerprint"]),
        semantic_lineage_key=str(review["semantic_lineage_key"]),
        claim_ids=normalized_claim_ids,
        reason_code=str(review["reason_code"]),
        proposed=proposal_payload,
        route_contract_version=int(review["route_contract_version"]),
        evidence_rule_version=int(review["evidence_rule_version"]),
    )
    decision_key = _decision_key(
        normalized,
        dedupe_key=str(review["dedupe_key"]),
        source_generation=int(review["source_generation"]),
    )
    current_claims = tuple(sorted(json.loads(str(review["claim_ids_json"]))))
    current_proposal = json.loads(str(review["proposed_json"]))
    if current_claims == normalized_claim_ids and current_proposal == proposal_payload:
        return False
    existing_decision = await _review_by_decision_key(db, decision_key)
    if (
        existing_decision is not None
        and str(existing_decision["review_id"]) != review_id
    ):
        if str(existing_decision["status"]) == "pending":
            raise RuntimeError("pending review dedupe invariant was violated")
        closed = await close_pending_review_on_connection(
            db,
            review_id=review_id,
            reason="review_decision_already_resolved",
            changed_at=changed_at,
        )
        if closed:
            await db.execute(
                """
                UPDATE l2_claim_projection_outcomes
                SET invalidated_at = ?,
                    invalidated_reason = 'review_decision_already_resolved'
                WHERE target_kind = 'review' AND target_id = ?
                  AND outcome = 'pending' AND invalidated_at IS NULL
                """,
                (changed_at, review_id),
            )
        return bool(closed)
    cursor = await db.execute(
        """
        UPDATE l2_pending_reviews
        SET decision_key = ?, claim_ids_json = ?, proposed_json = ?,
            version = version + 1, updated_at = ?
        WHERE review_id = ? AND status = 'pending'
        """,
        (
            decision_key,
            canonical_json(normalized_claim_ids),
            canonical_json(proposal_payload),
            changed_at,
            review_id,
        ),
    )
    return bool(cursor.rowcount)


async def close_pending_review_on_connection(
    db: aiosqlite.Connection,
    *,
    review_id: str,
    reason: str,
    changed_at: float,
) -> int:
    """Close one pending review without committing the caller's transaction."""

    cursor = await db.execute(
        """
        UPDATE l2_pending_reviews
        SET status = 'closed', close_reason = ?, version = version + 1,
            resolved_at = ?, updated_at = ?
        WHERE review_id = ? AND status = 'pending'
        """,
        (reason, changed_at, changed_at, review_id),
    )
    return max(int(cursor.rowcount or 0), 0)


def _normalize_proposal(proposal: PendingReviewProposal) -> PendingReviewProposal:
    subject_id = _required_text(proposal.subject_id, "subject_id")
    kind = _required_text(proposal.kind, "kind")
    if kind not in {
        "goal_currentness",
        "assertion_currentness",
        "materialization",
        "conflict",
    }:
        raise ValueError("unsupported pending review kind")
    claim_ids = tuple(
        sorted({_required_text(claim_id, "claim_id") for claim_id in proposal.claim_ids})
    )
    if not claim_ids:
        raise ValueError("pending review must have supporting Claims")
    proposed = dict(proposal.proposed)
    if not proposed:
        raise ValueError("pending review proposal must not be empty")
    return PendingReviewProposal(
        subject_id=subject_id,
        kind=kind,  # type: ignore[arg-type]
        slot_key=_required_text(proposal.slot_key, "slot_key"),
        value_fingerprint=str(proposal.value_fingerprint or "").strip(),
        semantic_lineage_key=str(proposal.semantic_lineage_key or "").strip(),
        claim_ids=claim_ids,
        reason_code=_required_text(proposal.reason_code, "reason_code"),
        proposed=proposed,
        route_contract_version=max(0, int(proposal.route_contract_version)),
        evidence_rule_version=max(0, int(proposal.evidence_rule_version)),
    )


def _dedupe_key(proposal: PendingReviewProposal) -> str:
    return _hash_key(
        "review-dedupe",
        {
            "subject_id": proposal.subject_id,
            "kind": proposal.kind,
            "slot_key": proposal.slot_key,
            "value_fingerprint": proposal.value_fingerprint,
        },
    )


def _decision_key(
    proposal: PendingReviewProposal,
    *,
    dedupe_key: str,
    source_generation: int,
) -> str:
    return _hash_key(
        "review-decision",
        {
            "dedupe_key": dedupe_key,
            "claim_ids": proposal.claim_ids,
            "proposed": proposal.proposed,
            "route_contract_version": proposal.route_contract_version,
            "evidence_rule_version": proposal.evidence_rule_version,
            "source_generation": source_generation,
        },
    )


def _hash_key(prefix: str, payload: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


async def _review_by_decision_key(
    db: aiosqlite.Connection,
    decision_key: str,
) -> aiosqlite.Row | None:
    async with db.execute(
        "SELECT * FROM l2_pending_reviews WHERE decision_key = ?",
        (decision_key,),
    ) as cursor:
        return await cursor.fetchone()


async def _pending_review_by_dedupe_key(
    db: aiosqlite.Connection,
    dedupe_key: str,
) -> aiosqlite.Row | None:
    async with db.execute(
        "SELECT * FROM l2_pending_reviews WHERE dedupe_key = ? AND status = 'pending'",
        (dedupe_key,),
    ) as cursor:
        return await cursor.fetchone()


async def _review_by_id(db: aiosqlite.Connection, review_id: str) -> aiosqlite.Row | None:
    async with db.execute(
        "SELECT * FROM l2_pending_reviews WHERE review_id = ?",
        (review_id,),
    ) as cursor:
        return await cursor.fetchone()


async def _active_review_claim_ids(
    db: aiosqlite.Connection,
    *,
    review_id: str,
) -> tuple[str, ...]:
    async with db.execute(
        """
        SELECT DISTINCT outcomes.claim_id
        FROM l2_claim_projection_outcomes AS outcomes
        JOIN l2_grounded_claims AS claims ON claims.claim_id = outcomes.claim_id
        WHERE outcomes.target_kind = 'review'
          AND outcomes.target_id = ?
          AND outcomes.invalidated_at IS NULL
          AND claims.availability = 'active'
        ORDER BY outcomes.claim_id
        """,
        (review_id,),
    ) as cursor:
        return tuple(str(row[0]) for row in await cursor.fetchall())


async def _confirmed_candidate(
    db: aiosqlite.Connection,
    *,
    proposal: dict[str, Any],
    claim_ids: tuple[str, ...],
    action: str,
    edit: Mapping[str, Any] | None,
    now: float,
) -> dict[str, Any]:
    placeholders = ", ".join("?" for _ in claim_ids)
    async with db.execute(
        f"""
        SELECT DISTINCT evidence.event_id, evidence.event_time
        FROM l2_claim_evidence AS evidence
        WHERE evidence.claim_id IN ({placeholders})
          AND evidence.link_role = 'supporting'
        ORDER BY evidence.event_time, evidence.event_id
        """,
        claim_ids,
    ) as cursor:
        evidence_rows = await cursor.fetchall()
    event_ids = [str(row[0]) for row in evidence_rows]
    if not event_ids:
        raise PendingReviewConflictError("pending review evidence is unavailable")
    event_times = [float(row[1]) for row in evidence_rows if row[1] is not None]
    candidate = dict(proposal)
    candidate["source_domain"] = "user_feedback"
    candidate["inference_depth"] = "explicit"
    candidate["validation_state"] = "stable"
    candidate["confidence_score"] = max(float(candidate.get("confidence_score") or 0.0), 0.95)
    candidate["evidence_events"] = event_ids
    candidate["first_inferred_at"] = min(event_times) if event_times else now
    candidate["last_validated_at"] = now
    candidate["decay_anchor_at"] = now
    if action == "confirm_with_edit":
        edit_payload = dict(edit or {})
        unsupported = set(edit_payload).difference({"trait_value", "natural_summary"})
        if unsupported:
            raise ValueError("pending review edit contains unsupported fields")
        if "trait_value" in edit_payload:
            candidate["trait_value"] = _required_text(
                edit_payload["trait_value"],
                "edit.trait_value",
            )
        if "natural_summary" in edit_payload:
            candidate["natural_summary"] = _required_text(
                edit_payload["natural_summary"],
                "edit.natural_summary",
            )[:500]
        candidate["semantic_route_slot_key"] = _edited_slot_key(candidate)
    return candidate


def _edited_slot_key(candidate: Mapping[str, Any]) -> str:
    return _hash_key(
        "review-edit-slot",
        {
            "entity_id": candidate.get("entity_id"),
            "trait_family": candidate.get("trait_family"),
            "trait_name": candidate.get("trait_name"),
            "trait_value": candidate.get("trait_value"),
            "target_entity_id": candidate.get("target_entity_id"),
        },
    )


def _decode_review(row: aiosqlite.Row) -> dict[str, Any]:
    result = dict(row)
    for source, target in (
        ("claim_ids_json", "claim_ids"),
        ("proposed_json", "proposed"),
        ("resolution_payload_json", "resolution_payload"),
    ):
        raw = result.pop(source, None)
        result[target] = json.loads(str(raw)) if raw is not None else None
    return result


def _required_text(value: object, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be blank")
    return text


__all__ = [
    "close_pending_review_on_connection",
    "PendingReviewConflictError",
    "PendingReviewNotFoundError",
    "PendingReviewRepository",
    "reconcile_pending_review_support_on_connection",
]
