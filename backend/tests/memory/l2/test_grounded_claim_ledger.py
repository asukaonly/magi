"""Grounded Claim identity, provenance, replay, and privacy invariants."""

from __future__ import annotations

import asyncio
import re

import pytest

from magi.memory.l2.claims.identity import derive_claim_identity_key
from magi.memory.l2.claims.models import (
    ClaimEvidenceInput,
    GroundedClaimInput,
    ProjectionOutcomeInput,
)


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
    first = await l2_store_with_schema.upsert_grounded_claim(
        claim=_claim_input(identity_key=identity_key),
        evidence=[_evidence("evt-1")],
    )
    second = await l2_store_with_schema.upsert_grounded_claim(
        claim=_claim_input(identity_key=identity_key),
        evidence=[_evidence("evt-1")],
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

    async def write_once() -> dict:
        return await l2_store_with_schema.upsert_grounded_claim(
            claim=_claim_input(identity_key=identity_key),
            evidence=[_evidence("evt-concurrent")],
        )

    first, second = await asyncio.gather(write_once(), write_once())
    rows = await l2_store_with_schema.list_grounded_claims()

    assert first["claim_id"] == second["claim_id"]
    assert sum(int(row["created"]) for row in (first, second)) == 1
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_projection_outcome_is_idempotent_per_attempt_target(l2_store_with_schema) -> None:
    stored = await l2_store_with_schema.upsert_grounded_claim(
        claim=_claim_input(identity_key=_identity(supporting_event_ids=["evt-2"])),
        evidence=[_evidence("evt-2")],
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

    first = await l2_store_with_schema.append_claim_projection_outcome(outcome)
    second = await l2_store_with_schema.append_claim_projection_outcome(outcome)
    rows = await l2_store_with_schema.list_claim_projection_outcomes(
        claim_id=stored["claim_id"]
    )

    assert first is not None and second is not None
    assert first["outcome_id"] == second["outcome_id"]
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_forget_redacts_claim_and_invalidates_outcome(l2_store_with_schema) -> None:
    identity_key = _identity(supporting_event_ids=["evt-secret"])
    stored = await l2_store_with_schema.upsert_grounded_claim(
        claim=_claim_input(identity_key=identity_key),
        evidence=[_evidence("evt-secret")],
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
        )
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
    )
    assert replay["replay_blocked"] is True
    assert replay["claim_id"] is None


@pytest.mark.asyncio
async def test_forgetting_required_antecedent_redacts_contextual_claim(
    l2_store_with_schema,
) -> None:
    identity_key = _identity(
        supporting_event_ids=["evt-reply"],
        antecedent_event_ids=["evt-question"],
        evidence_mode="confirmation",
    )
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
    stored = await l2_store_with_schema.upsert_grounded_claim(
        claim=_claim_input(identity_key=_identity(supporting_event_ids=["evt-clear"])),
        evidence=[_evidence("evt-clear")],
    )
    await l2_store_with_schema.append_claim_projection_outcome(
        ProjectionOutcomeInput(
            claim_id=stored["claim_id"],
            attempt_key="attempt:clear:1",
            target_kind="route",
            outcome="unrouted",
            reason_code="unsupported_route",
        )
    )

    await l2_store_with_schema.clear()

    assert await l2_store_with_schema.list_grounded_claims() == []
    assert await l2_store_with_schema.list_claim_projection_outcomes(
        claim_id=stored["claim_id"]
    ) == []
