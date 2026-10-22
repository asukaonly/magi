"""Tests for the cross-layer quality fusion in retrieval_projection_findings."""

from __future__ import annotations

import pytest

from magi.memory.hybrid_retrieval.models import RetrievalPayload, RetrievalQuery
from magi.memory.retrieval_projection_findings import build_findings as _build_findings_impl


def build_findings(payload, request, canonical_names=None):
    """Test-only wrapper that returns just the findings list.

    The production ``build_findings`` returns ``(findings, dropped_count)``
    as of Phase 5. These tests pre-date that contract and only care about
    the findings; the wrapper keeps them ergonomic without rewriting every
    callsite (the drop count is exercised in
    ``test_retrieval_projection_canonical_names.py``).
    """
    findings, _dropped = _build_findings_impl(payload, request, canonical_names)
    return findings


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
    l2_experiences: list | None = None,
    l3_reflections: list | None = None,
    l4_procedures: list | None = None,
    trace: dict | None = None,
) -> RetrievalPayload:
    return RetrievalPayload(
        l1_events=l1_events or [],
        l2_relationships=l2_relationships or [],
        l2_assertions=l2_assertions or [],
        l2_experiences=l2_experiences or [],
        l3_reflections=l3_reflections or [],
        l4_procedures=l4_procedures or [],
        trace=trace or {},
    )


class TestCrossLayerFusion:
    """Results from all layers surface; per-layer quota governs counts."""

    def test_experience_recall_projects_experiences(self):
        payload = _make_payload(
            l2_experiences=[
                {
                    "experience_id": "exp-japan",
                    "title": "日本旅行",
                    "user_label": "2026年5月日本旅行",
                    "magi_interpretation": "在路线、车票和城市切换之间整理旅行节奏。",
                    "time_start": 1777564800.0,
                    "time_end": 1778342400.0,
                    "_retrieval_score": 0.91,
                }
            ],
        )

        findings = build_findings(
            payload, _make_query(query="那次日本旅行", mode="experience_recall")
        )

        assert findings[0]["kind"] == "experience"
        assert "日本旅行" in findings[0]["statement"]
        assert findings[0]["source_layer"] == "L2"


    def test_mode_is_soft_not_hard(self):
        """Even with mode=strategy, a high-confidence L2 relationship should
        still appear if L4 has nothing good."""
        payload = _make_payload(
            l2_relationships=[
                {
                    "subject": "self",
                    "predicate": "LIKES",
                    "object": "topic:python",
                    "confidence": 0.95,
                    "first_observed_at": 1.0,
                },
            ],
        )
        findings = build_findings(payload, _make_query(mode="strategy"))
        assert len(findings) >= 1
        assert findings[0]["kind"] == "relationship"

    def test_each_nonempty_layer_preserves_exact_candidates_and_internal_score_order(self):
        payload = _make_payload(
            l1_events=[
                {"event_id": "event-low", "content": "Event Lo", "score": 0.3, "timestamp": 1.0},
                {"event_id": "event-high", "content": "Event Hi", "score": 0.9, "timestamp": 2.0},
            ],
            l2_relationships=[
                {
                    "triple_id": "rel-low",
                    "subject": "self",
                    "predicate": "LIKES",
                    "object": "topic:lo",
                    "confidence": 0.2,
                },
                {
                    "triple_id": "rel-high",
                    "subject": "self",
                    "predicate": "LIKES",
                    "object": "topic:hi",
                    "confidence": 0.9,
                },
            ],
        )
        findings = build_findings(payload, _make_query(mode="exact_fact"))
        assert [(f["source_layer"], f["feedback_ref"], f["statement"]) for f in findings] == [
            ("L1", "event:event-high", "Event Hi"),
            ("L1", "event:event-low", "Event Lo"),
            ("L2", "relationship:rel-high", "self LIKES topic:hi"),
            ("L2", "relationship:rel-low", "self LIKES topic:lo"),
        ]
        assert payload.trace["layer_quota"]["kept_per_layer"] == {"L1": 2, "L2": 2}


