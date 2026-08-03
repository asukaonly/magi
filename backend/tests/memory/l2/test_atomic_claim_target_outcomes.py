"""Atomicity invariants for L2 Claim target projection receipts."""

from __future__ import annotations

import aiosqlite
import pytest

from magi.memory.l2.claims.identity import derive_claim_identity_key
from magi.memory.l2.claims.models import (
    ClaimEvidenceInput,
    GroundedClaimInput,
)
from magi.memory.l2.claims.outcomes import ClaimTargetOutcomeContext
from magi.memory.l2.corrections.policy import (
    CorrectionPolicyAction,
    CorrectionPolicyDecision,
)
from magi.memory.l2.models import L2ProjectionLease


async def _running_leases(store, event_ids: list[str]) -> list[L2ProjectionLease]:  # type: ignore[no-untyped-def]
    for event_id in event_ids:
        await store.enqueue_projection_job(
            event_id=event_id,
            source="chat",
            event_type="UserMessage",
        )
    rows = await store.claim_projection_jobs(
        consumer_name="atomic-target-outcome-test",
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
        consumer_name="atomic-target-outcome-test",
    ) == len(event_ids)
    return leases


async def _ground_claim(
    store,  # type: ignore[no-untyped-def]
    *,
    event_id: str,
    object_value: str,
    leases: list[L2ProjectionLease],
) -> str:
    identity_key = derive_claim_identity_key(
        extractor_contract_version=1,
        evidence_rule_version=1,
        user_id=None,
        subject_ref="user:u1",
        subject_type="user",
        canonical_predicate="LIKES",
        fact_kind="explicit_fact",
        object_type="topic",
        polarity="positive",
        specificity="concrete",
        temporal_cue="stable",
        evidence_mode="direct",
        object_surface=object_value,
        object_value=object_value,
        supporting_event_ids=[event_id],
        antecedent_event_ids=[],
    )
    stored = await store.upsert_grounded_claim(
        claim=GroundedClaimInput(
            identity_key=identity_key,
            extractor_contract_version=1,
            evidence_rule_version=1,
            origin_attempt_key="attempt:atomic:1",
            profile_id="chat.user_message",
            user_id=None,
            subject_ref="user:u1",
            subject_type="user",
            canonical_predicate="LIKES",
            fact_kind="explicit_fact",
            object_type="topic",
            polarity="positive",
            specificity="concrete",
            confidence=0.9,
            object_value=object_value,
            object_surface=object_value,
            temporal_cue="stable",
        ),
        evidence=[
            ClaimEvidenceInput(
                event_id=event_id,
                link_role="supporting",
                required_for_grounding=False,
                event_time=1_720_000_000.0,
                timestamp_confidence="exact",
                timestamp_quality="exact",
                evidence_rule_version=1,
                evidence_mode="direct",
                source_type="conversation",
                source_domain="user_authored",
                author_type="user",
            )
        ],
        projection_leases=leases,
    )
    return str(stored["claim_id"])


def _graph_candidate(event_id: str) -> dict:
    return {
        "subject_id": "user:u1",
        "subject_type": "user",
        "predicate": "LIKES",
        "object_id": "topic:jazz",
        "object_type": "topic",
        "fact_kind": "explicit_fact",
        "evidence_event_ids": [event_id],
        "confidence": 0.9,
        "observed_at": 1_720_000_000.0,
        "source_type": "chat",
    }


def _assertion_candidate(event_ids: list[str], claim_ids: list[str]) -> dict:
    return {
        "entity_id": "user:u1",
        "entity_type": "user",
        "trait_family": "preference_profile",
        "trait_name": "preference.affinity",
        "trait_value": "jazz",
        "confidence_score": 0.9,
        "evidence_events": event_ids,
        "volatility_index": 0.2,
        "source_domain": "user_authored",
        "inference_depth": "semantic",
        "validation_state": "tentative",
        "first_inferred_at": 1_720_000_000.0,
        "last_validated_at": 1_720_000_000.0,
        "temporal_scope": "persistent",
        "decay_policy": "evidence_only",
        "semantic_route_slot_key": "preference:music:jazz",
        "supporting_claim_ids": claim_ids,
    }


