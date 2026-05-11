"""Tests for the cross-layer quality fusion in retrieval_projection_findings."""

from __future__ import annotations

import pytest

from magi.memory.hybrid_retrieval.models import RetrievalPayload, RetrievalQuery
from magi.memory.retrieval_projection_findings import build_findings


def _make_query(query: str = "test", mode: str = "exact_fact", limit: int = 10) -> RetrievalQuery:
    return RetrievalQuery(
        query=query,
        user_id="u1",
        session_id="s1",
        time_range={},
        query_mode=mode,
        limit=limit,
    )


def _make_payload(
    *,
    l1_events: list | None = None,
    l2_relationships: list | None = None,
    l2_assertions: list | None = None,
    l3_reflections: list | None = None,
    l4_procedures: list | None = None,
    trace: dict | None = None,
) -> RetrievalPayload:
    return RetrievalPayload(
        l1_events=l1_events or [],
        l2_relationships=l2_relationships or [],
        l2_assertions=l2_assertions or [],
        l3_reflections=l3_reflections or [],
        l4_procedures=l4_procedures or [],
        trace=trace or {},
    )


class TestCrossLayerFusion:
    """High-confidence results from any layer should surface regardless of mode."""

    def test_high_confidence_l2_beats_low_l1_in_exact_fact(self):
        payload = _make_payload(
            l1_events=[
                {"content": "some low-score event", "score": 0.2, "timestamp": 1.0},
            ],
            l2_relationships=[
                {"subject": "self", "predicate": "LIKES", "object": "topic:music",
                 "confidence": 0.9, "first_observed_at": 1.0},
            ],
        )
        findings = build_findings(payload, _make_query(mode="exact_fact"))
        assert findings[0]["kind"] == "relationship"

    def test_high_score_l1_beats_low_confidence_l2(self):
        """When L2 confidence is below the floor, L1 with high retrieval
        score should rank higher — the key fix for the 'L2 always wins' bug."""
        payload = _make_payload(
            l1_events=[
                {"content": "WiFi password is mypass123", "score": 0.85, "timestamp": 1.0},
            ],
            l2_relationships=[
                {"subject": "self", "predicate": "USES", "object": "software:wifi-app",
                 "confidence": 0.2, "first_observed_at": 1.0},
            ],
        )
        findings = build_findings(payload, _make_query(mode="exact_fact"))
        assert findings[0]["kind"] == "event"
        assert "WiFi" in findings[0]["statement"]

    def test_mode_is_soft_not_hard(self):
        """Even with mode=strategy, a high-confidence L2 relationship should
        still appear if L4 has nothing good."""
        payload = _make_payload(
            l2_relationships=[
                {"subject": "self", "predicate": "LIKES", "object": "topic:python",
                 "confidence": 0.95, "first_observed_at": 1.0},
            ],
        )
        findings = build_findings(payload, _make_query(mode="strategy"))
        assert len(findings) >= 1
        assert findings[0]["kind"] == "relationship"

    def test_mixed_layers_sorted_by_score(self):
        payload = _make_payload(
            l1_events=[
                {"content": "Event A", "score": 0.6, "timestamp": 1.0},
            ],
            l2_relationships=[
                {"subject": "self", "predicate": "LIKES", "object": "topic:A",
                 "confidence": 0.8, "first_observed_at": 1.0},
            ],
            l3_reflections=[
                {"summary": "Weekly summary about A", "confidence": 0.7},
            ],
        )
        findings = build_findings(payload, _make_query(mode="exact_fact"))
        scores = [f["_score"] for f in findings]
        assert scores == sorted(scores, reverse=True)

    def test_limit_respected(self):
        payload = _make_payload(
            l1_events=[
                {"content": f"Event {i}", "score": 0.5, "timestamp": float(i)}
                for i in range(20)
            ],
        )
        findings = build_findings(payload, _make_query(limit=5))
        assert len(findings) == 5


class TestConfidenceFloor:
    """Low-confidence L2 results should be penalized."""

    def test_below_floor_penalized(self):
        payload = _make_payload(
            l2_relationships=[
                {"subject": "self", "predicate": "LIKES", "object": "topic:noise",
                 "confidence": 0.2, "first_observed_at": 1.0},
                {"subject": "self", "predicate": "LIKES", "object": "topic:signal",
                 "confidence": 0.8, "first_observed_at": 1.0},
            ],
        )
        findings = build_findings(payload, _make_query(mode="exact_fact"))
        assert findings[0]["statement"].endswith("topic:signal")