class TestConfidenceFloor:
    """Low-confidence L2 results should be penalized."""

    @pytest.mark.parametrize(
        "confidence,expected",
        [
            (0.34, ["assertion:control", "relationship:edge"]),
            (0.35, ["relationship:edge", "assertion:control"]),
        ],
    )
    def test_confidence_floor_changes_order_against_a_fixed_competitor(self, confidence, expected):
        payload = _make_payload(
            l2_relationships=[
                {
                    "triple_id": "edge",
                    "subject": "self",
                    "predicate": "USES",
                    "object": "topic:editor",
                    "confidence": confidence,
                }
            ],
            l2_assertions=[
                {
                    "assertion_id": "control",
                    "subject": "self",
                    "predicate": "preference",
                    "claim": "A stable control",
                    "confidence": 0.4,
                }
            ],
        )
        findings = build_findings(payload, _make_query(mode="exact_fact"))
        assert [f["feedback_ref"] for f in findings] == expected


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

    def test_exclude_user_text_filters_rephrased_query(self):
        """When the LLM rephrases the query, the user's original message
        text (passed via exclude_user_text) should still be filtered out."""
        payload = _make_payload(
            l1_events=[
                {"content": "5月14我听了什么歌", "score": 0.9, "timestamp": 1.0},
                {"content": "Primal Scream - Movin' on Up", "score": 0.7, "timestamp": 2.0},
            ],
        )
        query = RetrievalQuery(
            query="5月14日听的音乐",  # LLM-rephrased; does not match the original
            user_id="u1",
            session_id="s1",
            time_range={},
            query_mode="exact_fact",
            limit=10,
            exclude_user_text="5月14我听了什么歌",
        )
        findings = build_findings(payload, query)
        statements = [f["statement"] for f in findings]
        assert "5月14我听了什么歌" not in statements
        assert "Primal Scream - Movin' on Up" in statements

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
                    "event_type": "SOURCE_EVENT",
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

        findings = build_findings(
            payload, _make_query(query="上次你怎么说部署", mode="episode_recall")
        )

        assert (
            findings[0]["statement"] == "上次我给出的部署步骤是先构建 sidecar，再运行 Tauri 打包。"
        )

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

        findings = build_findings(
            payload, _make_query(query="我什么时候看坤的真爱粉直播", mode="exact_fact")
        )

        assert findings[0]["statement"] == "我一般下午看坤的真爱粉直播。"