@pytest.mark.asyncio
async def test_graph_target_and_claim_outcome_commit_together(
    l2_store_with_schema,
) -> None:
    leases = await _running_leases(l2_store_with_schema, ["evt-graph-atomic"])
    claim_id = await _ground_claim(
        l2_store_with_schema,
        event_id="evt-graph-atomic",
        object_value="jazz",
        leases=leases,
    )
    context = ClaimTargetOutcomeContext.for_claim(
        claim_id=claim_id,
        attempt_key="attempt:graph:1",
        route_contract_version=7,
    )

    first = await l2_store_with_schema.upsert_knowledge_edge_with_receipt(
        _graph_candidate("evt-graph-atomic"),
        claim_outcome_context=context,
        projection_leases=leases,
    )
    second = await l2_store_with_schema.upsert_knowledge_edge_with_receipt(
        _graph_candidate("evt-graph-atomic"),
        claim_outcome_context=context,
        projection_leases=leases,
    )

    relationships = await l2_store_with_schema.get_relationships(subject_id="user:u1")
    outcomes = await l2_store_with_schema.list_claim_projection_outcomes(claim_id=claim_id)
    assert first["triple_id"] == second["triple_id"]
    assert len(relationships) == 1
    assert relationships[0]["observation_count"] == 1
    assert len(outcomes) == 1
    assert outcomes[0]["target_id"] == first["triple_id"]
    assert outcomes[0]["outcome"] == "projected"
    assert outcomes[0]["attempt_key"] == "attempt:graph:1"
    assert outcomes[0]["route_contract_version"] == 7


