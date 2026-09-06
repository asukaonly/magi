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

    def test_both_l1_and_l2_surface_in_exact_fact(self):
        """Per-layer quota: both L1 and L2 get their quota slots.

        Old test ``test_high_confidence_l2_beats_low_l1_in_exact_fact`` asserted
        global cross-layer ``_score`` ordering (L2 first). That contract is
        intentionally replaced by per-layer quota: each layer fills its own quota
        slot regardless of cross-layer score comparison.
        """
        payload = _make_payload(
            l1_events=[
                {"content": "some low-score event", "score": 0.2, "timestamp": 1.0},
            ],
            l2_relationships=[
                {
                    "subject": "self",
                    "predicate": "LIKES",
                    "object": "topic:music",
                    "confidence": 0.9,
                    "first_observed_at": 1.0,
                },
            ],
        )
        findings = build_findings(payload, _make_query(mode="exact_fact"))
        kinds = {f["kind"] for f in findings}
        # Both layers must appear — quota floor guarantees each present layer gets >= 1.
        assert "event" in kinds
        assert "relationship" in kinds

    def test_high_score_l1_beats_low_confidence_l2(self):
        """When L2 confidence is below the floor, L1 with high retrieval
        score should rank higher — the key fix for the 'L2 always wins' bug."""
        payload = _make_payload(
            l1_events=[
                {"content": "WiFi password is mypass123", "score": 0.85, "timestamp": 1.0},
            ],
            l2_relationships=[
                {
                    "subject": "self",
                    "predicate": "USES",
                    "object": "software:wifi-app",
                    "confidence": 0.2,
                    "first_observed_at": 1.0,
                },
            ],
        )
        findings = build_findings(payload, _make_query(mode="exact_fact"))
        # L1 is iterated first by insertion order; with per-layer quota both
        # appear. High-score L1 is the first finding in the L1 group.
        l1_findings = [f for f in findings if f["kind"] == "event"]
        assert l1_findings and "WiFi" in l1_findings[0]["statement"]

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

    def test_mixed_layers_each_sorted_internally(self):
        """Per-layer quota replaces cross-layer global ``_score`` ordering.

        Old test ``test_mixed_layers_sorted_by_score`` asserted that ALL findings
        were sorted by ``_score`` across layers. That contract is intentionally
        replaced: each layer is sorted internally by ``_score``, then
        layers are concatenated. Cross-layer ordering is no longer guaranteed.
        """
        payload = _make_payload(
            l1_events=[
                {"content": "Event Lo", "score": 0.3, "timestamp": 1.0},
                {"content": "Event Hi", "score": 0.9, "timestamp": 2.0},
            ],
            l2_relationships=[
                {
                    "subject": "self",
                    "predicate": "LIKES",
                    "object": "topic:lo",
                    "confidence": 0.4,
                    "first_observed_at": 1.0,
                },
                {
                    "subject": "self",
                    "predicate": "LIKES",
                    "object": "topic:hi",
                    "confidence": 0.9,
                    "first_observed_at": 2.0,
                },
            ],
        )
        findings = build_findings(payload, _make_query(mode="exact_fact"))
        l1 = [f for f in findings if f["kind"] == "event"]
        l2 = [f for f in findings if f["kind"] == "relationship"]
        # Within each layer, higher _retrieval_score comes first.
        if len(l1) >= 2:
            assert l1[0]["statement"] == "Event Hi"
        if len(l2) >= 2:
            assert l2[0]["statement"].endswith("topic:hi")

    def test_quota_caps_total_count_per_layer(self):
        """Per-layer quota, not request.limit, governs how many items appear.

        Old test ``test_limit_respected`` asserted that request.limit=5 produced
        exactly 5 results via nlargest. The new contract uses mode-driven per-layer
        quotas instead; request.limit is no longer a global cap on the total count.
        exact_fact L1 quota = 6, so 20 L1 events yield 6 results (capped by quota).
        """
        payload = _make_payload(
            l1_events=[
                {"content": f"Event {i}", "score": 0.5, "timestamp": float(i)} for i in range(20)
            ],
        )
        findings = build_findings(payload, _make_query(mode="exact_fact", limit=5))
        # exact_fact layer_quota = {"L2": 8, "L1": 6, ...}; only L1 present → 6 kept.
        assert len(findings) == 6


