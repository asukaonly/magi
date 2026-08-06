"""Governed pending-memory review persistence and resolution tests."""

from __future__ import annotations

import asyncio

import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.memory.l2.claims.identity import derive_claim_identity_key
from magi.memory.l2.claims.models import (
    ClaimEvidenceInput,
    GroundedClaimInput,
    ProjectionOutcomeInput,
)
from magi.memory.l2.claims.outcomes import ClaimTargetOutcomeContext
from magi.memory.l2.claims.reprojection_write import reproject_claim_route
from magi.memory.l2.models import L2ProjectionLease, derive_projection_attempt_key
from magi.memory.l2.reviews import PendingReviewProposal
from magi.memory.l2.reviews.repository import PendingReviewConflictError
from magi.memory.l2.semantic_routing import (
    ROUTE_CONTRACT_VERSION,
    SemanticRouteInput,
    derive_semantic_route,
)


async def _running_lease(store, event_id: str) -> L2ProjectionLease:  # type: ignore[no-untyped-def]
    return (await _running_leases(store, [event_id]))[0]


async def _running_leases(store, event_ids: list[str]) -> list[L2ProjectionLease]:  # type: ignore[no-untyped-def]
    for event_id in event_ids:
        await store.enqueue_projection_job(
            event_id=event_id,
            source="chat",
            event_type="UserMessage",
        )
    rows = await store.claim_projection_jobs(
        consumer_name="review-test",
        limit=len(event_ids),
    )
    leases = [
        L2ProjectionLease(
            event_id=str(row["event_id"]),
            lease_token=str(row["lease_token"]),
            attempt_count=int(row["attempt_count"]),
        )
        for row in rows
    ]
    assert await store.bind_projection_job_batch(leases, consumer_name="review-test") == len(
        leases
    )
    assert await store.mark_projection_jobs_running(leases, consumer_name="review-test") == len(
        leases
    )
    return leases


async def _ground_claim(
    store,  # type: ignore[no-untyped-def]
    *,
    event_id: str,
    leases: list[L2ProjectionLease],
    value: str = "今年秋天去海边",
) -> str:
    identity = derive_claim_identity_key(
        extractor_contract_version=4,
        evidence_rule_version=2,
        user_id="u1",
        subject_ref="user:u1",
        subject_type="user",
        canonical_predicate="PLANS_TO",
        fact_kind="future_intent",
        object_type="activity",
        polarity="positive",
        specificity="concrete",
        temporal_cue="one_off",
        fact_valid_from=None,
        fact_valid_to=None,
        target_from=None,
        target_to=None,
        raw_time_frame={"raw": "秋天", "resolution": "unresolved_text"},
        evidence_mode="direct",
        object_surface=value,
        object_value=value,
        supporting_event_ids=[event_id],
        antecedent_event_ids=[],
    )
    stored = await store.upsert_grounded_claim(
        claim=GroundedClaimInput(
            identity_key=identity,
            extractor_contract_version=4,
            evidence_rule_version=2,
            origin_attempt_key=derive_projection_attempt_key(leases),
            profile_id="chat.user_message",
            user_id="u1",
            subject_ref="user:u1",
            subject_type="user",
            canonical_predicate="PLANS_TO",
            fact_kind="future_intent",
            object_type="activity",
            polarity="positive",
            specificity="concrete",
            confidence=0.9,
            object_value=value,
            object_surface=value,
            temporal_cue="one_off",
            raw_time_frame={"raw": "秋天", "resolution": "unresolved_text"},
        ),
        evidence=[
            ClaimEvidenceInput(
                event_id=event_id,
                link_role="supporting",
                required_for_grounding=False,
                event_time=1_780_000_000.0,
                timestamp_confidence="approximate_recorded",
                timestamp_quality="approximate_recorded",
                timestamp_anchor_source="file_mtime",
                evidence_rule_version=2,
                evidence_mode="direct",
                source_type="history_import",
                source_domain="user_authored",
                author_type="user",
            )
        ],
        projection_leases=leases,
    )
    return str(stored["claim_id"])


