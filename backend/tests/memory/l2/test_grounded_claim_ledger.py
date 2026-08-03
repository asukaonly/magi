"""Grounded Claim identity, provenance, replay, and privacy invariants."""

from __future__ import annotations

import asyncio
import re
import time

import aiosqlite
import pytest

from magi.memory.l2.claims.identity import derive_claim_identity_key
from magi.memory.l2.claims.models import (
    ClaimEvidenceInput,
    ClaimEntityRefInput,
    GroundedClaimInput,
    ProjectionOutcomeInput,
)
from magi.memory.l2.claims.outcomes import ClaimTargetOutcomeContext
from magi.memory.l2.models import L2ProjectionLease
from magi.memory.l2.projection.errors import ProjectionAttemptFencedError


async def _running_leases(
    store,  # type: ignore[no-untyped-def]
    event_ids: list[str],
    *,
    consumer_name: str = "claim-ledger-test",
) -> list[L2ProjectionLease]:
    for event_id in event_ids:
        await store.enqueue_projection_job(
            event_id=event_id,
            source="chat",
            event_type="UserMessage",
        )
    rows = await store.claim_projection_jobs(
        consumer_name=consumer_name,
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
    assert len(leases) == len(event_ids)
    assert await store.mark_projection_jobs_running(
        leases,
        consumer_name=consumer_name,
    ) == len(leases)
    return leases


def _claim_input(
    *,
    identity_key: str,
) -> GroundedClaimInput:
    return GroundedClaimInput(
        identity_key=identity_key,
        extractor_contract_version=1,
        evidence_rule_version=1,
        origin_attempt_key="attempt:test:1",
        profile_id="chat.user_message",
        user_id=None,
        subject_ref="user:self",
        subject_type="user",
        canonical_predicate="LIKES",
        fact_kind="explicit_fact",
        object_type="topic",
        polarity="positive",
        specificity="concrete",
        confidence=0.92,
        object_value="jazz",
        object_surface="jazz",
        temporal_cue="stable",
    )


def _evidence(
    event_id: str,
    *,
    link_role: str = "supporting",
    required_for_grounding: bool = False,
    evidence_mode: str = "direct",
) -> ClaimEvidenceInput:
    return ClaimEvidenceInput(
        event_id=event_id,
        link_role=link_role,
        required_for_grounding=required_for_grounding,
        event_time=1_720_000_000.0,
        timestamp_confidence="exact",
        timestamp_quality="exact",
        evidence_rule_version=1,
        evidence_mode=evidence_mode,
        source_type="conversation" if link_role == "supporting" else None,
        source_domain="user_authored" if link_role == "supporting" else None,
        author_type="user" if link_role == "supporting" else "assistant",
        evidence_class="user_self_report" if link_role == "supporting" else None,
        evidence_locator={"start": 2, "end": 6, "quote_hash": "opaque"},
    )


def _identity(
    *,
    supporting_event_ids: list[str],
    antecedent_event_ids: list[str] | None = None,
    evidence_mode: str = "direct",
) -> str:
    return derive_claim_identity_key(
        extractor_contract_version=1,
        evidence_rule_version=1,
        user_id=None,
        subject_ref="user:self",
        subject_type="user",
        canonical_predicate="LIKES",
        fact_kind="explicit_fact",
        object_type="topic",
        polarity="positive",
        specificity="concrete",
        temporal_cue="stable",
        fact_valid_from=None,
        fact_valid_to=None,
        target_from=None,
        target_to=None,
        raw_time_frame=None,
        evidence_mode=evidence_mode,
        object_surface="jazz",
        object_value="jazz",
        supporting_event_ids=supporting_event_ids,
        antecedent_event_ids=antecedent_event_ids or [],
    )


def test_claim_identity_is_order_insensitive_but_role_sensitive() -> None:
    direct = _identity(supporting_event_ids=["evt-b", "evt-a"])
    reordered = _identity(supporting_event_ids=["evt-a", "evt-b"])
    contextual = _identity(
        supporting_event_ids=["evt-a", "evt-b"],
        antecedent_event_ids=["evt-context"],
        evidence_mode="confirmation",
    )

    assert direct == reordered
    assert contextual != direct


@pytest.mark.asyncio
async def test_grounded_claim_replay_is_idempotent(l2_store_with_schema) -> None:
    identity_key = _identity(supporting_event_ids=["evt-1"])
    leases = await _running_leases(l2_store_with_schema, ["evt-1"])
    first = await l2_store_with_schema.upsert_grounded_claim(
        claim=_claim_input(identity_key=identity_key),
        evidence=[_evidence("evt-1")],
        projection_leases=leases,
    )
    second = await l2_store_with_schema.upsert_grounded_claim(
        claim=_claim_input(identity_key=identity_key),
        evidence=[_evidence("evt-1")],
        projection_leases=leases,
    )

    assert first["created"] is True
    assert second["created"] is False
    assert first["claim_id"] == second["claim_id"]
    assert re.fullmatch(r"clm_[0-9a-f]{32}", first["claim_id"])
    assert first["inserted_evidence_count"] == 1
    assert second["inserted_evidence_count"] == 0
    assert len(second["evidence"]) == 1


@pytest.mark.asyncio
async def test_concurrent_grounded_claim_upsert_has_one_identity(l2_store_with_schema) -> None:
    identity_key = _identity(supporting_event_ids=["evt-concurrent"])
    leases = await _running_leases(l2_store_with_schema, ["evt-concurrent"])

    async def write_once() -> dict:
        return await l2_store_with_schema.upsert_grounded_claim(
            claim=_claim_input(identity_key=identity_key),
            evidence=[_evidence("evt-concurrent")],
            projection_leases=leases,
        )

    first, second = await asyncio.gather(write_once(), write_once())
    rows = await l2_store_with_schema.list_grounded_claims()

    assert first["claim_id"] == second["claim_id"]
    assert sum(int(row["created"]) for row in (first, second)) == 1
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_grounded_claim_rejects_support_outside_projection_lease_batch(
    l2_store_with_schema,
) -> None:
    leases = await _running_leases(l2_store_with_schema, ["evt-leased"])

    with pytest.raises(ValueError, match="subset of projection lease event IDs"):
        await l2_store_with_schema.upsert_grounded_claim(
            claim=_claim_input(identity_key=_identity(supporting_event_ids=["evt-not-leased"])),
            evidence=[_evidence("evt-not-leased")],
            projection_leases=leases,
        )

    assert await l2_store_with_schema.list_grounded_claims() == []


@pytest.mark.parametrize("mismatch", ["lease_token", "attempt_count"])
@pytest.mark.asyncio
async def test_claim_writes_require_the_exact_projection_lease(
    l2_store_with_schema,
    mismatch: str,
) -> None:
    exact_leases = await _running_leases(l2_store_with_schema, ["evt-exact"])
    exact = exact_leases[0]
    invalid = L2ProjectionLease(
        event_id=exact.event_id,
        lease_token=("wrong-token" if mismatch == "lease_token" else exact.lease_token),
        attempt_count=(
            exact.attempt_count + 1 if mismatch == "attempt_count" else exact.attempt_count
        ),
    )
    identity_key = _identity(supporting_event_ids=["evt-exact"])

    with pytest.raises(ProjectionAttemptFencedError):
        await l2_store_with_schema.upsert_grounded_claim(
            claim=_claim_input(identity_key=identity_key),
            evidence=[_evidence("evt-exact")],
            projection_leases=[invalid],
        )
    assert await l2_store_with_schema.list_grounded_claims() == []

    stored = await l2_store_with_schema.upsert_grounded_claim(
        claim=_claim_input(identity_key=identity_key),
        evidence=[_evidence("evt-exact")],
        projection_leases=exact_leases,
    )
    with pytest.raises(ProjectionAttemptFencedError):
        await l2_store_with_schema.upsert_claim_entity_ref(
            ClaimEntityRefInput(
                claim_id=stored["claim_id"],
                ref_role="object",
                entity_id="topic:jazz",
                resolution_version=1,
            ),
            projection_leases=[invalid],
        )
    with pytest.raises(ProjectionAttemptFencedError):
        await l2_store_with_schema.append_claim_projection_outcome(
            ProjectionOutcomeInput(
                claim_id=stored["claim_id"],
                attempt_key="attempt:invalid",
                target_kind="route",
                outcome="unrouted",
            ),
            projection_leases=[invalid],
        )

    assert await l2_store_with_schema.list_claim_entity_refs(claim_id=stored["claim_id"]) == []
    assert (
        await l2_store_with_schema.list_claim_projection_outcomes(claim_id=stored["claim_id"]) == []
    )

    assert await l2_store_with_schema.upsert_claim_entity_ref(
        ClaimEntityRefInput(
            claim_id=stored["claim_id"],
            ref_role="object",
            entity_id="topic:jazz",
            resolution_version=1,
        ),
        projection_leases=exact_leases,
    )
    exact_outcome = await l2_store_with_schema.append_claim_projection_outcome(
        ProjectionOutcomeInput(
            claim_id=stored["claim_id"],
            attempt_key="attempt:exact",
            target_kind="route",
            outcome="unrouted",
        ),
        projection_leases=exact_leases,
    )
    assert exact_outcome is not None


@pytest.mark.asyncio
async def test_claim_entity_ref_rejects_same_version_entity_drift(
    l2_store_with_schema,
) -> None:
    leases = await _running_leases(l2_store_with_schema, ["evt-ref-version"])
    stored_claim = await l2_store_with_schema.upsert_grounded_claim(
        claim=_claim_input(identity_key=_identity(supporting_event_ids=["evt-ref-version"])),
        evidence=[_evidence("evt-ref-version")],
        projection_leases=leases,
    )
    first = await l2_store_with_schema.upsert_claim_entity_ref(
        ClaimEntityRefInput(
            claim_id=stored_claim["claim_id"],
            ref_role="object",
            entity_id="topic:jazz",
            resolution_version=1,
        ),
        projection_leases=leases,
    )
    replay = await l2_store_with_schema.upsert_claim_entity_ref(
        ClaimEntityRefInput(
            claim_id=stored_claim["claim_id"],
            ref_role="object",
            entity_id="topic:jazz",
            resolution_version=1,
        ),
        projection_leases=leases,
    )

    assert first is not None and replay is not None
    assert first["entity_id"] == replay["entity_id"] == "topic:jazz"
    with pytest.raises(RuntimeError, match="conflicting entity IDs"):
        await l2_store_with_schema.upsert_claim_entity_ref(
            ClaimEntityRefInput(
                claim_id=stored_claim["claim_id"],
                ref_role="object",
                entity_id="topic:blues",
                resolution_version=1,
            ),
            projection_leases=leases,
        )

    refs = await l2_store_with_schema.list_claim_entity_refs(claim_id=stored_claim["claim_id"])
    assert [(item["resolution_version"], item["entity_id"]) for item in refs] == [(1, "topic:jazz")]


@pytest.mark.asyncio
async def test_projection_outcome_is_idempotent_per_attempt_target(l2_store_with_schema) -> None:
    leases = await _running_leases(l2_store_with_schema, ["evt-2"])
    stored = await l2_store_with_schema.upsert_grounded_claim(
        claim=_claim_input(identity_key=_identity(supporting_event_ids=["evt-2"])),
        evidence=[_evidence("evt-2")],
        projection_leases=leases,
    )
    outcome = ProjectionOutcomeInput(
        claim_id=stored["claim_id"],
        attempt_key="attempt:test:1",
        target_kind="route",
        target_id="",
        target_slot_key="route:preference:music",
        route_contract_version=1,
        outcome="projected",
        details={"family": "preference_profile"},
    )

    first = await l2_store_with_schema.append_claim_projection_outcome(
        outcome,
        projection_leases=leases,
    )
    second = await l2_store_with_schema.append_claim_projection_outcome(
        outcome,
        projection_leases=leases,
    )
    rows = await l2_store_with_schema.list_claim_projection_outcomes(claim_id=stored["claim_id"])

    assert first is not None and second is not None
    assert first["outcome_id"] == second["outcome_id"]
    assert len(rows) == 1

    with pytest.raises(RuntimeError, match="claim_projection_outcome_conflict"):
        await l2_store_with_schema.append_claim_projection_outcome(
            ProjectionOutcomeInput(
                claim_id=stored["claim_id"],
                attempt_key="attempt:test:1",
                target_kind="route",
                target_id="",
                target_slot_key="route:preference:music",
                route_contract_version=1,
                outcome="rejected",
                reason_code="conflicting_replay",
            ),
            projection_leases=leases,
        )

    rows = await l2_store_with_schema.list_claim_projection_outcomes(
        claim_id=stored["claim_id"]
    )
    assert len(rows) == 1
    assert rows[0]["outcome"] == "projected"


@pytest.mark.asyncio
async def test_forget_redacts_claim_and_invalidates_outcome(l2_store_with_schema) -> None:
    identity_key = _identity(supporting_event_ids=["evt-secret"])
    leases = await _running_leases(l2_store_with_schema, ["evt-secret"])
    stored = await l2_store_with_schema.upsert_grounded_claim(
        claim=_claim_input(identity_key=identity_key),
        evidence=[_evidence("evt-secret")],
        projection_leases=leases,
    )
    await l2_store_with_schema.append_claim_projection_outcome(
        ProjectionOutcomeInput(
            claim_id=stored["claim_id"],
            attempt_key="attempt:test:1",
            target_kind="assertion",
            target_id="assertion-secret",
            target_slot_key="slot-secret",
            route_contract_version=1,
            outcome="projected",
            details={"summary": "private text"},
        ),
        projection_leases=leases,
    )

    result = await l2_store_with_schema.forget_source_events(
        ["evt-secret"],
        reason="user_request",
    )
    forgotten = await l2_store_with_schema.get_grounded_claim(
        stored["claim_id"],
        include_forgotten=True,
    )
    outcomes = await l2_store_with_schema.list_claim_projection_outcomes(
        claim_id=stored["claim_id"]
    )

    assert result["l2_grounded_claims"] == 1
    assert forgotten is not None
    assert forgotten["availability"] == "forgotten"
    assert forgotten["object_surface"] is None
    assert forgotten["canonical_predicate"] is None
    assert forgotten["subject_ref"] is None
    assert forgotten["evidence"] == []
    assert outcomes[0]["invalidated_reason"] == "source_event_forgotten"
    assert outcomes[0]["details_json"] is None
    assert outcomes[0]["target_id"].startswith("redacted:")
    assert await l2_store_with_schema.get_grounded_claim(stored["claim_id"]) is None

    replay = await l2_store_with_schema.upsert_grounded_claim(
        claim=_claim_input(identity_key=identity_key),
        evidence=[_evidence("evt-secret")],
        projection_leases=leases,
    )
    assert replay["replay_blocked"] is True
    assert replay["claim_id"] is None


@pytest.mark.asyncio
async def test_tombstone_immediately_hides_claim_before_cleanup_resumes(
    l2_store_with_schema,
) -> None:
    leases = await _running_leases(l2_store_with_schema, ["evt-tombstone-crash"])
    stored = await l2_store_with_schema.upsert_grounded_claim(
        claim=_claim_input(identity_key=_identity(supporting_event_ids=["evt-tombstone-crash"])),
        evidence=[_evidence("evt-tombstone-crash")],
        projection_leases=leases,
    )

    await l2_store_with_schema.tombstone_source_events(
        ["evt-tombstone-crash"],
        reason="durable_forget_admission",
    )

    assert await l2_store_with_schema.get_grounded_claim(stored["claim_id"]) is None
    forgotten = await l2_store_with_schema.get_grounded_claim(
        stored["claim_id"],
        include_forgotten=True,
    )
    assert forgotten is not None
    assert forgotten["availability"] == "forgotten"
    assert forgotten["object_surface"] is None
    assert forgotten["evidence"] == []


@pytest.mark.asyncio
async def test_forgetting_required_antecedent_redacts_contextual_claim(
    l2_store_with_schema,
) -> None:
    identity_key = _identity(
        supporting_event_ids=["evt-reply"],
        antecedent_event_ids=["evt-question"],
        evidence_mode="confirmation",
    )
    leases = await _running_leases(l2_store_with_schema, ["evt-reply"])
    stored = await l2_store_with_schema.upsert_grounded_claim(
        claim=_claim_input(identity_key=identity_key),
        evidence=[
            _evidence("evt-reply", evidence_mode="confirmation"),
            _evidence(
                "evt-question",
                link_role="antecedent",
                required_for_grounding=True,
                evidence_mode="confirmation",
            ),
        ],
        projection_leases=leases,
    )

    await l2_store_with_schema.forget_source_events(
        ["evt-question"],
        reason="user_request",
    )
    forgotten = await l2_store_with_schema.get_grounded_claim(
        stored["claim_id"],
        include_forgotten=True,
    )

    assert forgotten is not None
    assert forgotten["availability"] == "forgotten"
    assert forgotten["evidence"] == []


@pytest.mark.asyncio
async def test_full_clear_removes_claim_children_before_claims(l2_store_with_schema) -> None:
    leases = await _running_leases(l2_store_with_schema, ["evt-clear"])
    stored = await l2_store_with_schema.upsert_grounded_claim(
        claim=_claim_input(identity_key=_identity(supporting_event_ids=["evt-clear"])),
        evidence=[_evidence("evt-clear")],
        projection_leases=leases,
    )
    await l2_store_with_schema.append_claim_projection_outcome(
        ProjectionOutcomeInput(
            claim_id=stored["claim_id"],
            attempt_key="attempt:clear:1",
            target_kind="route",
            outcome="unrouted",
            reason_code="unsupported_route",
        ),
        projection_leases=leases,
    )

    await l2_store_with_schema.clear()

    assert await l2_store_with_schema.list_grounded_claims() == []
    assert (
        await l2_store_with_schema.list_claim_projection_outcomes(claim_id=stored["claim_id"]) == []
    )


@pytest.mark.asyncio
async def test_forgetting_any_identity_evidence_redacts_the_whole_claim(
    l2_store_with_schema,
) -> None:
    leases = await _running_leases(l2_store_with_schema, ["evt-a", "evt-b"])
    identity_key = _identity(supporting_event_ids=["evt-a", "evt-b"])
    stored = await l2_store_with_schema.upsert_grounded_claim(
        claim=_claim_input(identity_key=identity_key),
        evidence=[_evidence("evt-a"), _evidence("evt-b")],
        projection_leases=leases,
    )

    await l2_store_with_schema.forget_source_events(["evt-a"], reason="user_request")
    forgotten = await l2_store_with_schema.get_grounded_claim(
        stored["claim_id"],
        include_forgotten=True,
    )

    assert forgotten is not None
    assert forgotten["availability"] == "forgotten"
    assert forgotten["evidence"] == []


@pytest.mark.asyncio
async def test_stale_attempt_cannot_append_claim_children(l2_store_with_schema) -> None:
    first = await _running_leases(l2_store_with_schema, ["evt-fenced"])
    stored = await l2_store_with_schema.upsert_grounded_claim(
        claim=_claim_input(identity_key=_identity(supporting_event_ids=["evt-fenced"])),
        evidence=[_evidence("evt-fenced")],
        projection_leases=first,
    )
    async with aiosqlite.connect(l2_store_with_schema.db_path) as db:
        await db.execute(
            """
            UPDATE l2_projection_jobs
            SET lease_heartbeat_at = ?, updated_at = ?
            WHERE event_id = 'evt-fenced'
            """,
            (time.time() - 60, time.time() - 60),
        )
        await db.commit()
    assert (
        await l2_store_with_schema.requeue_stale_projection_jobs(
            queued_timeout_seconds=30,
            running_timeout_seconds=30,
        )
        == 1
    )

    with pytest.raises(ProjectionAttemptFencedError):
        await l2_store_with_schema.append_claim_projection_outcome(
            ProjectionOutcomeInput(
                claim_id=stored["claim_id"],
                attempt_key="attempt:stale",
                target_kind="route",
                outcome="unrouted",
            ),
            projection_leases=first,
        )


@pytest.mark.asyncio
async def test_stale_attempt_cannot_write_projection_targets(l2_store_with_schema) -> None:
    leases = await _running_leases(l2_store_with_schema, ["evt-target-fenced"])
    async with aiosqlite.connect(l2_store_with_schema.db_path) as db:
        await db.execute(
            """
            UPDATE l2_projection_jobs
            SET lease_heartbeat_at = ?, updated_at = ?
            WHERE event_id = 'evt-target-fenced'
            """,
            (time.time() - 60, time.time() - 60),
        )
        await db.commit()
    assert (
        await l2_store_with_schema.requeue_stale_projection_jobs(
            queued_timeout_seconds=30,
            running_timeout_seconds=30,
        )
        == 1
    )

    with pytest.raises(ProjectionAttemptFencedError):
        await l2_store_with_schema.upsert_knowledge_edge_with_receipt(
            {
                "subject_id": "user:u1",
                "subject_type": "user",
                "predicate": "LIKES",
                "object_id": "topic:jazz",
                "object_type": "topic",
                "fact_kind": "explicit_fact",
                "evidence_event_ids": ["evt-target-fenced"],
                "confidence": 0.9,
                "observed_at": time.time(),
                "source_type": "chat",
            },
            claim_outcome_context=ClaimTargetOutcomeContext.for_claim(
                claim_id="clm_stale",
                attempt_key="attempt:stale",
                route_contract_version=1,
            ),
            projection_leases=leases,
        )
    with pytest.raises(ProjectionAttemptFencedError):
        await l2_store_with_schema.upsert_assertion_candidate_with_receipt(
            {
                "entity_id": "user:u1",
                "entity_type": "user",
                "trait_family": "preference_profile",
                "trait_name": "preference.affinity",
                "trait_value": "like",
                "confidence_score": 0.9,
                "evidence_events": ["evt-target-fenced"],
                "volatility_index": 0.2,
                "source_domain": "user_authored",
                "inference_depth": "semantic",
                "validation_state": "tentative",
                "first_inferred_at": time.time(),
                "last_validated_at": time.time(),
                "temporal_scope": "persistent",
                "decay_policy": "evidence_only",
            },
            claim_outcome_context=ClaimTargetOutcomeContext.for_claim(
                claim_id="clm_stale",
                attempt_key="attempt:stale",
                route_contract_version=1,
            ),
            projection_leases=leases,
        )
    with pytest.raises(ProjectionAttemptFencedError):
        await l2_store_with_schema.upsert_entity_facet(
            entity_id="topic:jazz",
            entity_type="topic",
            facet_name="category",
            facet_value="music",
            evidence_event_ids=["evt-target-fenced"],
            confidence=0.9,
            observed_at=time.time(),
            source_type="chat",
            projection_leases=leases,
        )

    existing_triple_id = await l2_store_with_schema.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="LIKES",
        object_id="topic:existing",
        object_type="topic",
        evidence_event_ids=["evt-existing"],
        confidence=0.9,
        observed_at=time.time(),
        source_type="chat",
    )
    with pytest.raises(ProjectionAttemptFencedError):
        await l2_store_with_schema.apply_contradiction_hint(
            {
                "target_record_type": "knowledge_graph",
                "target_record_id": existing_triple_id,
                "recommended_action": "mark_deprecated",
                "confidence": 0.9,
            },
            projection_leases=leases,
        )

    relationships = await l2_store_with_schema.get_relationships(subject_id="user:u1")
    assert [(item["triple_id"], item["status"]) for item in relationships] == [
        (existing_triple_id, "active")
    ]
    assert await l2_store_with_schema.list_current_assertions(entity_id="user:u1") == []
    assert await l2_store_with_schema.list_entity_facets(entity_id="topic:jazz") == []