class TestEvidenceClassDrivenFiltering:
    """``evidence_class`` is the source of truth, with the legacy heuristic
    kept strictly as a fallback for rows without a usable annotation."""

    def test_evidence_class_user_question_filtered_regardless_of_content(self):
        """Sentences that lack a question mark but are marked as user_question
        by L1 governance must still be dropped from fact-like recall."""
        payload = _make_payload(
            l1_events=[
                {
                    "event_id": "evt-question-no-mark",
                    "event_type": "UserMessage",
                    "source": "chat_projector",
                    "author_type": "user",
                    "content_type": "text",
                    "evidence_class": "user_question",
                    "content": "请告诉我我一般在什么时候看坤的真爱粉直播",
                    "score": 0.9,
                    "timestamp": 2.0,
                },
                {
                    "event_id": "evt-chrome-history",
                    "event_type": "SOURCE_EVENT",
                    "source": "chrome_history",
                    "author_type": "external",
                    "content_type": "observation",
                    "evidence_class": "external_observation",
                    "content": "Chrome 浏览 坤的真爱粉的抖音直播间（访问 11 次）",
                    "score": 0.7,
                    "timestamp": 1.0,
                },
            ],
        )

        findings = build_findings(
            payload,
            _make_query(query="我通常几点打开坤的真爱粉直播间", mode="exact_fact"),
        )

        statements = [finding["statement"] for finding in findings]
        assert statements == ["Chrome 浏览 坤的真爱粉的抖音直播间（访问 11 次）"]

        assert payload.trace["projection_filter"] == {
            "count": 1,
            "dropped": [
                {
                    "event_id": "evt-question-no-mark",
                    "evidence_class": "user_question",
                    "reason": "answer_facing_chat_artifact",
                }
            ],
        }

    def test_evidence_class_user_self_report_kept_even_when_string_looks_like_question(self):
        """When evidence_class is trusted, the legacy string heuristic must
        not fire — a user_self_report that incidentally ends with a question
        mark stays as factual evidence."""
        payload = _make_payload(
            l1_events=[
                {
                    "event_id": "evt-self-report",
                    "event_type": "UserMessage",
                    "source": "chat_projector",
                    "author_type": "user",
                    "content_type": "text",
                    "evidence_class": "user_self_report",
                    "content": "我一般下午看坤的真爱粉直播？",
                    "score": 0.9,
                    "timestamp": 1.0,
                }
            ],
        )

        findings = build_findings(
            payload,
            _make_query(query="我什么时候看坤的真爱粉直播", mode="exact_fact"),
        )

        assert findings[0]["statement"] == "我一般下午看坤的真爱粉直播？"

    def test_evidence_class_user_question_is_historical_in_conversation_recall(self):
        """Conversation recall keeps a question as a question, never as a fact."""
        payload = _make_payload(
            l1_events=[
                {
                    "event_id": "evt-q",
                    "event_type": "UserMessage",
                    "source": "chat_projector",
                    "author_type": "user",
                    "content_type": "text",
                    "evidence_class": "user_question",
                    "content": "杭州天气怎么样",
                    "score": 0.9,
                    "timestamp": 2.0,
                },
                {
                    "event_id": "evt-obs",
                    "event_type": "SOURCE_EVENT",
                    "source": "chrome_history",
                    "author_type": "external",
                    "content_type": "observation",
                    "evidence_class": "external_observation",
                    "content": "Chrome 浏览 天气网 杭州 7 天预报",
                    "score": 0.7,
                    "timestamp": 1.0,
                },
            ],
        )

        findings = build_findings(
            payload,
            _make_query(query="杭州最近天气", mode="episode_recall"),
        )

        statements = [finding["statement"] for finding in findings]
        assert "杭州天气怎么样" in statements
        assert "Chrome 浏览 天气网 杭州 7 天预报" in statements
        question = next(f for f in findings if f["feedback_ref"] == "event:evt-q")
        assert question["author_type"] == "user"
        assert question["evidence_class"] == "user_question"
        assert question["evidence_semantics"] == "historical_record"


    def test_evidence_class_unknown_falls_back_to_legacy_heuristic(self):
        """Rows without a usable evidence_class must still be filtered by the
        legacy author/source/content shape, otherwise unbackfilled data leaks
        into fact-like recall."""
        payload = _make_payload(
            l1_events=[
                {
                    "event_id": "evt-legacy-assistant",
                    "event_type": "AIResponse",
                    "source": "chat_projector",
                    "author_type": "assistant",
                    "content_type": "text",
                    "evidence_class": "unknown",
                    "content": "根据浏览记录，你访问该直播间主要集中在下午时段。",
                    "score": 0.95,
                    "timestamp": 2.0,
                },
                {
                    "event_id": "evt-legacy-chrome",
                    "event_type": "SOURCE_EVENT",
                    "source": "chrome_history",
                    "author_type": "external",
                    "content_type": "observation",
                    "content": "Chrome 浏览 该直播间（访问 11 次）",
                    "score": 0.7,
                    "timestamp": 1.0,
                },
            ],
        )

        findings = build_findings(payload, _make_query(query="什么时候看", mode="exact_fact"))

        statements = [finding["statement"] for finding in findings]
        assert statements == ["Chrome 浏览 该直播间（访问 11 次）"]


