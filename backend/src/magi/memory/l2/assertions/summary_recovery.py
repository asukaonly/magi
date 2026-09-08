"""Bounded repair of derived assertion wording from immutable grounded Claims."""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ..claim_text import load_claim_texts, persisted_claim_to_phase1
from ..claims.outcomes import ClaimTargetOutcomeContext, append_claim_target_outcomes_on_connection
from ..corrections.fingerprints import assertion_claim_fingerprint, canonical_claim_value
from ..corrections.forget_governance import filter_candidate_evidence_by_forget_rules
from ..corrections.models import CorrectionTargetKind
from ..corrections.policy import CorrectionPolicyAction, CorrectionPolicyEvaluator
from ..corrections.repository import MemoryCorrectionRepository
from ..factual_rendering import render_grounded_fact
from ..semantic_routing import SemanticRouteInput, derive_semantic_route
from .state_machine import ACTIVE_VALIDATION_STATES

SUMMARY_RECOVERY_VERSION = 1


@dataclass(frozen=True, slots=True)
class AssertionSummaryRecoveryRequest:
    """The exact persisted assertion snapshot approved for a wording rebuild."""

    assertion_id: str
    expected_updated_at: float
    expected_summary: str


@dataclass(frozen=True, slots=True)
class AssertionSummaryRecoveryItem:
    assertion_id: str
    status: str
    previous_summary: str | None = None
    rebuilt_summary: str | None = None
    claim_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AssertionSummaryRecoveryResult:
    """Preview or committed changes, plus revisions for normal view rebuilding."""

    dry_run: bool
    items: tuple[AssertionSummaryRecoveryItem, ...]
    subject_revisions: Mapping[str, int]
    l3_summary_ids: tuple[str, ...] = ()


