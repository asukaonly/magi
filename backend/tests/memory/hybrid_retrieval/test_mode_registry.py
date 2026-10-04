"""Mode policy verified through plan construction, storage and answer quotas."""

from unittest.mock import AsyncMock

import pytest

from magi.memory.hybrid_retrieval.mode_registry import MODE_REGISTRY
from magi.memory.hybrid_retrieval.models import (
    IntentDeciderInput,
    RetrievalConfig,
    RetrievalPayload,
    RetrievalQuery,
)
from magi.memory.hybrid_retrieval.rule_intent_decider import RuleBasedIntentDecider
from magi.memory.hybrid_retrieval.service import HybridRetrievalService
from magi.memory.retrieval_projection_findings import build_findings

_MODE_LAYERS = {
    "event_stream": (["L1"], []),
    "exact_fact": (["L2"], ["L1"]),
    "current_state": (["L2"], ["L1"]),
    "episode_recall": (["L2", "L1"], ["L3"]),
    "experience_recall": (["L2", "L1"], ["L3"]),
    "cross_session": (["L2", "L1"], ["L3"]),
    "temporal_compare": (["L2", "L1"], ["L3"]),
    "summary": (["L3"], ["L1"]),
    "strategy": (["L4"], ["L1"]),
    "activity_summary": (["L3"], ["L1"]),
}


@pytest.mark.parametrize("mode", list(_MODE_LAYERS))
def test_supported_modes_build_reachable_plans_and_cap_ranked_findings(mode):
    assert set(MODE_REGISTRY) == set(_MODE_LAYERS)
    plan = MODE_REGISTRY[mode]
    assert plan.mode == mode
    assert plan.layer_quota and all(
        type(n) is int and 0 < n < 32 for n in plan.layer_quota.values()
    )
    decision = RuleBasedIntentDecider().evaluate(
        IntentDeciderInput(query="codename", query_mode_hint=mode)
    )
    primary, fallback = _MODE_LAYERS[mode]
    assert [(p.layer, p.is_fallback) for p in decision.plans] == [
        (layer, False) for layer in primary
    ] + [(layer, True) for layer in fallback]
    payload = RetrievalPayload(
        l1_events=[
            {
                "event_id": f"L1-{i}",
                "content": f"Record {i}",
                "score": 0.5 + i / 100,
                "timestamp": 1.0,
            }
            for i in range(32)
        ],
        l2_relationships=[
            {
                "triple_id": f"L2-{i}",
                "subject": "self",
                "predicate": "USES",
                "object": f"tool:{i}",
                "confidence": 0.5 + i / 100,
            }
            for i in range(32)
        ],
    )
    findings, dropped = build_findings(
        payload, RetrievalQuery(query="codename", query_mode=mode, limit=1)
    )
    assert dropped == 0
    for layer, kind in [("L1", "event"), ("L2", "relationship")]:
        count = max(1, plan.layer_quota.get(layer, 0))
        assert [item["feedback_ref"] for item in findings if item["source_layer"] == layer] == [
            f"{kind}:{layer}-{i}" for i in range(31, 31 - count, -1)
        ]
        assert payload.trace["layer_quota"]["kept_per_layer"][layer] == count
    if mode == "cross_session":
        assert plan.layer_quota["L1"] > MODE_REGISTRY["current_state"].layer_quota["L1"]
        assert plan.layer_quota["L2"] >= MODE_REGISTRY["current_state"].layer_quota["L2"]
    elif mode == "event_stream":
        assert plan.layer_quota["L1"] >= 12
    elif mode == "experience_recall":
        assert plan.layer_quota["L2"] >= 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["episode_recall", "experience_recall", "cross_session", "temporal_compare"]
)
async def test_recall_modes_execute_experience_and_evidence_policy_without_episode_substrate(
    historical_memory, monkeypatch, mode
):
    from magi.memory.hybrid_retrieval import l2_query_execution

    substrate = AsyncMock(wraps=l2_query_execution.retrieve_episodes)
    monkeypatch.setattr(l2_query_execution, "retrieve_episodes", substrate)
    await historical_memory.l2.create_experience(
        experience_id="exp-codename",
        title="Codename decision",
        user_label="Codename decision",
        status="active",
        time_start=1599999990.0,
        time_end=1600000010.0,
        source_event_count=1,
    )
    await historical_memory.l2.create_experience(
        experience_id="exp-unrelated",
        title="Garden planting",
        user_label="Garden planting",
        status="active",
        time_start=1599999990.0,
        time_end=1600000010.0,
        source_event_count=1,
    )
    service = HybridRetrievalService(
        historical_memory, config=RetrievalConfig(intent_decider_llm_enabled=False)
    )
    result = await service.query(RetrievalQuery(query="codename", query_mode=mode, user_id="u1"))
    recalls_experience = mode in {"episode_recall", "experience_recall"}
    assert [item["experience_id"] for item in result.l2_experiences] == (
        ["exp-codename"] if recalls_experience else []
    )
    assert {item["event_id"] for item in result.l1_events} == (
        {"old-name", "external-name"} if recalls_experience else {"external-name"}
    )
    assert result.l2_episodes == []
    substrate.assert_not_awaited()
