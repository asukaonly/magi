"""Tests for answer-facing memory retrieval projection."""

from __future__ import annotations

from magi.memory.hybrid_retrieval.models import RetrievalPayload, RetrievalQuery
from magi.memory.retrieval_projection import project_historical_recall


def test_project_historical_recall_prefers_l2_relationships_for_preference_recall() -> None:
    payload = RetrievalPayload(
        l2_relationships=[
            {
                "triple_id": "triple-1",
                "subject_id": "user:local_user",
                "predicate": "DISLIKES",
                "object_id": "weather_state:humid",
                "confidence": 0.97,
                "status": "active",
                "updated_at": 1774499528.09,
            }
        ],
        trace={
            "query_mode": "detail",
            "primary_count": 1,
        },
    )
    request = RetrievalQuery(
        query="我讨厌什么天气来着",
        user_id="local_user",
        session_id="session-1",
        time_range={},
        recall_intent="preference_recall",
        query_mode="detail",
    )

    projected = project_historical_recall(payload=payload, request=request)

    assert projected.status == "found"
    assert projected.recall_intent == "preference_recall"
    assert projected.query_mode == "detail"
    assert projected.summary == "你讨厌潮湿天气。"
    assert projected.insufficient_evidence is False
    assert projected.findings == [
        {
            "kind": "relationship",
            "statement": "user:local_user DISLIKES weather_state:humid",
            "source_layer": "L2",
            "confidence": 0.97,
            "status": "active",
            "occurred_at": None,
            "updated_at": 1774499528.09,
            "evidence_ref_ids": ["triple-1"],
        }
    ]
    assert projected.provenance["primary_count"] == 1
    assert projected.provenance["source_layers"] == ["L2"]
    assert projected.answering_hints["must_not_guess_when_empty"] is True


def test_project_historical_recall_returns_not_found_when_no_results_exist() -> None:
    request = RetrievalQuery(
        query="我喜欢什么天气",
        user_id="local_user",
        session_id="session-1",
        time_range={},
        recall_intent="preference_recall",
        query_mode="detail",
    )

    projected = project_historical_recall(payload=RetrievalPayload(), request=request)

    assert projected.status == "not_found"
    assert projected.summary == "未检索到可确认的历史记忆。"
    assert projected.findings == []
    assert projected.insufficient_evidence is True
    assert projected.provenance["source_layers"] == []


def test_project_historical_recall_summarizes_follows_for_preference_recall() -> None:
    payload = RetrievalPayload(
        l2_relationships=[
            {
                "triple_id": "triple-2",
                "subject_id": "user:local_user",
                "predicate": "FOLLOWS",
                "object_id": "person:永雏塔菲",
                "confidence": 0.92,
                "status": "active",
                "updated_at": 1774499528.09,
            }
        ],
        trace={"primary_count": 1},
    )
    request = RetrievalQuery(
        query="我B站喜欢哪些up主",
        user_id="local_user",
        session_id="session-1",
        time_range={},
        recall_intent="preference_recall",
        query_mode="detail",
    )

    projected = project_historical_recall(payload=payload, request=request)

    assert projected.status == "found"
    assert projected.summary == "你关注永雏塔菲。"