async def _append_route_receipt(
    store,  # type: ignore[no-untyped-def]
    *,
    claim_id: str,
    leases: list[L2ProjectionLease],
) -> None:
    route = derive_semantic_route(
        SemanticRouteInput(
            claim_id=claim_id,
            subject_id="user:u1",
            subject_type="user",
            canonical_predicate="PLANS_TO",
            fact_kind="future_intent",
            object_type="activity",
            object_value="今年秋天去海边",
            object_entity_id=None,
            temporal_cue="one_off",
            specificity="concrete",
            target_from=None,
            target_to=None,
            raw_time_expression="秋天",
            time_resolution="unresolved_text",
            time_frame={"raw": "秋天", "resolution": "unresolved_text"},
        )
    )
    await store.append_claim_projection_outcome(
        ProjectionOutcomeInput(
            claim_id=claim_id,
            attempt_key=derive_projection_attempt_key(leases),
            target_kind="route",
            target_id=route.route_key or "predicate:PLANS_TO",
            target_slot_key=route.slot_key,
            route_contract_version=ROUTE_CONTRACT_VERSION,
            outcome=route.disposition.value,
            reason_code=route.reason_code,
            details={
                "semantic_route_id": route.semantic_route_id,
                "family": route.family,
                "trait_code": route.trait_code,
                "object_role": route.object_role.value,
                "value_fingerprint": route.value_fingerprint,
                "semantic_target_key": route.semantic_target_key,
                "object_surface": route.object_surface,
                "normalized_target_text": route.normalized_target_text,
                "target_entity_type": route.target_entity_type,
                "goal_lineage_key": route.goal_lineage_key,
                "target_window_key": route.target_window_key,
                "scope_key": route.scope_key,
            },
        ),
        projection_leases=leases,
    )


def _proposal(*claim_ids: str) -> PendingReviewProposal:
    return PendingReviewProposal(
        subject_id="user:u1",
        kind="goal_currentness",
        slot_key="goal-slot:seaside",
        value_fingerprint="goal-value:seaside",
        semantic_lineage_key="goal-lineage:seaside",
        claim_ids=tuple(claim_ids),
        reason_code="goal_ambiguous_time",
        proposed={
            "entity_id": "user:u1",
            "entity_type": "user",
            "trait_family": "goal_profile",
            "trait_name": "goal.intent",
            "trait_value": "今年秋天去海边",
            "confidence_score": 0.9,
            "evidence_events": [],
            "volatility_index": 0.2,
            "source_domain": "user_authored",
            "inference_depth": "explicit",
            "validation_state": "tentative",
            "first_inferred_at": 1_780_000_000.0,
            "last_validated_at": 1_780_000_000.0,
            "target_scope": "global",
            "temporal_scope": "persistent",
            "decay_policy": "evidence_only",
            "decay_anchor_at": 1_780_000_000.0,
            "semantic_route_slot_key": "goal-slot:seaside",
            "semantic_lineage_key": "goal-lineage:seaside",
            "target_window": {"raw": "秋天", "resolution": "unresolved_text"},
            "natural_summary": "用户想在秋天去海边，但年份尚不明确。",
        },
        route_contract_version=5,
        evidence_rule_version=2,
    )


async def _create_review(store, event_id: str = "event-review"):  # type: ignore[no-untyped-def]
    lease = await _running_lease(store, event_id)
    leases = [lease]
    claim_id = await _ground_claim(store, event_id=event_id, leases=leases)
    await _append_route_receipt(store, claim_id=claim_id, leases=leases)
    context = ClaimTargetOutcomeContext.for_claim(
        claim_id=claim_id,
        attempt_key=derive_projection_attempt_key([lease]),
        route_contract_version=5,
    )
    result = await store.upsert_pending_review_with_receipt(
        _proposal(claim_id),
        claim_outcome_context=context,
        projection_leases=leases,
    )
    return result, claim_id, lease