class TestEchoFiltering:
    """Conversation echoes should be filtered out."""

    def test_echo_removed(self):
        payload = _make_payload(
            l1_events=[
                {"content": "我喜欢什么音乐", "score": 0.9, "timestamp": 1.0},
                {"content": "Chrome browsed Spotify", "score": 0.7, "timestamp": 2.0},
            ],
        )
        findings = build_findings(payload, _make_query(query="我喜欢什么音乐"))
        statements = [f["statement"] for f in findings]
        assert "我喜欢什么音乐" not in statements
        assert "Chrome browsed Spotify" in statements

    def test_fact_recall_filters_prior_memory_qa_artifacts(self):
        payload = _make_payload(
            l1_events=[
                {
                    "event_id": "evt-assistant-answer",
                    "event_type": "AIResponse",
                    "source": "chat_projector",
                    "author_type": "assistant",
                    "content_type": "text",
                    "content": "根据浏览记录，你访问「坤的真爱粉」直播间的时间主要集中在下午时段。",
                    "score": 0.95,
                    "timestamp": 3.0,
                },
                {
                    "event_id": "evt-user-question",
                    "event_type": "UserMessage",
                    "source": "chat_projector",
                    "author_type": "user",
                    "content_type": "text",
                    "content": "坤的真爱粉我一般在什么时候看",
                    "score": 0.9,
                    "timestamp": 2.0,
                },
                {
                    "event_id": "evt-chrome-history",
                    "event_type": "SENSOR_EVENT",
                    "source": "chrome_history",
                    "author_type": "external",
                    "content_type": "observation",
                    "content": "Chrome 浏览 坤的真爱粉的抖音直播间 - 抖音直播（访问 11 次）",
                    "score": 0.8,
                    "timestamp": 1.0,
                },
            ],
        )

        findings = build_findings(
            payload,
            _make_query(query="我通常几点打开坤的真爱粉直播间", mode="exact_fact"),
        )

        statements = [finding["statement"] for finding in findings]
        assert statements == ["Chrome 浏览 坤的真爱粉的抖音直播间 - 抖音直播（访问 11 次）"]

    def test_conversation_recall_can_keep_assistant_messages(self):
        payload = _make_payload(
            l1_events=[
                {
                    "event_id": "evt-assistant-answer",
                    "event_type": "AIResponse",
                    "source": "chat_projector",
                    "author_type": "assistant",
                    "content_type": "text",
                    "content": "上次我给出的部署步骤是先构建 sidecar，再运行 Tauri 打包。",
                    "score": 0.9,
                    "timestamp": 1.0,
                }
            ],
        )

        findings = build_findings(payload, _make_query(query="上次你怎么说部署", mode="episode_recall"))

        assert findings[0]["statement"] == "上次我给出的部署步骤是先构建 sidecar，再运行 Tauri 打包。"

    def test_fact_recall_keeps_user_self_report_with_habit_adverb(self):
        payload = _make_payload(
            l1_events=[
                {
                    "event_id": "evt-user-self-report",
                    "event_type": "UserMessage",
                    "source": "chat_projector",
                    "author_type": "user",
                    "content_type": "text",
                    "content": "我一般下午看坤的真爱粉直播。",
                    "score": 0.9,
                    "timestamp": 1.0,
                }
            ],
        )

        findings = build_findings(payload, _make_query(query="我什么时候看坤的真爱粉直播", mode="exact_fact"))

        assert findings[0]["statement"] == "我一般下午看坤的真爱粉直播。"


class TestPredicateBonus:
    """Predicate-aware sorting for preference queries."""

    def test_likes_ranked_over_uses_for_topic(self):
        payload = _make_payload(
            l2_relationships=[
                {"subject": "self", "predicate": "USES", "object": "topic:jazz",
                 "confidence": 0.7, "first_observed_at": 1.0},
                {"subject": "self", "predicate": "LIKES", "object": "topic:rock",
                 "confidence": 0.7, "first_observed_at": 1.0},
            ],
            trace={"l2_query_trace": {"semantic_frame": {"answer_kind": "topic"}}},
        )
        findings = build_findings(payload, _make_query(query="我喜欢什么音乐", mode="exact_fact"))
        assert findings[0]["statement"].endswith("topic:rock")

    def test_dislikes_first_for_negative_query(self):
        payload = _make_payload(
            l2_relationships=[
                {"subject": "self", "predicate": "LIKES", "object": "topic:pop",
                 "confidence": 0.75, "first_observed_at": 1.0},
                {"subject": "self", "predicate": "DISLIKES", "object": "topic:country",
                 "confidence": 0.75, "first_observed_at": 1.0},
            ],
        )
        findings = build_findings(payload, _make_query(query="我讨厌什么", mode="exact_fact"))
        assert "DISLIKES" in findings[0]["statement"]


class TestActivitySummaryMode:
    def test_reflections_preferred_when_available(self):
        payload = _make_payload(
            l1_events=[
                {"content": "Browsed site X", "score": 0.5, "timestamp": 1.0},
            ],
            l3_reflections=[
                {"summary": "This week you mainly browsed gaming sites", "confidence": 0.8},
            ],
        )
        findings = build_findings(payload, _make_query(mode="activity_summary"))
        assert findings[0]["kind"] == "reflection"

    def test_events_fallback_when_no_reflections(self):
        payload = _make_payload(
            l1_events=[
                {"content": "Browsed site X", "score": 0.5, "timestamp": 1.0},
            ],
        )
        findings = build_findings(payload, _make_query(mode="activity_summary"))
        assert findings[0]["kind"] == "event"


class TestEmptyPayload:
    def test_no_results(self):
        findings = build_findings(_make_payload(), _make_query())
        assert findings == []
