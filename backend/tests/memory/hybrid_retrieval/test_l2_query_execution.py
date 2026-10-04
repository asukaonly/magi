"""L2 diagnostic serialization and execution logging contracts."""

import logging
from unittest.mock import AsyncMock

import pytest

from magi.memory.hybrid_retrieval import l2_query_execution as execution
from magi.memory.hybrid_retrieval.grounding import (
    GroundedEntityCandidate,
    GroundedPredicateCandidate,
    L2GroundingPlan,
)
from magi.memory.hybrid_retrieval.models import L2Conditions


def _populated_plan():
    plan = L2GroundingPlan(
        query_kind="exact_fact",
        subject_scope="explicit",
        answer_kind="place",
        predicate_family="location",
        confidence=0.85,
        allowed_evidence_classes={"user_self_report", "external_observation"},
        evidence_focus_source="llm",
        predicate_source="embedding",
        fact_abstention_reason="object_unresolved",
        subject_candidates=[
            GroundedEntityCandidate(
                entity_id="user:private", entity_type="user", surface="self", score=1.0
            )
        ],
        object_candidates=[
            GroundedEntityCandidate(
                entity_id="place:shanghai", entity_type="place", surface="Shanghai", score=0.9
            ),
            GroundedEntityCandidate(
                entity_id="place:tokyo", entity_type="place", surface="Tokyo", score=0.8
            ),
        ],
        predicate_candidates=[GroundedPredicateCandidate(predicate="LIVES_IN")],
    )
    plan.temporal_context.mode = "as_of"
    return plan


@pytest.mark.parametrize("state", ["default", "empty-evidence", "populated"])
def test_grounding_trace_preserves_values_counts_and_provenance(state):
    plan = _populated_plan() if state == "populated" else L2GroundingPlan()
    if state == "empty-evidence":
        plan.allowed_evidence_classes = set()
    expected = {
        "query_kind": "unknown",
        "subject_scope": "none",
        "fact_abstention_reason": None,
        "answer_kind": "unknown",
        "predicate_family": None,
        "confidence": 0.5,
        "temporal_mode": "none",
        "subject_count": 0,
        "object_count": 0,
        "predicate_count": 0,
        "allowed_evidence_classes": None,
        "evidence_focus_source": None,
        "predicate_source": None,
        "subject_entity_ids": [],
        "object_entity_ids": [],
    }
    if state == "populated":
        expected.update(
            query_kind="exact_fact",
            subject_scope="explicit",
            fact_abstention_reason="object_unresolved",
            answer_kind="place",
            predicate_family="location",
            confidence=0.85,
            temporal_mode="as_of",
            subject_count=1,
            object_count=2,
            predicate_count=1,
            allowed_evidence_classes=["external_observation", "user_self_report"],
            evidence_focus_source="llm",
            predicate_source="embedding",
            subject_entity_ids=["user:private"],
            object_entity_ids=["place:shanghai", "place:tokyo"],
        )
    trace = execution._build_grounding_plan_trace(plan)
    assert {key: trace[key] for key in expected} == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("full_logging", [False, True])
async def test_execute_returns_diagnostics_and_obeys_content_logging_policy(
    monkeypatch, caplog, full_logging
):
    plan = _populated_plan()
    plan_builder = AsyncMock(return_value=plan)
    channels = execution._L2ChannelResults(
        knowledge_edges=[],
        assertions=[],
        snapshots=[],
        episodes=[],
        experiences=[{"experience_id": "experience:private"}],
        assertion_retrieval_trace={"semantic_hits": 2},
    )
    channel_reader = AsyncMock(return_value=channels)
    monkeypatch.setattr(execution, "_build_query_plan", plan_builder)
    monkeypatch.setattr(execution, "_retrieve_l2_channels", channel_reader)
    monkeypatch.setattr(execution, "full_content_logging_enabled", lambda: full_logging)
    host = execution.L2QueryExecutionMixin()
    conditions = L2Conditions(limit=4)
    with caplog.at_level(logging.INFO, logger=execution.__name__):
        result = await host.execute(conditions, user_id="private")
    plan_builder.assert_awaited_once_with(host, conditions, user_id="private", time_range=None)
    channel_reader.assert_awaited_once_with(
        host, plan, conditions, user_id="private", time_range=None
    )
    trace = result["trace"]
    assert trace["grounding_plan"]["subject_entity_ids"] == ["user:private"]
    assert trace["channel_counts"] == {
        "knowledge_edges": 0,
        "assertions": 0,
        "snapshots": 0,
        "episodes": 0,
        "experiences": 1,
    }
    assert trace["assertion_retrieval"] == {"semantic_hits": 2}
    assert trace["fusion_candidate_count"] == 0
    assert trace["output_counts"] == {
        "entity_cards": 0,
        "relationships": 0,
        "assertions": 0,
        "episodes": 0,
        "experiences": 1,
        "state_history": 0,
    }
    assert result["experiences"] == [{"experience_id": "experience:private"}]
    records = [record for record in caplog.records if record.name == execution.__name__]
    assert len(records) == 1
    if full_logging:
        assert records[0].getMessage() == f"L2 retrieval executed | {trace}"
        assert "user:private" in records[0].getMessage()
    else:
        assert (
            records[0].getMessage()
            == "L2 retrieval executed | entity_cards=0 relationships=0 assertions=0 episodes=0 experiences=1"
        )