async def recover_assertion_summaries(
    db_path: str,
    *,
    requests: Sequence[AssertionSummaryRecoveryRequest],
    dry_run: bool = True,
    language: str | None = None,
) -> AssertionSummaryRecoveryResult:
    """Rebuild an explicit bounded set without replaying extraction or promotion.

    Each request pins the observed assertion timestamp and summary. Current
    Claims, projection receipts, evidence, correction rules and source-job state
    are checked under the same transaction as the write. Missing support or a
    competing projection refuses that item. A preview rolls back every write.

    Successful writes only replace derived wording and its update timestamp,
    append recovery receipts, invalidate directly dependent L3 insights, and
    advance subject revisions. Existing profile
    and portrait repositories then reject old caches, including after a crash;
    their normal builders can regenerate the affected subjects without a model.
    """
    if not requests or len(requests) > 100:
        raise ValueError("Provide between 1 and 100 explicit assertion snapshots")
    identities = [request.assertion_id for request in requests]
    if len(set(identities)) != len(identities) or any(not value.strip() for value in identities):
        raise ValueError("Assertion snapshots must contain unique nonblank identities")
    if any(not math.isfinite(request.expected_updated_at) for request in requests):
        raise ValueError("Assertion snapshot timestamps must be finite")

    results: list[AssertionSummaryRecoveryItem] = []
    subjects: set[str] = set()
    revisions: dict[str, int] = {}
    l3_summary_ids: tuple[str, ...] = ()
    async with sqlite_connection_async(db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("BEGIN IMMEDIATE")
        try:
            for request in requests:
                result, subject = await _recover_one(
                    db, request=request, dry_run=dry_run, language=language,
                )
                results.append(result)
                if subject:
                    subjects.add(subject)
            rebuilt_ids = [
                item.assertion_id for item in results
                if item.status in {"rebuilt", "would_rebuild"}
            ]
            if rebuilt_ids:
                l3_summary_ids = await _dependent_l3_summary_ids(db, rebuilt_ids)
            if dry_run:
                await db.rollback()
            else:
                repository = MemoryCorrectionRepository(db_path)
                if rebuilt_ids:
                    subjects.update(await repository.invalidate_l3_insights_on_connection(
                        db,
                        source_kind="assertion",
                        source_ids=rebuilt_ids,
                        summary_ids=l3_summary_ids,
                    ))
                for subject in sorted(subjects):
                    revisions[subject] = await repository.bump_subject_revision(
                        db, subject_key=subject,
                    )
                await db.commit()
        except Exception:
            await db.rollback()
            raise
    return AssertionSummaryRecoveryResult(dry_run, tuple(results), revisions, l3_summary_ids)


async def _dependent_l3_summary_ids(
    db: aiosqlite.Connection, assertion_ids: Sequence[str],
) -> tuple[str, ...]:
    async with db.execute(
        """
        SELECT DISTINCT summaries.summary_id
        FROM memory_derivation_dependencies AS dependencies
        JOIN summaries ON summaries.summary_id = dependencies.artifact_id
        WHERE dependencies.artifact_kind = 'l3_insight'
          AND dependencies.source_kind = 'assertion'
          AND dependencies.source_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
          AND summaries.summary_type = 'insight'
          AND summaries.derivation_state IN ('current', 'stale')
          AND COALESCE(summaries.review_state, '') != 'rejected'
        ORDER BY summaries.summary_id
        """, (json.dumps(list(assertion_ids)),),
    ) as cursor:
        return tuple(str(row[0]) for row in await cursor.fetchall())


async def _recover_one(
    db: aiosqlite.Connection,
    *,
    request: AssertionSummaryRecoveryRequest,
    dry_run: bool,
    language: str | None,
) -> tuple[AssertionSummaryRecoveryItem, str | None]:
    def blocked(status: str) -> tuple[AssertionSummaryRecoveryItem, None]:
        return AssertionSummaryRecoveryItem(request.assertion_id, status), None

    async with db.execute(
        "SELECT * FROM tom_trait_assertions WHERE assertion_id = ?", (request.assertion_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return blocked("assertion_missing")
    assertion = dict(row)
    if (
        float(assertion["updated_at"]) != request.expected_updated_at
        or str(assertion["natural_summary"] or "") != request.expected_summary
    ):
        return blocked("snapshot_changed")
    if assertion["status"] not in ACTIVE_VALIDATION_STATES:
        return blocked("assertion_not_active")
    if assertion.get("authority_ref") or assertion.get("user_feedback"):
        return blocked("user_governed")
    policy = await CorrectionPolicyEvaluator().evaluate_assertion(db, assertion)
    if policy.action != CorrectionPolicyAction.ACCEPT_ACTIVE or policy.correction_id:
        return blocked("user_governed")

    claims = await _supporting_claims(db, request.assertion_id)
    if not claims or any(claim["availability"] != "active" for claim in claims):
        return blocked("claim_support_unavailable")
    claim_ids = tuple(str(claim["claim_id"]) for claim in claims)
    evidence = await _claim_evidence(db, claim_ids)
    if {str(item["claim_id"]) for item in evidence if item["link_role"] == "supporting"} != set(claim_ids):
        return blocked("claim_evidence_unavailable")
    event_ids = sorted({str(item["event_id"]) for item in evidence})
    async with db.execute(
        """
        SELECT 1 FROM l2_projection_jobs
        WHERE event_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
          AND status != 'completed'
        LIMIT 1
        """, (json.dumps(event_ids),),
    ) as cursor:
        if await cursor.fetchone() is not None:
            return blocked("source_projection_not_complete")
    if not await _evidence_is_retained(db, assertion, evidence, event_ids):
        return blocked("source_governed")

    texts = await load_claim_texts(db, list(claim_ids))
    if any(claim_id not in texts for claim_id in claim_ids):
        return blocked("claim_text_unavailable")
    if any(
        text.subject_entity_id != assertion["entity_id"]
        or (text.object_entity_id or "") != str(assertion["target_entity_id"] or "")
        for text in texts.values()
    ):
        return blocked("claim_identity_changed")
    for claim in claims:
        phase1 = persisted_claim_to_phase1(claim)
        text = texts[str(claim["claim_id"])]
        route = derive_semantic_route(SemanticRouteInput(
            claim_id=str(claim["claim_id"]),
            subject_id=str(text.subject_entity_id),
            subject_type=str(claim["subject_type"]),
            canonical_predicate=str(claim["canonical_predicate"]),
            fact_kind=str(claim["fact_kind"]),
            object_type=str(claim["object_type"]),
            object_value=json.loads(claim["object_value_json"] or "null"),
            object_entity_id=text.object_entity_id,
            temporal_cue=str(claim["temporal_cue"]),
            specificity=str(claim["specificity"]),
            target_from=phase1.target_from,
            target_to=phase1.target_to,
            raw_time_expression=phase1.raw_time_expression,
            time_resolution=str((phase1.raw_time_frame or {}).get("resolution") or "unscheduled"),
            time_frame=phase1.raw_time_frame,
            polarity=str(claim["polarity"]),
        ))
        expected_value = route.object_surface if route.family == "goal_profile" else route.canonical_value
        if (
            not route.can_project_assertion
            or route.slot_key != assertion["slot_key"]
            or route.trait_code != assertion["trait_name"]
            or route.family != assertion["trait_family"]
            or canonical_claim_value(expected_value) != canonical_claim_value(assertion["trait_value"])
        ):
            return blocked("claim_semantics_changed")
    summaries = {
        render_grounded_fact(
            persisted_claim_to_phase1(claim),
            resolved_text=texts[str(claim["claim_id"])], language=language,
        )
        for claim in claims
    }
    if "" in summaries or len(summaries) != 1:
        return blocked("claim_text_incomplete_or_ambiguous")
    summary = summaries.pop()
    if summary == request.expected_summary:
        return AssertionSummaryRecoveryItem(
            request.assertion_id, "unchanged", request.expected_summary, summary, claim_ids,
        ), None
    if not dry_run:
        changed_at = max(time.time(), request.expected_updated_at + 0.000001)
        await db.execute(
            "UPDATE tom_trait_assertions SET natural_summary = ?, updated_at = ? WHERE assertion_id = ?",
            (summary, changed_at, request.assertion_id),
        )
        fingerprint = hashlib.sha256(json.dumps(
            [request.assertion_id, request.expected_updated_at, request.expected_summary, summary],
            ensure_ascii=False, separators=(",", ":"),
        ).encode()).hexdigest()[:32]
        await append_claim_target_outcomes_on_connection(
            db,
            context=ClaimTargetOutcomeContext(
                claim_ids=claim_ids,
                attempt_key=f"summary-recovery:v{SUMMARY_RECOVERY_VERSION}:{fingerprint}",
                route_contract_version=int(assertion.get("route_contract_version") or 0),
            ),
            target_kind="assertion_summary",
            target_id=request.assertion_id,
            target_slot_key=assertion.get("slot_key"),
            outcome="rebuilt",
            reason_code="host_resolved_claim_text",
            details={"summary_recovery_version": SUMMARY_RECOVERY_VERSION},
            created_at=changed_at,
        )
    return AssertionSummaryRecoveryItem(
        request.assertion_id, "would_rebuild" if dry_run else "rebuilt",
        request.expected_summary, summary, claim_ids,
    ), str(assertion["entity_id"])


async def _supporting_claims(db: aiosqlite.Connection, assertion_id: str) -> list[dict[str, Any]]:
    async with db.execute(
        """
        SELECT DISTINCT claims.* FROM l2_grounded_claims AS claims
        JOIN l2_claim_projection_outcomes AS outcomes ON outcomes.claim_id = claims.claim_id
        JOIN tom_trait_assertions AS assertion ON assertion.assertion_id = outcomes.target_id
        WHERE outcomes.target_kind = 'assertion' AND outcomes.target_id = ?
          AND outcomes.outcome = 'projected' AND outcomes.invalidated_at IS NULL
          AND outcomes.target_slot_key = assertion.slot_key
        ORDER BY claims.created_at, claims.claim_id
        """, (assertion_id,),
    ) as cursor:
        return [dict(row) for row in await cursor.fetchall()]


async def _claim_evidence(
    db: aiosqlite.Connection, claim_ids: tuple[str, ...],
) -> list[dict[str, Any]]:
    async with db.execute(
        """
        SELECT * FROM l2_claim_evidence
        WHERE claim_id IN (SELECT CAST(value AS TEXT) FROM json_each(?))
        """, (json.dumps(claim_ids),),
    ) as cursor:
        return [dict(row) for row in await cursor.fetchall()]


async def _evidence_is_retained(
    db: aiosqlite.Connection,
    assertion: Mapping[str, Any],
    evidence: list[dict[str, Any]],
    event_ids: list[str],
) -> bool:
    # The admission helper also records discovered barriers. Recovery only reads
    # its verdict; the source-governance owner retains responsibility for writes.
    await db.execute("SAVEPOINT summary_recovery_governance")
    try:
        filtered = await filter_candidate_evidence_by_forget_rules(
            db,
            target_kind=CorrectionTargetKind.ASSERTION,
            semantic_fingerprint=assertion_claim_fingerprint(
                slot_key_value=str(assertion["slot_key"]), trait_value=assertion["trait_value"],
            ),
            event_ids=event_ids,
            event_timestamps={str(item["event_id"]): item["event_time"] for item in evidence},
            observed_at=float(assertion["last_validated_at"]),
            observed_from=float(assertion["first_inferred_at"]),
            observed_to=float(assertion["last_validated_at"]),
            entity_ids=(str(assertion["entity_id"]), str(assertion["target_entity_id"])),
        )
        return set(filtered.retained_event_ids) == set(event_ids)
    finally:
        await db.execute("ROLLBACK TO summary_recovery_governance")
        await db.execute("RELEASE summary_recovery_governance")


__all__ = [
    "AssertionSummaryRecoveryItem", "AssertionSummaryRecoveryRequest",
    "AssertionSummaryRecoveryResult", "recover_assertion_summaries",
]