@pytest.mark.asyncio
async def test_identical_review_replay_is_a_timestamp_noop(l2_store_with_schema) -> None:
    first, claim_id, lease = await _create_review(l2_store_with_schema)
    before = (await l2_store_with_schema.list_pending_reviews())[0]
    second = await l2_store_with_schema.upsert_pending_review_with_receipt(
        _proposal(claim_id),
        claim_outcome_context=ClaimTargetOutcomeContext.for_claim(
            claim_id=claim_id,
            attempt_key=derive_projection_attempt_key([lease]),
            route_contract_version=5,
        ),
        projection_leases=[lease],
    )
    after = (await l2_store_with_schema.list_pending_reviews())[0]

    assert first.review_id == second.review_id
    assert second.created is False
    assert second.changed is False
    assert before["version"] == after["version"] == 1
    assert before["updated_at"] == after["updated_at"]


@pytest.mark.asyncio
async def test_review_write_and_claim_receipt_roll_back_together(
    l2_store_with_schema,
    monkeypatch,
) -> None:
    lease = await _running_lease(l2_store_with_schema, "event-review-rollback")
    claim_id = await _ground_claim(
        l2_store_with_schema,
        event_id="event-review-rollback",
        leases=[lease],
    )

    async def fail_receipt(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("receipt failed")

    monkeypatch.setattr(
        "magi.memory.l2.reviews.repository.append_claim_target_outcomes_on_connection",
        fail_receipt,
    )
    with pytest.raises(RuntimeError, match="receipt failed"):
        await l2_store_with_schema.upsert_pending_review_with_receipt(
            _proposal(claim_id),
            claim_outcome_context=ClaimTargetOutcomeContext.for_claim(
                claim_id=claim_id,
                attempt_key=derive_projection_attempt_key([lease]),
                route_contract_version=5,
            ),
            projection_leases=[lease],
        )

    assert await l2_store_with_schema.list_pending_reviews() == []


@pytest.mark.asyncio
async def test_confirm_review_atomically_creates_authoritative_assertion(
    l2_store_with_schema,
) -> None:
    review, claim_id, _lease = await _create_review(l2_store_with_schema)

    resolved = await l2_store_with_schema.resolve_pending_review(
        review_id=review.review_id,
        action="confirm",
        expected_version=1,
        resolved_by="user:u1",
        resolution_event_id="review-event-confirm",
        route_contract_version=5,
        evidence_rule_version=2,
    )

    assert resolved.status == "confirmed"
    assert resolved.version == 2
    assert resolved.assertion_id
    assert await l2_store_with_schema.list_pending_reviews() == []
    confirmed = await l2_store_with_schema.list_pending_reviews(status="confirmed")
    assert confirmed[0]["resolution_action"] == "confirm"
    assertions = await l2_store_with_schema.list_current_assertions(entity_id="user:u1")
    assertion = next(item for item in assertions if item["assertion_id"] == resolved.assertion_id)
    assert assertion["authority_ref"] == review.review_id
    assert assertion["source_domain"] == "user_feedback"
    outcomes = await l2_store_with_schema.list_claim_projection_outcomes(claim_id=claim_id)
    assert {item["target_kind"] for item in outcomes} == {"route", "review", "assertion"}


@pytest.mark.asyncio
async def test_review_resolution_uses_optimistic_concurrency(l2_store_with_schema) -> None:
    review, _claim_id, _lease = await _create_review(
        l2_store_with_schema,
        "event-review-concurrency",
    )

    results = await asyncio.gather(
        l2_store_with_schema.resolve_pending_review(
            review_id=review.review_id,
            action="confirm",
            expected_version=1,
            resolved_by="user:u1",
            resolution_event_id="review-event-win",
            route_contract_version=5,
            evidence_rule_version=2,
        ),
        l2_store_with_schema.resolve_pending_review(
            review_id=review.review_id,
            action="reject",
            expected_version=1,
            resolved_by="user:u1",
            resolution_event_id="review-event-lose",
            route_contract_version=5,
            evidence_rule_version=2,
        ),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, PendingReviewConflictError) for result in results) == 1