class TestPredicateBonus:
    """Predicate-aware scoring contributes to _score, which drives within-layer ordering."""

    def test_topic_predicate_bonus_breaks_equal_confidence_ties(self):
        payload = _make_payload(
            l2_relationships=[
                {
                    "triple_id": "uses",
                    "subject": "self",
                    "predicate": "USES",
                    "object": "topic:jazz",
                    "confidence": 0.7,
                },
                {
                    "triple_id": "likes",
                    "subject": "self",
                    "predicate": "LIKES",
                    "object": "topic:rock",
                    "confidence": 0.7,
                },
            ],
            trace={"l2_query_trace": {"semantic_frame": {"answer_kind": "topic"}}},
        )
        findings = build_findings(payload, _make_query(query="我喜欢什么音乐", mode="exact_fact"))
        assert [f["feedback_ref"] for f in findings] == ["relationship:likes", "relationship:uses"]

    @pytest.mark.parametrize(
        "query,expected",
        [
            ("我喜欢什么音乐", ["relationship:likes", "relationship:dislikes"]),
            ("我讨厌什么音乐", ["relationship:dislikes", "relationship:likes"]),
        ],
    )
    def test_query_polarity_changes_order_at_equal_confidence(self, query, expected):
        payload = _make_payload(
            l2_relationships=[
                {
                    "triple_id": "likes",
                    "subject": "self",
                    "predicate": "LIKES",
                    "object": "topic:pop",
                    "confidence": 0.75,
                },
                {
                    "triple_id": "dislikes",
                    "subject": "self",
                    "predicate": "DISLIKES",
                    "object": "topic:country",
                    "confidence": 0.75,
                },
            ]
        )
        findings = build_findings(payload, _make_query(query=query, mode="exact_fact"))
        assert [f["feedback_ref"] for f in findings] == expected


class TestPerLayerQuota:
    def test_l2_does_not_starve_l1_under_quota(self):
        payload = _make_payload(
            l1_events=[
                {
                    "event_id": f"e{i}",
                    "source": "chrome_history",
                    "author_type": "external",
                    "content_type": "observation",
                    "evidence_class": "external_observation",
                    "content": f"Chrome 浏览 咖啡馆 {i}",
                    "score": 0.3,
                    "timestamp": float(i),
                }
                for i in range(10)
            ],
            l2_assertions=[
                {
                    "subject": f"s{i}",
                    "predicate": "likes",
                    "claim": f"c{i}",
                    "confidence": 0.99,
                    "source_layer": "L2",
                }
                for i in range(20)
            ],
        )
        findings = build_findings(
            payload, _make_query(query="我喝过哪些咖啡馆", mode="cross_session")
        )
        layers = [f["source_layer"] for f in findings]
        # cross_session quota gives L1=12, L2=8 — under the OLD cross-layer nlargest
        # the 20 high-confidence (0.99) L2 assertions would crowd out the low-score
        # (0.3) L1 events; per-layer quota must keep L1's slots.
        assert layers.count("L1") >= 3
        assert layers.count("L2") >= 1

    def test_layer_internal_order_by_score(self):
        """Within a layer, items are sorted by _score (descending). For L1 events,
        _score is derived directly from the retrieval score, so high-score items
        come first."""
        payload = _make_payload(
            l1_events=[
                {
                    "event_id": "lo",
                    "source": "screenshot_timeline",
                    "author_type": "external",
                    "content_type": "observation",
                    "evidence_class": "external_observation",
                    "content": "低分事件",
                    "score": 0.2,
                    "timestamp": 1.0,
                },
                {
                    "event_id": "hi",
                    "source": "screenshot_timeline",
                    "author_type": "external",
                    "content_type": "observation",
                    "evidence_class": "external_observation",
                    "content": "高分事件",
                    "score": 0.9,
                    "timestamp": 2.0,
                },
            ],
        )
        findings = build_findings(payload, _make_query(query="事件", mode="event_stream"))
        l1 = [f for f in findings if f["source_layer"] == "L1"]
        assert l1[0]["statement"] == "高分事件"

    def test_unknown_mode_uses_default_layer_limits_without_dropping_available_layers(self):
        payload = _make_payload(
            l1_events=[
                {"event_id": f"e{i}", "content": f"Event {i}", "score": 0.8, "timestamp": float(i)}
                for i in range(10)
            ],
            l2_relationships=[
                {
                    "triple_id": f"r{i}",
                    "subject": "self",
                    "predicate": "USES",
                    "object": f"software:editor{i}",
                    "confidence": 0.8,
                }
                for i in range(8)
            ],
            l3_reflections=[
                {"summary_id": f"s{i}", "summary": f"Summary {i}", "confidence": 0.8} for i in range(5)
            ],
            l4_procedures=[
                {"skill_id": f"p{i}", "description": f"Procedure {i}", "success_rate": 0.8}
                for i in range(4)
            ],
        )
        findings = build_findings(payload, _make_query(mode="unregistered-mode"))
        assert [f["feedback_ref"] for f in findings] == [f"event:e{i}" for i in range(8)] + [
            f"relationship:r{i}" for i in range(6)
        ] + [f"reflection:s{i}" for i in range(3)] + [f"procedure:p{i}" for i in range(2)]
        assert payload.trace["layer_quota"] == {
            "mode": "unregistered-mode",
            "kept_per_layer": {"L1": 8, "L2": 6, "L3": 3, "L4": 2},
        }


