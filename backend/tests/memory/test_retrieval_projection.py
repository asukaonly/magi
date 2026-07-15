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
    assert len(projected.findings) == 1
    f = projected.findings[0]
    assert f["kind"] == "relationship"
    assert f["statement"] == "user:local_user DISLIKES weather_state:humid"
    assert f["source_layer"] == "L2"
    assert f["confidence"] == 0.97
    assert f["feedback_ref"] == "relationship:triple-1"
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


def test_project_historical_recall_keeps_l1_evidence_for_temporal_exact_fact_queries() -> None:
    payload = RetrievalPayload(
        l1_events=[
            {
                "event_id": "evt-photo-1",
                "content": "2022-09-02 周五傍晚用 Apple iPhone 13 Pro Max 在Hangzhou, 浙江省拍摄了1 张照片",
                "score": 0.93,
                "timestamp": 1662114600.0,
            }
        ],
        l2_relationships=[
            {
                "triple_id": "triple-place-1",
                "subject_id": "user:local_user",
                "predicate": "VISITED",
                "object_id": "place:hangzhou",
                "confidence": 0.87,
                "status": "active",
                "first_observed_at": 1662114600.0,
                "updated_at": 1774499528.09,
            }
        ],
        trace={"primary_count": 2},
    )
    request = RetrievalQuery(
        query="2022年9月我在哪里拍了照片",
        user_id="local_user",
        session_id="session-1",
        time_range={"start": 1661990400.0, "end": 1664582399.0},
        query_mode="exact_fact",
        limit=5,
    )

    projected = project_historical_recall(payload=payload, request=request)

    assert projected.status == "found"
    layers = [f["source_layer"] for f in projected.findings]
    assert "L1" in layers
    assert "L2" in layers
    assert len(projected.findings) == 2
    assert {f["feedback_ref"] for f in projected.findings} == {
        "event:evt-photo-1",
        "relationship:triple-place-1",
    }


def test_project_historical_recall_emits_generic_entity_and_asset_refs() -> None:
    payload = RetrievalPayload(
        l1_events=[
            {
                "event_id": "evt-photo-1",
                "source": "timeline",
                "content_type": "image",
                "timestamp": "2022-09-02T10:30:00Z",
                "content": "West Lake sunrise",
                "metadata_json": {
                    "activity_snapshot": {
                        "source_type": "photo_library",
                        "source_item_id": "photo-1",
                        "title": "West Lake sunrise",
                        "kind": "image",
                        "provenance": {
                            "filename": "hangzhou.jpg",
                            "location_name": "West Lake",
                            "device_name": "iPhone 13 Pro Max",
                        },
                    }
                },
            }
        ],
        l2_entity_cards=[
            {
                "entity_id": "place:west-lake",
                "entity_type": "place",
                "canonical_name": "West Lake",
            }
        ],
        trace={
            "query_mode": "episode_recall",
            "l2_query_trace": {
                "resolved_entities": [
                    {
                        "entity_id": "place:west-lake",
                        "canonical_name": "West Lake",
                        "match_source": "explicit_query",
                    }
                ]
            },
        },
    )
    request = RetrievalQuery(
        query="2022年9月我在哪里拍了照片",
        user_id="local_user",
        session_id="session-1",
        time_range={"start": 1661990400.0, "end": 1664582399.0},
        query_mode="episode_recall",
    )

    projected = project_historical_recall(payload=payload, request=request)

    assert projected.entity_refs == [
        {
            "entity_id": "place:west-lake",
            "entity_type": "place",
            "canonical_name": "West Lake",
            "match_source": "explicit_query",
        }
    ]
    assert projected.asset_refs == [
        {
            "asset_ref_id": "photo-1",
            "kind": "image",
            "event_id": "evt-photo-1",
            "source_type": "photo_library",
            "source_item_id": "photo-1",
            "original_name": "hangzhou.jpg",
            "display_name": "West Lake sunrise",
            "captured_at": "2022-09-02T10:30:00Z",
            "occurred_at": "2022-09-02T10:30:00Z",
            "attributes": {
                "location_name": "West Lake",
                "device_name": "iPhone 13 Pro Max",
            },
        }
    ]


def test_project_historical_recall_keeps_one_l1_event_for_non_list_exact_fact_queries() -> None:
    payload = RetrievalPayload(
        l1_events=[
            {
                "event_id": "evt-preference-1",
                "content": "我最近一直用 Bilibili 看视频，昨晚还收藏了两个番剧解说。",
                "score": 0.88,
                "timestamp": 1710000000.0,
            }
        ],
        l2_relationships=[
            {
                "triple_id": "triple-software-1",
                "subject_id": "user:local_user",
                "predicate": "USES",
                "object_id": "software:bilibili",
                "confidence": 0.89,
                "status": "active",
                "updated_at": 1774499528.09,
            }
        ],
        trace={"primary_count": 2},
    )
    request = RetrievalQuery(
        query="我喜欢B站吗",
        user_id="local_user",
        session_id="session-1",
        time_range={},
        query_mode="exact_fact",
        limit=5,
    )

    projected = project_historical_recall(payload=payload, request=request)

    layers = [f["source_layer"] for f in projected.findings]
    assert "L1" in layers
    assert "L2" in layers
    assert len(projected.findings) == 2


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
    follows = [f for f in projected.findings if "FOLLOWS" in f["statement"]]
    assert len(follows) == 2


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

    statements = [f["statement"] for f in projected.findings]
    assert "user:local_user INTERESTED_IN topic:mystery" in statements
    assert "user:local_user LIKES topic:anime" in statements
    assert projected.findings[0]["statement"] == "user:local_user INTERESTED_IN topic:mystery"


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

    assert projected.findings[0]["statement"] == "user:local_user INTERESTED_IN topic:mystery"


def test_coerce_request_propagates_all_fields_from_dict() -> None:
    """Round 5 #8: dict path of _coerce_request must preserve exclude_user_text,
    conversation_context, and summary_categories — earlier it silently dropped
    them, degrading callers that passed dicts (tests / plugins)."""
    from magi.memory.hybrid_retrieval.models import ConversationTurn
    from magi.memory.retrieval_projection import _coerce_request

    turn = ConversationTurn(role="user", content="hi", timestamp=1.0)
    coerced = _coerce_request(
        {
            "query": "q",
            "user_id": "u",
            "session_id": "s",
            "time_range": {"start": 1},
            "query_mode": "exact_fact",
            "source_filters": ["chrome"],
            "domain_filters": ["d.com"],
            "summary_categories": ["work"],
            "limit": 5,
            "exclude_user_text": "echo",
            "conversation_context": [turn],
        }
    )
    assert coerced.exclude_user_text == "echo"
    assert coerced.conversation_context == [turn]
    assert coerced.summary_categories == ["work"]
    assert coerced.source_filters == ["chrome"]
    assert coerced.domain_filters == ["d.com"]
    assert coerced.limit == 5