@pytest.mark.asyncio
async def test_confirm_with_edit_creates_a_user_owned_slot(l2_store_with_schema) -> None:
    review, claim_id, _lease = await _create_review(
        l2_store_with_schema,
        "event-review-edit",
    )

    resolved = await l2_store_with_schema.resolve_pending_review(
        review_id=review.review_id,
        action="confirm_with_edit",
        expected_version=1,
        resolved_by="user:u1",
        resolution_event_id="review-event-edit",
        edit={"trait_value": "明年春天去海边", "natural_summary": "用户确认明年春天去海边。"},
        route_contract_version=5,
        evidence_rule_version=2,
    )

    assertions = await l2_store_with_schema.list_current_assertions(entity_id="user:u1")
    assertion = next(item for item in assertions if item["assertion_id"] == resolved.assertion_id)
    assert assertion["trait_value"] == "明年春天去海边"
    assert assertion["slot_key"].startswith("review-edit-slot:")
    outcomes = await l2_store_with_schema.list_claim_projection_outcomes(claim_id=claim_id)
    assertion_receipt = next(item for item in outcomes if item["target_kind"] == "assertion")
    assert assertion_receipt["target_slot_key"] == assertion["slot_key"]


@pytest.mark.asyncio
async def test_source_forgetting_reconciles_then_closes_shared_review(
    l2_store_with_schema,
) -> None:
    event_ids = ["event-review-shared-a", "event-review-shared-b"]
    leases = await _running_leases(l2_store_with_schema, event_ids)
    claim_ids: list[str] = []
    for event_id in event_ids:
        claim_id = await _ground_claim(
            l2_store_with_schema,
            event_id=event_id,
            leases=leases,
        )
        await _append_route_receipt(
            l2_store_with_schema,
            claim_id=claim_id,
            leases=leases,
        )
        claim_ids.append(claim_id)

    review = await l2_store_with_schema.upsert_pending_review_with_receipt(
        _proposal(*claim_ids),
        claim_outcome_context=ClaimTargetOutcomeContext(
            claim_ids=tuple(claim_ids),
            attempt_key=derive_projection_attempt_key(leases),
            route_contract_version=ROUTE_CONTRACT_VERSION,
        ),
        projection_leases=leases,
    )

    first_result = await l2_store_with_schema.forget_source_events(
        [event_ids[0]],
        reason="test_forget_shared_review_support",
    )
    pending = await l2_store_with_schema.list_pending_reviews()
    assert first_result["l2_pending_reviews"] == 0
    assert len(pending) == 1
    assert pending[0]["review_id"] == review.review_id
    assert pending[0]["claim_ids"] == [claim_ids[1]]
    assert pending[0]["version"] == 2

    second_result = await l2_store_with_schema.forget_source_events(
        [event_ids[1]],
        reason="test_forget_last_review_support",
    )
    assert second_result["l2_pending_reviews"] == 1
    assert await l2_store_with_schema.list_pending_reviews() == []
    closed = await l2_store_with_schema.list_pending_reviews(status="closed")
    assert closed[0]["review_id"] == review.review_id
    assert closed[0]["close_reason"] == "source_event_forgotten"


@pytest.mark.asyncio
async def test_route_reprojection_closes_review_that_is_no_longer_authorized(
    l2_store_with_schema,
) -> None:
    review, claim_id, _lease = await _create_review(
        l2_store_with_schema,
        "event-review-route-change",
    )
    async with sqlite_connection_async(l2_store_with_schema.db_path) as db:
        await db.execute(
            """
            UPDATE l2_grounded_claims
            SET canonical_predicate = 'BIRTH_DATE', updated_at = updated_at + 1
            WHERE claim_id = ?
            """,
            (claim_id,),
        )
        await db.commit()

    result = await reproject_claim_route(
        l2_store_with_schema.db_path,
        claim_id=claim_id,
    )

    assert result.target_outcomes_invalidated == 1
    assert result.targets_archived == 1
    assert await l2_store_with_schema.list_pending_reviews() == []
    closed = await l2_store_with_schema.list_pending_reviews(status="closed")
    assert closed[0]["review_id"] == review.review_id
    assert closed[0]["close_reason"] == "route_contract_changed"
