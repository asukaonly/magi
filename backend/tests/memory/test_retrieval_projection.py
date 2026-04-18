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
        query_mode="exact_fact",
    )

    projected = project_historical_recall(payload=payload, request=request)

    assert projected.status == "found"
    assert projected.query_mode == "exact_fact"
    assert projected.query_mode == "exact_fact"
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
        query_mode="exact_fact",
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
        query_mode="exact_fact",
    )

    projected = project_historical_recall(payload=payload, request=request)

    assert projected.status == "found"
    assert projected.summary == "你关注永雏塔菲。"


def test_project_historical_recall_summarizes_top_follows_for_list_preference_query() -> None:
    payload = RetrievalPayload(
        l2_relationships=[
            {
                "triple_id": "triple-7",
                "subject_id": "user:local_user",
                "predicate": "INTERESTED_IN",
                "object_id": "person:某个up主",
                "confidence": 0.99,
                "status": "active",
                "updated_at": 1774499528.09,
            },
            {
                "triple_id": "triple-2",
                "subject_id": "user:local_user",
                "predicate": "FOLLOWS",
                "object_id": "person:永雏塔菲",
                "confidence": 0.92,
                "status": "active",
                "updated_at": 1774499528.09,
            },
            {
                "triple_id": "triple-5",
                "subject_id": "user:local_user",
                "predicate": "FOLLOWS",
                "object_id": "person:嘉然",
                "confidence": 0.89,
                "status": "active",
                "updated_at": 1774499528.09,
            },
        ],
        trace={"primary_count": 2},
    )
    request = RetrievalQuery(
        query="我B站喜欢哪些up主",
        user_id="local_user",
        session_id="session-1",
        time_range={},
        query_mode="exact_fact",
    )

    projected = project_historical_recall(payload=payload, request=request)

    assert projected.status == "found"
    assert projected.summary == "你关注永雏塔菲、嘉然。"
    assert projected.findings[0]["statement"] == "user:local_user FOLLOWS person:永雏塔菲"
    assert projected.findings[1]["statement"] == "user:local_user FOLLOWS person:嘉然"


def test_project_historical_recall_summarizes_uses_for_preference_recall() -> None:
    payload = RetrievalPayload(
        l2_relationships=[
            {
                "triple_id": "triple-3",
                "subject_id": "user:local_user",
                "predicate": "USES",
                "object_id": "software:bilibili",
                "confidence": 0.89,
                "status": "active",
                "updated_at": 1774499528.09,
            }
        ],
        trace={"primary_count": 1},
    )
    request = RetrievalQuery(
        query="我喜欢B站吗",
        user_id="local_user",
        session_id="session-1",
        time_range={},
        query_mode="exact_fact",
    )

    projected = project_historical_recall(payload=payload, request=request)

    assert projected.status == "found"
    assert projected.summary == "你有使用bilibili的记录。"


def test_project_historical_recall_summarizes_topic_affinity_for_preference_recall() -> None:
    payload = RetrievalPayload(
        l2_relationships=[
            {
                "triple_id": "triple-4",
                "subject_id": "user:local_user",
                "predicate": "INTERESTED_IN",
                "object_id": "topic:anime",
                "confidence": 0.91,
                "status": "active",
                "updated_at": 1774499528.09,
            }
        ],
        trace={"primary_count": 1},
    )
    request = RetrievalQuery(
        query="我喜欢什么题材",
        user_id="local_user",
        session_id="session-1",
        time_range={},
        query_mode="exact_fact",
    )

    projected = project_historical_recall(payload=payload, request=request)

    assert projected.status == "found"
    assert projected.summary == "你对anime题材感兴趣。"


def test_project_historical_recall_summarizes_top_topics_for_list_preference_query() -> None:
    payload = RetrievalPayload(
        l2_relationships=[
            {
                "triple_id": "triple-4",
                "subject_id": "user:local_user",
                "predicate": "INTERESTED_IN",
                "object_id": "topic:anime",
                "confidence": 0.91,
                "status": "active",
                "updated_at": 1774499528.09,
            },
            {
                "triple_id": "triple-6",
                "subject_id": "user:local_user",
                "predicate": "INTERESTED_IN",
                "object_id": "topic:mystery",
                "confidence": 0.87,
                "status": "active",
                "updated_at": 1774499528.09,
            },
        ],
        trace={"primary_count": 2},
    )
    request = RetrievalQuery(
        query="我喜欢什么题材",
        user_id="local_user",
        session_id="session-1",
        time_range={},
        query_mode="exact_fact",
    )

    projected = project_historical_recall(payload=payload, request=request)

    assert projected.status == "found"
    assert projected.summary == "你对anime题材、mystery题材感兴趣。"


def test_project_historical_recall_prefers_semantic_frame_over_misleading_query_tokens() -> None:
    payload = RetrievalPayload(
        l2_relationships=[
            {
                "triple_id": "triple-8",
                "subject_id": "user:local_user",
                "predicate": "LIKES",
                "object_id": "topic:anime",
                "confidence": 0.95,
                "status": "active",
                "updated_at": 1774499528.09,
            },
            {
                "triple_id": "triple-9",
                "subject_id": "user:local_user",
                "predicate": "INTERESTED_IN",
                "object_id": "topic:mystery",
                "confidence": 0.80,
                "status": "active",
                "updated_at": 1774499528.09,
            },
        ],
        trace={
            "primary_count": 2,
            "l2_query_trace": {
                "semantic_frame": {
                    "answer_kind": "topic",
                }
            },
        },
    )
    request = RetrievalQuery(
        query="上次我看的主播他说的主题是什么",
        user_id="local_user",
        session_id="session-1",
        time_range={},
        query_mode="exact_fact",
    )

    projected = project_historical_recall(payload=payload, request=request)

    assert projected.summary == "你对mystery题材感兴趣。"
    assert projected.findings[0]["statement"] == "user:local_user INTERESTED_IN topic:mystery"
    assert projected.findings[1]["statement"] == "user:local_user LIKES topic:anime"


def test_project_historical_recall_infers_answer_kind_from_findings_before_query_tokens() -> None:
    payload = RetrievalPayload(
        l2_relationships=[
            {
                "triple_id": "triple-10",
                "subject_id": "user:local_user",
                "predicate": "LIKES",
                "object_id": "topic:anime",
                "confidence": 0.95,
                "status": "active",
                "updated_at": 1774499528.09,
            },
            {
                "triple_id": "triple-11",
                "subject_id": "user:local_user",
                "predicate": "INTERESTED_IN",
                "object_id": "topic:mystery",
                "confidence": 0.80,
                "status": "active",
                "updated_at": 1774499528.09,
            },
        ],
        trace={"primary_count": 2},
    )
    request = RetrievalQuery(
        query="上次我看的主播他说的主题是什么",
        user_id="local_user",
        session_id="session-1",
        time_range={},
        query_mode="exact_fact",
    )

    projected = project_historical_recall(payload=payload, request=request)

    assert projected.summary == "你对mystery题材感兴趣。"
    assert projected.findings[0]["statement"] == "user:local_user INTERESTED_IN topic:mystery"