@pytest.mark.asyncio
async def test_graph_outcome_failure_rolls_back_target(
    l2_store_with_schema,
    monkeypatch,
) -> None:
    leases = await _running_leases(l2_store_with_schema, ["evt-graph-rollback"])
    claim_id = await _ground_claim(
        l2_store_with_schema,
        event_id="evt-graph-rollback",
        object_value="jazz",
        leases=leases,
    )

    async def fail_outcome(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("injected outcome failure")

    monkeypatch.setattr(
        "magi.memory.l2.graph.writes.append_claim_target_outcomes_on_connection",
        fail_outcome,
    )
    with pytest.raises(RuntimeError, match="injected outcome failure"):
        await l2_store_with_schema.upsert_knowledge_edge_with_receipt(
            _graph_candidate("evt-graph-rollback"),
            claim_outcome_context=ClaimTargetOutcomeContext.for_claim(
                claim_id=claim_id,
                attempt_key="attempt:graph:rollback",
                route_contract_version=1,
            ),
            projection_leases=leases,
        )

    assert await l2_store_with_schema.get_relationships(subject_id="user:u1") == []
    assert await l2_store_with_schema.list_claim_projection_outcomes(claim_id=claim_id) == []


@pytest.mark.asyncio
async def test_multi_claim_assertion_and_outcomes_replay_idempotently(
    l2_store_with_schema,
) -> None:
    event_ids = ["evt-assertion-a", "evt-assertion-b"]
    leases = await _running_leases(l2_store_with_schema, event_ids)
    claim_ids = [
        await _ground_claim(
            l2_store_with_schema,
            event_id=event_id,
            object_value=f"jazz-{index}",
            leases=leases,
        )
        for index, event_id in enumerate(event_ids)
    ]
    context = ClaimTargetOutcomeContext(
        claim_ids=tuple(claim_ids),
        attempt_key="attempt:assertion:1",
        route_contract_version=9,
    )
    candidate = _assertion_candidate(event_ids, claim_ids)

    first = await l2_store_with_schema.upsert_assertion_candidate_with_receipt(
        candidate,
        claim_outcome_context=context,
        projection_leases=leases,
    )
    second = await l2_store_with_schema.upsert_assertion_candidate_with_receipt(
        candidate,
        claim_outcome_context=context,
        projection_leases=leases,
    )

    assertions = await l2_store_with_schema.list_current_assertions(entity_id="user:u1")
    assert first["assertion_id"] == second["assertion_id"]
    assert len(assertions) == 1
    for claim_id in claim_ids:
        outcomes = await l2_store_with_schema.list_claim_projection_outcomes(claim_id=claim_id)
        assert len(outcomes) == 1
        assert outcomes[0]["target_id"] == first["assertion_id"]
        assert outcomes[0]["outcome"] == "projected"
        assert outcomes[0]["attempt_key"] == "attempt:assertion:1"
        assert outcomes[0]["route_contract_version"] == 9


@pytest.mark.asyncio
async def test_assertion_outcome_failure_rolls_back_target(
    l2_store_with_schema,
    monkeypatch,
) -> None:
    leases = await _running_leases(l2_store_with_schema, ["evt-assertion-rollback"])
    claim_id = await _ground_claim(
        l2_store_with_schema,
        event_id="evt-assertion-rollback",
        object_value="jazz",
        leases=leases,
    )

    async def fail_outcome(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("injected outcome failure")

    monkeypatch.setattr(
        "magi.memory.l2.assertions.write.append_claim_target_outcomes_on_connection",
        fail_outcome,
    )
    with pytest.raises(RuntimeError, match="injected outcome failure"):
        await l2_store_with_schema.upsert_assertion_candidate_with_receipt(
            _assertion_candidate(["evt-assertion-rollback"], [claim_id]),
            claim_outcome_context=ClaimTargetOutcomeContext.for_claim(
                claim_id=claim_id,
                attempt_key="attempt:assertion:rollback",
                route_contract_version=1,
            ),
            projection_leases=leases,
        )

    assert await l2_store_with_schema.list_current_assertions(entity_id="user:u1") == []
    assert await l2_store_with_schema.list_claim_projection_outcomes(claim_id=claim_id) == []


@pytest.mark.asyncio
async def test_atomic_writer_rejects_missing_claim_and_rolls_back_target(
    l2_store_with_schema,
) -> None:
    leases = await _running_leases(l2_store_with_schema, ["evt-missing-claim"])

    with pytest.raises(RuntimeError, match="active grounded Claim"):
        await l2_store_with_schema.upsert_knowledge_edge_with_receipt(
            _graph_candidate("evt-missing-claim"),
            claim_outcome_context=ClaimTargetOutcomeContext.for_claim(
                claim_id="clm_missing",
                attempt_key="attempt:missing-claim",
                route_contract_version=1,
            ),
            projection_leases=leases,
        )

    async with aiosqlite.connect(l2_store_with_schema.db_path) as db:
        async with db.execute("SELECT COUNT(*) FROM knowledge_graph") as cursor:
            assert int((await cursor.fetchone())[0]) == 0
        async with db.execute("SELECT COUNT(*) FROM l2_claim_projection_outcomes") as cursor:
            assert int((await cursor.fetchone())[0]) == 0


@pytest.mark.asyncio
async def test_multi_claim_assertion_rolls_back_when_one_claim_is_missing(
    l2_store_with_schema,
) -> None:
    event_id = "evt-assertion-missing-claim"
    leases = await _running_leases(l2_store_with_schema, [event_id])
    claim_id = await _ground_claim(
        l2_store_with_schema,
        event_id=event_id,
        object_value="jazz",
        leases=leases,
    )

    with pytest.raises(RuntimeError, match="active grounded Claim"):
        await l2_store_with_schema.upsert_assertion_candidate_with_receipt(
            _assertion_candidate([event_id], [claim_id, "clm_missing"]),
            claim_outcome_context=ClaimTargetOutcomeContext(
                claim_ids=(claim_id, "clm_missing"),
                attempt_key="attempt:assertion:missing-claim",
                route_contract_version=1,
            ),
            projection_leases=leases,
        )

    assert await l2_store_with_schema.list_current_assertions(entity_id="user:u1") == []
    assert await l2_store_with_schema.list_claim_projection_outcomes(claim_id=claim_id) == []


@pytest.mark.asyncio
async def test_graph_governance_noop_commits_skipped_outcome_with_target(
    l2_store_with_schema,
    monkeypatch,
) -> None:
    leases = await _running_leases(l2_store_with_schema, ["evt-graph-governed"])
    claim_id = await _ground_claim(
        l2_store_with_schema,
        event_id="evt-graph-governed",
        object_value="jazz",
        leases=leases,
    )

    class GovernedPolicy:
        async def evaluate_relationship(self, db, candidate):  # type: ignore[no-untyped-def]
            return CorrectionPolicyDecision(
                CorrectionPolicyAction.REQUIRES_SCOPE,
                correction_id="corr-governed",
                target_id="edge-governed-target",
            )

    async def record_evidence_noop(*args, **kwargs):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(
        "magi.memory.l2.graph.writes.CorrectionPolicyEvaluator",
        GovernedPolicy,
    )
    monkeypatch.setattr(
        "magi.memory.l2.graph.writes.MemoryCorrectionRepository.append_evidence_event_ids",
        record_evidence_noop,
    )
    receipt = await l2_store_with_schema.upsert_knowledge_edge_with_receipt(
        _graph_candidate("evt-graph-governed"),
        claim_outcome_context=ClaimTargetOutcomeContext.for_claim(
            claim_id=claim_id,
            attempt_key="attempt:graph:governed",
            route_contract_version=1,
        ),
        projection_leases=leases,
    )

    outcomes = await l2_store_with_schema.list_claim_projection_outcomes(claim_id=claim_id)
    assert receipt["persisted"] is False
    assert receipt["triple_id"] == "edge-governed-target"
    assert await l2_store_with_schema.get_relationships(subject_id="user:u1") == []
    assert [(item["target_id"], item["outcome"], item["reason_code"]) for item in outcomes] == [
        ("edge-governed-target", "skipped", "requires_scope")
    ]


@pytest.mark.asyncio
async def test_assertion_governance_noop_commits_skipped_outcomes_with_target(
    l2_store_with_schema,
    monkeypatch,
) -> None:
    event_ids = ["evt-assertion-governed-a", "evt-assertion-governed-b"]
    leases = await _running_leases(l2_store_with_schema, event_ids)
    claim_ids = [
        await _ground_claim(
            l2_store_with_schema,
            event_id=event_id,
            object_value=f"jazz-{index}",
            leases=leases,
        )
        for index, event_id in enumerate(event_ids)
    ]

    class GovernedPolicy:
        async def evaluate_assertion(self, db, candidate):  # type: ignore[no-untyped-def]
            return CorrectionPolicyDecision(
                CorrectionPolicyAction.REQUIRES_SCOPE,
                correction_id="corr-governed",
                target_id="assertion-governed-target",
            )

    async def record_evidence_noop(*args, **kwargs):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(
        "magi.memory.l2.assertions.write.CorrectionPolicyEvaluator",
        GovernedPolicy,
    )
    monkeypatch.setattr(
        "magi.memory.l2.assertions.write.MemoryCorrectionRepository.append_evidence_event_ids",
        record_evidence_noop,
    )
    receipt = await l2_store_with_schema.upsert_assertion_candidate_with_receipt(
        _assertion_candidate(event_ids, claim_ids),
        claim_outcome_context=ClaimTargetOutcomeContext(
            claim_ids=tuple(claim_ids),
            attempt_key="attempt:assertion:governed",
            route_contract_version=1,
        ),
        projection_leases=leases,
    )

    assert receipt["persisted"] is False
    assert receipt["assertion_id"] == "assertion-governed-target"
    assert await l2_store_with_schema.list_current_assertions(entity_id="user:u1") == []
    for claim_id in claim_ids:
        outcomes = await l2_store_with_schema.list_claim_projection_outcomes(claim_id=claim_id)
        assert [(item["target_id"], item["outcome"], item["reason_code"]) for item in outcomes] == [
            ("assertion-governed-target", "skipped", "requires_scope")
        ]