class TestActivitySummaryMode:
    @pytest.mark.parametrize("include_summary", [True, False])
    def test_activity_summary_keeps_events_with_or_without_reflections(self, include_summary):
        payload = _make_payload(
            l1_events=[
                {"event_id": "visit", "content": "Browsed site X", "score": 0.5, "timestamp": 1.0}
            ],
            l3_reflections=(
                [
                    {
                        "summary_id": "weekly",
                        "summary": "This week you mainly browsed gaming sites",
                        "confidence": 0.8,
                    }
                ]
                if include_summary
                else []
            ),
        )
        findings = build_findings(payload, _make_query(mode="activity_summary"))
        assert [(f["kind"], f["feedback_ref"]) for f in findings] == [("event", "event:visit")] + (
            [("reflection", "reflection:weekly")] if include_summary else []
        )


class TestFindingTopic:
    """Each finding should carry a short, UI-friendly ``topic`` label."""

    def test_relationship_topic_extracts_object_label(self):
        payload = _make_payload(
            l2_relationships=[
                {
                    "subject": "self",
                    "predicate": "LIKES",
                    "object": "topic:hachi-mi",
                    "confidence": 0.9,
                    "first_observed_at": 1.0,
                }
            ],
        )
        findings = build_findings(payload, _make_query(mode="exact_fact"))
        assert findings[0]["topic"] == "hachi-mi"

    @pytest.mark.parametrize(
        "object_value,expected", [("person:keigo", ["keigo"]), ("", []), (None, [])]
    )
    def test_relationship_topics_require_a_complete_fact_before_display(self, object_value, expected):
        payload = _make_payload(
            l2_relationships=[
                {
                    "subject": "罗永浩",
                    "predicate": "FOLLOWS",
                    "object": object_value,
                    "confidence": 0.9,
                    "first_observed_at": 1.0,
                }
            ]
        )
        findings = build_findings(payload, _make_query(mode="exact_fact"))
        assert [f["topic"] for f in findings] == expected

    def test_assertion_topic_uses_value_after_colon(self):
        payload = _make_payload(
            l2_assertions=[
                {
                    "subject": "self",
                    "predicate": "favorite_band",
                    "claim": "陈奕迅",
                    "confidence_score": 0.7,
                    "created_at": 1.0,
                }
            ],
        )
        findings = build_findings(payload, _make_query(mode="exact_fact"))
        assert findings[0]["topic"] == "陈奕迅"

    def test_event_topic_preserves_meaningful_prefix_while_bounding_display_length(self):
        content = "锤子手机情怀加上罗永浩个人IP的混合体导致了直播带货成功"
        payload = _make_payload(l1_events=[{"content": content, "score": 0.8, "timestamp": 1.0}])
        findings = build_findings(payload, _make_query(mode="exact_fact"))
        assert len(findings) == 1
        assert findings[0]["topic"] == "锤子手机情怀加上罗永浩个人…"
        assert len(findings[0]["topic"]) == 14
        assert findings[0]["statement"] == content