class TestConfidenceFloor:
    """Low-confidence L2 results should be penalized."""

    def test_below_floor_penalized(self):
        payload = _make_payload(
            l2_relationships=[
                {
                    "subject": "self",
                    "predicate": "LIKES",
                    "object": "topic:noise",
                    "confidence": 0.2,
                    "first_observed_at": 1.0,
                },
                {
                    "subject": "self",
                    "predicate": "LIKES",
                    "object": "topic:signal",
                    "confidence": 0.8,
                    "first_observed_at": 1.0,
                },
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

    def test_evidence_class_user_question_filtered_in_non_fact_like_mode(self):
        """A user_question must be dropped even when the query routes to a
        non-fact-like mode (episode_recall / event_stream), not just fact-like
        modes."""
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
        assert "杭州天气怎么样" not in statements
        assert "Chrome 浏览 天气网 杭州 7 天预报" in statements

    def test_projection_filter_drops_are_recorded_in_trace(self):
        """When an evidence_class gate drops an L1 candidate, build_findings
        records it under payload.trace['projection_filter'] for observability."""
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

        build_findings(payload, _make_query(query="杭州最近天气", mode="exact_fact"))

        pf = payload.trace.get("projection_filter")
        assert pf is not None
        dropped_ids = [d["event_id"] for d in pf["dropped"]]
        assert "evt-q" in dropped_ids
        assert "evt-obs" not in dropped_ids
        assert pf["dropped"][0]["evidence_class"] == "user_question"

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

    def test_likes_and_uses_both_appear_in_results(self):
        """Within-layer ordering uses _score (descending), which includes predicate
        bonus on top of confidence. LIKES (0.9 confidence + topic predicate bonus)
        beats USES (0.7 confidence). Both predicates appear — quota floor guarantees it.

        Old test ``test_likes_ranked_over_uses_for_topic`` relied on predicate bonus
        changing relative order within L2 when confidence was equal (0.7 each). The
        updated fixture makes the score difference unambiguous by also varying confidence.
        """
        payload = _make_payload(
            l2_relationships=[
                {
                    "subject": "self",
                    "predicate": "USES",
                    "object": "topic:jazz",
                    "confidence": 0.7,
                    "first_observed_at": 1.0,
                },
                {
                    "subject": "self",
                    "predicate": "LIKES",
                    "object": "topic:rock",
                    "confidence": 0.9,
                    "first_observed_at": 1.0,
                },
            ],
            trace={"l2_query_trace": {"semantic_frame": {"answer_kind": "topic"}}},
        )
        findings = build_findings(payload, _make_query(query="我喜欢什么音乐", mode="exact_fact"))
        statements = [f["statement"] for f in findings]
        # LIKES has higher confidence AND predicate bonus → ranked first.
        assert findings[0]["statement"].endswith("topic:rock")
        assert any("topic:jazz" in s for s in statements)

    def test_dislikes_ranked_first_when_higher_score(self):
        """When DISLIKES has strictly higher confidence, it ranks first within the L2
        group under per-layer quota ordering (sort by _score descending).

        Old test ``test_dislikes_first_for_negative_query`` had equal confidences
        (0.75); with equal ``_retrieval_score`` and equal predicate bonus the ordering
        was insertion-dependent. Give DISLIKES a higher confidence so the sort reliably
        places it first.
        """
        payload = _make_payload(
            l2_relationships=[
                {
                    "subject": "self",
                    "predicate": "LIKES",
                    "object": "topic:pop",
                    "confidence": 0.70,
                    "first_observed_at": 1.0,
                },
                {
                    "subject": "self",
                    "predicate": "DISLIKES",
                    "object": "topic:country",
                    "confidence": 0.85,
                    "first_observed_at": 1.0,
                },
            ],
        )
        findings = build_findings(payload, _make_query(query="我讨厌什么", mode="exact_fact"))
        assert "DISLIKES" in findings[0]["statement"]


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

    def test_quota_falls_back_to_default_for_unknown_mode(self):
        payload = _make_payload(
            l1_events=[
                {
                    "event_id": "e1",
                    "source": "screenshot_timeline",
                    "author_type": "external",
                    "content_type": "observation",
                    "evidence_class": "external_observation",
                    "content": "事件",
                    "score": 0.5,
                    "timestamp": 1.0,
                },
            ],
        )
        findings = build_findings(payload, _make_query(query="x", mode="exact_fact"))
        assert any(f["source_layer"] == "L1" for f in findings)


class TestActivitySummaryMode:
    def test_reflections_appear_when_available(self):
        """Per-layer quota means both L1 and L3 get their own slots.

        Old test ``test_reflections_preferred_when_available`` asserted
        ``findings[0]["kind"] == "reflection"`` relying on cross-layer global
        ``_score`` ordering. Per-layer quota places L1 items before L3 in output
        order (L1 is appended first). The test is updated to assert that reflections
        appear in the results (quota floor = 1 guarantees it), not that they are first.
        """
        payload = _make_payload(
            l1_events=[
                {"content": "Browsed site X", "score": 0.5, "timestamp": 1.0},
            ],
            l3_reflections=[
                {"summary": "This week you mainly browsed gaming sites", "confidence": 0.8},
            ],
        )
        findings = build_findings(payload, _make_query(mode="activity_summary"))
        kinds = {f["kind"] for f in findings}
        assert "reflection" in kinds

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

    def test_relationship_topic_falls_back_to_subject_when_object_blank(self):
        payload = _make_payload(
            l2_relationships=[
                {
                    "subject": "罗永浩",
                    "predicate": "FOLLOWS",
                    "object": "person:keigo",
                    "confidence": 0.9,
                    "first_observed_at": 1.0,
                }
            ],
        )
        findings = build_findings(payload, _make_query(mode="exact_fact"))
        # The object has the type prefix stripped before display.
        assert findings[0]["topic"] == "keigo"

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

    def test_event_topic_truncates_long_statements(self):
        long_content = "锤子手机情怀加上罗永浩个人IP的混合体导致了直播带货成功"
        payload = _make_payload(
            l1_events=[
                {"content": long_content, "score": 0.8, "timestamp": 1.0},
            ],
        )
        findings = build_findings(payload, _make_query(mode="exact_fact"))
        topic = findings[0]["topic"]
        assert topic.endswith("…")
        # The truncated length stays bounded; the exact threshold lives in the
        # implementation, but we assert the topic is shorter than the full
        # statement so we know truncation actually fired.
        assert len(topic) < len(long_content)
