"""Tests for layer handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from magi.memory.hybrid_retrieval.handlers import (
    L1Handler,
    L2Handler,
    L3Handler,
    L4Handler,
    execute_plan,
)
from magi.memory.hybrid_retrieval.service_plan_execution import execute_layer_plan
from magi.memory.hybrid_retrieval.models import (
    L1Conditions,
    L2Conditions,
    L2SemanticFrame,
    L3Conditions,
    L4Conditions,
    LayerQueryPlan,
    SemanticConstraint,
    TimeRange,
)


# -----------------------------------------------------------------------
# L1Handler (mock-based, triple-path)
# -----------------------------------------------------------------------


class TestL1Handler:
    """Mock-based tests for L1Handler triple-path search.

    Full integration tests with real L1EventStore live in test_rrf_fusion.py.
    These tests verify interface behavior with mocked store methods.
    """

    @pytest.fixture
    def store(self):
        s = AsyncMock()
        s.db_path = ":memory:"
        s.bm25_search.return_value = [("e1", -1.0), ("e2", -0.5)]
        s.vector_search.return_value = []
        s.query_events.return_value = [
            {"event_id": "e1", "content": "hello world", "timestamp": 1000},
            {"event_id": "e2", "content": "world peace", "timestamp": 2000},
        ]
        s.resolve_event_entities.return_value = []
        s.find_events_by_entities.return_value = []
        s.filter_ids_by_user.return_value = []
        s.fetch_events.return_value = []
        return s

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, store):
        handler = L1Handler(store)
        conds = L1Conditions(content_query="")
        results = await handler.execute(conds)
        assert results == []
        store.bm25_search.assert_not_called()

    @pytest.mark.asyncio
    async def test_reranks_user_fact_above_verbose_assistant_guidance(self, store, monkeypatch):
        handler = L1Handler(store)
        conds = L1Conditions(content_query="What was the first issue I had with my new car after its first service?", limit=2)

        async def _bm25_path(_query, _limit, *, user_id=None, l1_retrieval_scopes=None):
            return ["assistant-generic", "user-fact"]

        async def _vector_path(_query, _limit, *, user_id=None, l1_retrieval_scopes=None):
            return []

        async def _keyword_path(_conditions, _limit, *, session_id=None, user_id=None, l1_retrieval_scopes=None):
            return ["assistant-generic", "user-fact"]

        async def _fetch_and_filter(*, event_ids, conditions, time_range, session_id, user_id, l1_retrieval_scopes=None):
            by_id = {
                "assistant-generic": {
                    "event_id": "assistant-generic",
                    "content": (
                        "That is great to hear. Here are ten general tips for protecting your car and "
                        "keeping it in good condition over the long term while thinking about detailing, "
                        "wax products, paint protection, interior cleaning, insurance shopping, and "
                        "other maintenance ideas that are not directly answering the issue question."
                    ),
                    "timestamp": 2000.0,
                    "author_type": "assistant",
                },
                "user-fact": {
                    "event_id": "user-fact",
                    "content": (
                        "I recently had an issue with my car's GPS system on 3/22, and I had to take "
                        "it back to the dealership to get it fixed after the first service."
                    ),
                    "timestamp": 1900.0,
                    "author_type": "user",
                },
            }
            return [by_id[event_id] for event_id in event_ids if event_id in by_id]

        monkeypatch.setattr(handler, "_bm25_path", _bm25_path)
        monkeypatch.setattr(handler, "_vector_path", _vector_path)
        monkeypatch.setattr(handler, "_keyword_path", _keyword_path)
        monkeypatch.setattr(handler, "_fetch_and_filter", _fetch_and_filter)

        results = await handler.execute(conds)

        assert [item["event_id"] for item in results] == ["user-fact", "assistant-generic"]

    @pytest.mark.asyncio
    async def test_attaches_retrieval_trace_metadata_to_results(self, store, monkeypatch):
        handler = L1Handler(store)
        conds = L1Conditions(content_query="Where did I mention the GPS issue?", limit=1)

        async def _bm25_path(_query, _limit, *, user_id=None, l1_retrieval_scopes=None):
            return ["user-fact"]

        async def _vector_path(_query, _limit, *, user_id=None, l1_retrieval_scopes=None):
            return []

        async def _keyword_path(_conditions, _limit, *, session_id=None, user_id=None, l1_retrieval_scopes=None):
            return ["user-fact"]

        async def _fetch_and_filter(*, event_ids, conditions, time_range, session_id, user_id, l1_retrieval_scopes=None):
            return [
                {
                    "event_id": "user-fact",
                    "content": "I had an issue with my car's GPS system after the first service.",
                    "timestamp": 1900.0,
                    "author_type": "user",
                }
            ]

        monkeypatch.setattr(handler, "_bm25_path", _bm25_path)
        monkeypatch.setattr(handler, "_vector_path", _vector_path)
        monkeypatch.setattr(handler, "_keyword_path", _keyword_path)
        monkeypatch.setattr(handler, "_fetch_and_filter", _fetch_and_filter)

        results = await handler.execute(conds)

        assert "retrieval_trace" in results[0]
        assert results[0]["retrieval_trace"]["base_rrf_score"] > 0
        assert "role_bias" in results[0]["retrieval_trace"]

    @pytest.mark.asyncio
    async def test_prefers_titled_user_events_over_generic_assistant_comparison_guidance(self, store, monkeypatch):
        handler = L1Handler(store)
        conds = L1Conditions(
            content_query=(
                "Which event did I attend first, the 'Effective Time Management' workshop "
                "or the 'Data Analysis using Python' webinar?"
            ),
            limit=3,
        )

        async def _bm25_path(_query, _limit, *, user_id=None, l1_retrieval_scopes=None):
            return ["assistant-generic", "user-workshop", "user-webinar"]

        async def _vector_path(_query, _limit, *, user_id=None, l1_retrieval_scopes=None):
            return []

        async def _keyword_path(_conditions, _limit, *, session_id=None, user_id=None, l1_retrieval_scopes=None):
            return ["assistant-generic", "user-workshop", "user-webinar"]

        async def _fetch_and_filter(*, event_ids, conditions, time_range, session_id, user_id, l1_retrieval_scopes=None):
            by_id = {
                "assistant-generic": {
                    "event_id": "assistant-generic",
                    "content": (
                        "To figure out which event came first, compare the 'Effective Time Management' "
                        "workshop and the 'Data Analysis using Python' webinar by checking your notes, "
                        "calendar, and any reminders about when you attended each event."
                    ),
                    "timestamp": 3000.0,
                    "author_type": "assistant",
                },
                "user-workshop": {
                    "event_id": "user-workshop",
                    "content": (
                        "I attended the 'Effective Time Management' workshop at the community center "
                        "last Saturday."
                    ),
                    "timestamp": 2000.0,
                    "author_type": "user",
                },
                "user-webinar": {
                    "event_id": "user-webinar",
                    "content": (
                        "I participated in the 'Data Analysis using Python' webinar two months ago."
                    ),
                    "timestamp": 1000.0,
                    "author_type": "user",
                },
            }
            return [by_id[event_id] for event_id in event_ids if event_id in by_id]

        monkeypatch.setattr(handler, "_bm25_path", _bm25_path)
        monkeypatch.setattr(handler, "_vector_path", _vector_path)
        monkeypatch.setattr(handler, "_keyword_path", _keyword_path)
        monkeypatch.setattr(handler, "_fetch_and_filter", _fetch_and_filter)

        results = await handler.execute(conds)

        ranked_ids = [item["event_id"] for item in results]
        assert set(ranked_ids) == {"assistant-generic", "user-workshop", "user-webinar"}
        # user-workshop has strong quoted-phrase match + user role bias → ranked first
        assert ranked_ids[0] == "user-workshop"

    @pytest.mark.asyncio
    async def test_records_quoted_title_hits_in_retrieval_trace(self, store, monkeypatch):
        handler = L1Handler(store)
        conds = L1Conditions(
            content_query="Did I attend the 'Effective Time Management' workshop?",
            limit=1,
        )

        async def _bm25_path(_query, _limit, *, user_id=None, l1_retrieval_scopes=None):
            return ["user-workshop"]

        async def _vector_path(_query, _limit, *, user_id=None, l1_retrieval_scopes=None):
            return []

        async def _keyword_path(_conditions, _limit, *, session_id=None, user_id=None, l1_retrieval_scopes=None):
            return ["user-workshop"]

        async def _fetch_and_filter(*, event_ids, conditions, time_range, session_id, user_id, l1_retrieval_scopes=None):
            return [
                {
                    "event_id": "user-workshop",
                    "content": "I attended the 'Effective Time Management' workshop last Saturday.",
                    "timestamp": 1000.0,
                    "author_type": "user",
                }
            ]

        monkeypatch.setattr(handler, "_bm25_path", _bm25_path)
        monkeypatch.setattr(handler, "_vector_path", _vector_path)
        monkeypatch.setattr(handler, "_keyword_path", _keyword_path)
        monkeypatch.setattr(handler, "_fetch_and_filter", _fetch_and_filter)

        results = await handler.execute(conds)

        assert results[0]["retrieval_trace"]["quoted_phrase_hits"] == ["effective time management"]

    @pytest.mark.asyncio
    async def test_keyword_path_recovers_multiple_quoted_candidates_for_comparison_queries(self, store, monkeypatch):
        handler = L1Handler(store)
        conds = L1Conditions(
            content_query=(
                "Which event did I attend first, the 'Effective Time Management' workshop "
                "or the 'Data Analysis using Python' webinar?"
            ),
            limit=3,
        )
        store.query_events.return_value = [
            {
                "event_id": "user-workshop",
                "content": "I attended the 'Effective Time Management' workshop at the community center.",
                "timestamp": 2000.0,
                "author_type": "user",
            },
            {
                "event_id": "user-webinar",
                "content": "I participated in the 'Data Analysis using Python' webinar two months ago.",
                "timestamp": 1000.0,
                "author_type": "user",
            },
            {
                "event_id": "user-unrelated",
                "content": (
                    "I think I'll try out both Tableau and Power BI's free trials to get a feel for "
                    "their interfaces and customization options."
                ),
                "timestamp": 3000.0,
                "author_type": "user",
            },
        ]

        async def _bm25_path(_query, _limit, *, user_id=None, l1_retrieval_scopes=None):
            return []

        async def _vector_path(_query, _limit, *, user_id=None, l1_retrieval_scopes=None):
            return []

        async def _fetch_and_filter(*, event_ids, conditions, time_range, session_id, user_id, l1_retrieval_scopes=None):
            by_id = {event["event_id"]: event for event in store.query_events.return_value}
            return [by_id[event_id] for event_id in event_ids if event_id in by_id]

        monkeypatch.setattr(handler, "_bm25_path", _bm25_path)
        monkeypatch.setattr(handler, "_vector_path", _vector_path)
        monkeypatch.setattr(handler, "_fetch_and_filter", _fetch_and_filter)

        results = await handler.execute(conds)

        ranked_ids = [item["event_id"] for item in results]
        assert set(ranked_ids) == {"user-workshop", "user-webinar"}
        assert "user-unrelated" not in ranked_ids


# -----------------------------------------------------------------------
# L2Handler (grounded hybrid retrieval pipeline)
# -----------------------------------------------------------------------


def _make_l2_store(**overrides):
    """Create a base store mock with all methods the L2 pipeline calls."""
    s = AsyncMock()
    s.batch_get_tom_snapshots.return_value = overrides.get("snapshots", [])
    s.batch_get_relationships.return_value = overrides.get("batch_rels", {})
    s.batch_list_tom_assertions.return_value = overrides.get("batch_assertions", {})
    s.list_tom_assertions.return_value = overrides.get("assertions", [])
    s.get_relationships.return_value = overrides.get("rels", [])
    s.search_edges_by_embedding.return_value = overrides.get("edge_vectors", [])
    s.list_episodes.return_value = overrides.get("episodes", [])
    s.search_episodes_fts.return_value = overrides.get("fts_episodes", [])
    return s


class TestL2Handler:
    @pytest.fixture
    def store(self):
        edge = {
            "triple_id": "t1",
            "subject_id": "alice",
            "object_id": "bob",
            "predicate": "KNOWS",
            "status": "active",
        }
        return _make_l2_store(
            snapshots=[{"entity_id": "alice", "name": "Alice"}],
            rels=[edge],
            # Subject-grounded recall fetches via batch_get_relationships.
            batch_rels={"person:alice": [edge]},
        )

    @pytest.mark.asyncio
    async def test_entity_cards(self, store):
        handler = L2Handler(store)
        conds = L2Conditions(
            entities=["person:alice"],
            include_tom_snapshot=True,
            include_relationships=False,
        )
        results = await handler.execute(conds)
        assert len(results["entity_cards"]) == 1
        assert results["entity_cards"][0]["entity_id"] == "alice"

    @pytest.mark.asyncio
    async def test_relationships(self, store):
        handler = L2Handler(store)
        # RFC #65: with no predicate AND no object-type constraint the
        # structured channel deliberately abstains (a bare subject dump is
        # topically unfiltered), so grounded recall must carry a predicate.
        conds = L2Conditions(
            entities=["person:alice"],
            predicates=["KNOWS"],
            include_tom_snapshot=False,
            include_relationships=True,
        )
        results = await handler.execute(conds)
        assert len(results["relationships"]) >= 1

    @pytest.mark.asyncio
    async def test_both_snapshot_and_relationships(self, store):
        handler = L2Handler(store)
        conds = L2Conditions(
            entities=["person:alice"],
            predicates=["KNOWS"],
            include_tom_snapshot=True,
            include_relationships=True,
        )
        results = await handler.execute(conds)
        assert len(results["entity_cards"]) == 1
        assert len(results["relationships"]) >= 1

    @pytest.mark.asyncio
    async def test_no_entities_returns_empty_entity_cards(self, store):
        handler = L2Handler(store)
        conds = L2Conditions(
            entities=None,
            include_tom_snapshot=True,
            include_relationships=True,
        )
        results = await handler.execute(conds)
        assert len(results["entity_cards"]) == 0
        assert "grounding_plan" in results["trace"]
        assert results["trace"]["grounding_plan"]["subject_count"] == 0

    @pytest.mark.asyncio
    async def test_default_l2_query_does_not_return_episode_substrate(self):
        store = _make_l2_store(
            episodes=[
                {
                    "episode_id": "ep-candidate",
                    "status": "candidate",
                    "time_start": 100.0,
                    "time_end": 200.0,
                }
            ],
        )
        handler = L2Handler(store)

        results = await handler.execute(
            L2Conditions(
                content_query="我听过什么歌",
                include_tom_snapshot=False,
                include_relationships=False,
                include_assertions=False,
            )
        )

        assert results["episodes"] == []
        store.list_episodes.assert_not_awaited()

    def test_filter_by_time_range_uses_observed_at_schema_fields(self):
        items = [
            {"triple_id": "in", "first_observed_at": 1661990400.0, "last_observed_at": 1662114600.0},
            {"triple_id": "out", "first_observed_at": 1664582401.0, "last_observed_at": 1664582401.0},
        ]

        filtered = L2Handler._filter_by_time_range(
            items,
            TimeRange(start=1661990400.0, end=1664582399.0),
            timestamp_keys=("last_observed_at", "first_observed_at"),
        )

        assert [item["triple_id"] for item in filtered] == ["in"]

    @pytest.mark.asyncio
    async def test_self_preference_without_entities_binds_user_as_subject(self):
        store = _make_l2_store(
            snapshots=[{"entity_id": "user:u1", "entity_type": "user"}],
            batch_rels={"user:u1": []},
            batch_assertions={"user:u1": []},
        )

        handler = L2Handler(store)
        conds = L2Conditions(
            content_query="我喜欢什么天气",
            subject_hint="self",
            predicate_family="preference",
            include_tom_snapshot=False,
            include_relationships=True,
            include_assertions=True,
        )

        results = await handler.execute(conds, user_id="u1")

        assert store.batch_get_relationships.called
        assert results["trace"]["grounding_plan"]["subject_scope"] == "self"

    @pytest.mark.asyncio
    async def test_self_preference_binds_user_as_subject_with_semantic_frame(self):
        store = _make_l2_store(
            snapshots=[{"entity_id": "user:u1", "entity_type": "user"}],
            batch_rels={
                "user:u1": [
                    {
                        "triple_id": "pref-1",
                        "subject_id": "user:u1",
                        "predicate": "LIKES",
                        "object_id": "weather_state:sunny",
                        "status": "active",
                    }
                ]
            },
            batch_assertions={"user:u1": []},
        )
        entity_catalog = AsyncMock()
        entity_catalog.resolve_query_entities.return_value = [
            {
                "entity_id": "weather_state:weather-state",
                "entity_type": "weather_state",
                "canonical_name": "Weather",
                "match_source": "alias",
            }
        ]

        handler = L2Handler(store, entity_catalog=entity_catalog)
        conds = L2Conditions(
            content_query="我喜欢什么天气",
            entities=["天气"],
            subject_hint="self",
            predicate_family="preference",
            include_tom_snapshot=True,
            include_relationships=True,
            include_assertions=True,
            semantic_frame=L2SemanticFrame(
                query_family="affinity",
                subject_scope="self",
                answer_kind="unknown",
                answer_unit="mixed",
            ),
        )

        results = await handler.execute(conds, user_id="u1")

        assert results["trace"]["grounding_plan"]["subject_scope"] == "self"
        assert results["trace"]["grounding_plan"]["predicate_family"] == "preference"
        batch_calls = store.batch_get_relationships.call_args_list
        subject_ids_used = set()
        for call in batch_calls:
            for eid in call.kwargs.get("entity_ids", []):
                subject_ids_used.add(eid)
        assert "user:u1" in subject_ids_used

    @pytest.mark.asyncio
    async def test_explicit_subject_preference_does_not_bind_self(self):
        store = _make_l2_store(
            rels=[
                {
                    "triple_id": "pref-1",
                    "subject_id": "person:xiaowang",
                    "predicate": "LIKES",
                    "object_id": "food:ramen",
                    "status": "active",
                }
            ],
        )
        entity_catalog = AsyncMock()
        entity_catalog.resolve_query_entities.return_value = [
            {
                "entity_id": "person:xiaowang",
                "entity_type": "person",
                "canonical_name": "小王",
                "match_source": "alias",
            }
        ]

        handler = L2Handler(store, entity_catalog=entity_catalog)
        conds = L2Conditions(
            content_query="我的朋友小王喜欢什么",
            entities=["小王"],
            subject_hint="explicit",
            predicate_family="preference",
            include_tom_snapshot=False,
            include_relationships=True,
            include_assertions=False,
        )

        results = await handler.execute(conds, user_id="u1")

        # user:u1 should NOT be bound as subject via batch_get_relationships
        for call in store.batch_get_relationships.call_args_list:
            entity_ids = call.kwargs.get("entity_ids", [])
            assert "user:u1" not in entity_ids

    @pytest.mark.asyncio
    async def test_self_preference_grounds_user_as_subject(self):
        store = _make_l2_store(
            snapshots=[{"entity_id": "user:local_user", "entity_type": "user"}],
            batch_rels={"user:local_user": []},
            batch_assertions={"user:local_user": []},
        )
        entity_catalog = AsyncMock()
        entity_catalog.resolve_query_entities.return_value = [
            {
                "entity_id": "weather_state:weather-state",
                "entity_type": "weather_state",
                "canonical_name": "Weather",
                "match_source": "alias",
            },
            {
                "entity_id": "person:219ba6d80c59",
                "entity_type": "person",
                "canonical_name": "Someone",
                "match_source": "context",
            },
        ]

        handler = L2Handler(store, entity_catalog=entity_catalog)
        conds = L2Conditions(
            content_query="你觉得我喜欢什么天气",
            entities=None,
            subject_hint="self",
            predicate_family="preference",
            include_tom_snapshot=True,
            include_relationships=True,
            include_assertions=True,
            semantic_frame=L2SemanticFrame(
                query_family="affinity",
                subject_scope="self",
                answer_kind="unknown",
                answer_unit="mixed",
            ),
        )

        results = await handler.execute(conds, user_id="local_user")

        trace = results["trace"]["grounding_plan"]
        assert trace["subject_scope"] == "self"
        batch_calls = store.batch_get_relationships.call_args_list
        subject_ids_used = set()
        for call in batch_calls:
            for eid in call.kwargs.get("entity_ids", []):
                subject_ids_used.add(eid)
        assert "user:local_user" in subject_ids_used

    @pytest.mark.asyncio
    async def test_self_activity_uses_user_as_subject(self):
        store = _make_l2_store(
            batch_rels={
                "user:local_user": [
                    {
                        "triple_id": "uses-1",
                        "subject_id": "user:local_user",
                        "predicate": "USES",
                        "object_id": "app:x",
                        "status": "active",
                    }
                ],
            },
            batch_assertions={"user:local_user": []},
        )
        entity_catalog = AsyncMock()
        entity_catalog.resolve_query_entities.return_value = [
            {
                "entity_id": "activity:drinking-water",
                "entity_type": "activity",
                "canonical_name": "Drinking water",
                "match_source": "vector",
            }
        ]

        handler = L2Handler(store, entity_catalog=entity_catalog)
        conds = L2Conditions(
            content_query="我最近3天的活动",
            subject_hint="self",
            predicate_family="activity",
            include_tom_snapshot=False,
            include_relationships=True,
            include_assertions=True,
            semantic_frame=L2SemanticFrame(
                query_family="activity",
                subject_scope="self",
                answer_kind="unknown",
                answer_unit="mixed",
            ),
        )

        results = await handler.execute(conds, user_id="local_user")

        batch_calls = store.batch_get_relationships.call_args_list
        assert any("user:local_user" in call.kwargs.get("entity_ids", []) for call in batch_calls)
        assert results["trace"]["grounding_plan"]["subject_scope"] == "self"
        assert len(results["relationships"]) >= 1

    @pytest.mark.asyncio
    async def test_creator_affinity_returns_follow_edges_via_topology(self):
        def _batch_rels(**kwargs):
            entity_ids = kwargs.get("entity_ids", [])
            predicates = kwargs.get("predicates") or []
            object_types = kwargs.get("object_types") or []
            result = {}
            for eid in entity_ids:
                if eid == "user:u1" and "presence" in object_types:
                    result[eid] = [
                        {
                            "triple_id": "follow-1",
                            "subject_id": "user:u1",
                            "subject_type": "user",
                            "predicate": "FOLLOWS",
                            "object_id": "presence:bilibili:creator_1",
                            "object_type": "presence",
                            "status": "active",
                        }
                    ]
                elif eid == "user:u1":
                    result[eid] = []
                elif eid == "presence:bilibili:creator_1" and "PRESENCE_OF" in predicates:
                    result[eid] = [
                        {
                            "triple_id": "presence-of-1",
                            "subject_id": "presence:bilibili:creator_1",
                            "subject_type": "presence",
                            "predicate": "PRESENCE_OF",
                            "object_id": "person:永雏塔菲",
                            "object_type": "person",
                            "status": "active",
                        }
                    ]
                else:
                    result[eid] = []
            return result

        store = _make_l2_store()
        store.batch_get_relationships.side_effect = _batch_rels

        handler = L2Handler(store, entity_catalog=AsyncMock())
        conds = L2Conditions(
            content_query="我B站喜欢哪些up主",
            subject_hint="self",
            predicate_family="preference",
            include_tom_snapshot=False,
            include_relationships=True,
            include_assertions=False,
            semantic_frame=L2SemanticFrame(
                query_family="affinity",
                subject_scope="self",
                answer_kind="creator",
                answer_unit="identity",
                constraints=[
                    SemanticConstraint(
                        scope="target",
                        facet="platform",
                        raw_value="B站",
                        resolved_entity_id="software:bilibili",
                    )
                ],
            ),
        )

        results = await handler.execute(conds, user_id="u1")

        assert results["trace"]["grounding_plan"]["answer_kind"] == "creator"
        follow_edges = [r for r in results["relationships"] if r["predicate"] == "FOLLOWS"]
        assert len(follow_edges) >= 1

    @pytest.mark.asyncio
    async def test_topic_affinity_queries_topic_relationships(self):
        store = _make_l2_store(
            batch_rels={
                "user:u1": [
                    {
                        "triple_id": "topic-1",
                        "subject_id": "user:u1",
                        "subject_type": "user",
                        "predicate": "INTERESTED_IN",
                        "object_id": "topic:anime",
                        "object_type": "topic",
                        "status": "active",
                    }
                ]
            },
        )

        handler = L2Handler(store, entity_catalog=AsyncMock())
        conds = L2Conditions(
            content_query="我喜欢什么题材",
            subject_hint="self",
            predicate_family="preference",
            include_tom_snapshot=False,
            include_relationships=True,
            include_assertions=False,
            semantic_frame=L2SemanticFrame(
                query_family="affinity",
                subject_scope="self",
                answer_kind="topic",
                answer_unit="topic",
            ),
        )

        results = await handler.execute(conds, user_id="u1")

        assert results["trace"]["grounding_plan"]["answer_kind"] == "topic"
        interested = [r for r in results["relationships"] if r["predicate"] == "INTERESTED_IN"]
        assert len(interested) >= 1

    @pytest.mark.asyncio
    async def test_place_affinity_uses_location_topology(self):
        store = _make_l2_store(batch_rels={"user:u1": []})
        store.get_relationships.side_effect = [
            # Topology: LOCATED_IN hangzhou
            [
                {
                    "triple_id": "topology-2",
                    "subject_id": "place:manner-xihu",
                    "subject_type": "place",
                    "predicate": "LOCATED_IN",
                    "object_id": "place:hangzhou",
                    "object_type": "place",
                    "status": "active",
                }
            ],
            # Evidence: user visited manner-xihu
            [
                {
                    "triple_id": "visit-1",
                    "subject_id": "user:u1",
                    "subject_type": "user",
                    "predicate": "VISITED",
                    "object_id": "place:manner-xihu",
                    "object_type": "place",
                    "status": "active",
                }
            ],
        ]

        handler = L2Handler(store, entity_catalog=AsyncMock())
        conds = L2Conditions(
            content_query="我在杭州喜欢去哪些咖啡馆",
            subject_hint="self",
            predicate_family="preference",
            include_tom_snapshot=False,
            include_relationships=True,
            include_assertions=False,
            semantic_frame=L2SemanticFrame(
                query_family="affinity",
                subject_scope="self",
                answer_kind="place",
                answer_unit="place",
                constraints=[
                    SemanticConstraint(
                        scope="target",
                        facet="located_in",
                        raw_value="杭州",
                        resolved_entity_id="place:hangzhou",
                    ),
                ],
            ),
        )

        results = await handler.execute(conds, user_id="u1")

        assert results["trace"]["grounding_plan"]["answer_kind"] == "place"
        visited = [r for r in results["relationships"] if r["predicate"] == "VISITED"]
        assert len(visited) >= 1

    @pytest.mark.asyncio
    async def test_software_affinity_queries_software_relationships(self):
        edge = {
            "triple_id": "software-1",
            "subject_id": "user:u1",
            "subject_type": "user",
            "predicate": "USES",
            "object_id": "software:bilibili",
            "object_type": "software",
            "status": "active",
        }
        store = _make_l2_store(
            batch_rels={"user:u1": [edge]},
            rels=[edge],
        )
        entity_catalog = AsyncMock()
        entity_catalog.resolve_query_entities.return_value = [
            {
                "entity_id": "software:bilibili",
                "entity_type": "software",
                "canonical_name": "Bilibili",
                "match_source": "alias",
            }
        ]

        handler = L2Handler(store, entity_catalog=entity_catalog)
        conds = L2Conditions(
            content_query="我喜欢B站吗",
            entities=["B站"],
            subject_hint="self",
            predicate_family="preference",
            include_tom_snapshot=False,
            include_relationships=True,
            include_assertions=False,
            semantic_frame=L2SemanticFrame(
                query_family="affinity",
                subject_scope="self",
                answer_kind="software",
                answer_unit="mixed",
                entity_mentions=["B站"],
            ),
        )

        results = await handler.execute(conds, user_id="u1")

        assert results["trace"]["grounding_plan"]["answer_kind"] == "software"
        uses_edges = [r for r in results["relationships"] if r["predicate"] == "USES"]
        assert len(uses_edges) >= 1


# -----------------------------------------------------------------------
# L3Handler
# -----------------------------------------------------------------------


class TestL3Handler:
    @pytest.fixture
    def store(self):
        s = AsyncMock()
        s.db_path = ":memory:"
        s.bm25_search.return_value = [("s1", -1.0)]
        s.vector_search.return_value = [{"summary_id": "s1", "content": "weekly summary"}]
        s.keyword_search.return_value = []
        s.fetch_by_ids.return_value = [{"summary_id": "s1", "content": "weekly summary"}]
        return s

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, store):
        handler = L3Handler(store)
        conds = L3Conditions(content_query="")
        results = await handler.execute(conds)
        assert results == []
        store.bm25_search.assert_not_called()

    @pytest.mark.asyncio
    async def test_reranks_specific_summary_above_generic_summary(self, store, monkeypatch):
        handler = L3Handler(store)
        conds = L3Conditions(content_query="career gps issue", limit=2)

        async def _bm25_path(_query, _summary_type, _summary_category, _limit):
            return ["summary-generic", "summary-specific"]

        async def _vector_path(_query, _summary_type, _summary_category, _limit):
            return []

        async def _keyword_path(_query, _summary_type, _summary_category, _limit):
            return ["summary-generic", "summary-specific"]

        async def _fetch_by_ids(_summary_ids, _summary_type, _summary_category):
            return [
                {
                    "summary_id": "summary-generic",
                    "content": "general weekly summary with broad advice",
                    "updated_at": 2000.0,
                },
                {
                    "summary_id": "summary-specific",
                    "content": "career gps issue summary with concrete recall details",
                    "updated_at": 1900.0,
                    "matched_chunks": [{"chunk_id": "summary-specific::chunk-0", "distance": 0.03}],
                },
            ]

        monkeypatch.setattr(handler, "_bm25_path", _bm25_path)
        monkeypatch.setattr(handler, "_vector_path", _vector_path)
        monkeypatch.setattr(handler, "_keyword_path", _keyword_path)
        monkeypatch.setattr(handler, "_fetch_by_ids", _fetch_by_ids)

        results = await handler.execute(conds)

        assert [item["summary_id"] for item in results] == ["summary-specific", "summary-generic"]
        assert "retrieval_trace" in results[0]


# -----------------------------------------------------------------------
# L4Handler
# -----------------------------------------------------------------------


class TestL4Handler:
    @pytest.fixture
    def store(self):
        s = AsyncMock()
        s.db_path = ":memory:"
        s.bm25_search.return_value = [("p1", -1.0)]
        s.keyword_search.return_value = []
        s.fetch_by_ids.return_value = [{"skill_id": "p1", "content": "deploy strategy"}]
        return s

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, store):
        handler = L4Handler(store)
        conds = L4Conditions(content_query="")
        results = await handler.execute(conds)
        assert results == []
        store.bm25_search.assert_not_called()
        results = await handler.execute(conds)
        assert results == []

    @pytest.mark.asyncio
    async def test_reranks_specific_skill_above_generic_skill(self, store, monkeypatch):
        handler = L4Handler(store)
        conds = L4Conditions(content_query="browser recovery workflow", limit=2)

        async def _bm25_path(_query, _limit):
            return ["skill-generic", "skill-specific"]

        async def _keyword_path(_query, _limit):
            return ["skill-generic", "skill-specific"]

        async def _fetch_by_ids(_skill_ids):
            return [
                {
                    "skill_id": "skill-generic",
                    "skill_name": "workflow",
                    "skill_category": "workflow",
                    "optimized_prompt": "general workflow helper",
                    "updated_at": 2000.0,
                },
                {
                    "skill_id": "skill-specific",
                    "skill_name": "browser-workflow",
                    "skill_category": "workflow",
                    "optimized_prompt": "browser recovery workflow with concrete recovery checklist",
                    "updated_at": 1900.0,
                    "matched_chunks": [{"chunk_id": "skill-specific::chunk-0", "distance": 0.02}],
                },
            ]

        monkeypatch.setattr(handler, "_bm25_path", _bm25_path)
        monkeypatch.setattr(handler, "_keyword_path", _keyword_path)
        monkeypatch.setattr(handler, "_fetch_by_ids", _fetch_by_ids)

        results = await handler.execute(conds)

        assert [item["skill_id"] for item in results] == ["skill-specific", "skill-generic"]
        assert "retrieval_trace" in results[0]


# -----------------------------------------------------------------------
# execute_plan dispatch
# -----------------------------------------------------------------------


class TestExecutePlan:
    @pytest.mark.asyncio
    async def test_dispatch_l1(self):
        l1 = AsyncMock(spec=L1Handler)
        l1.execute.return_value = [{"id": "e1"}]
        plan = LayerQueryPlan(layer="L1", conditions=L1Conditions(content_query="x"))
        result = await execute_plan(plan, l1=l1)
        assert result == [{"id": "e1"}]

    @pytest.mark.asyncio
    async def test_dispatch_l2(self):
        l2 = AsyncMock(spec=L2Handler)
        l2.execute.return_value = {"entity_cards": [], "relationships": []}
        plan = LayerQueryPlan(layer="L2", conditions=L2Conditions())
        result = await execute_plan(plan, l2=l2)
        assert "entity_cards" in result

    @pytest.mark.asyncio
    async def test_dispatch_l3(self):
        l3 = AsyncMock(spec=L3Handler)
        l3.execute.return_value = [{"id": "s1"}]
        plan = LayerQueryPlan(layer="L3", conditions=L3Conditions(content_query="x"))
        result = await execute_plan(plan, l3=l3)
        assert result == [{"id": "s1"}]

    @pytest.mark.asyncio
    async def test_dispatch_l4(self):
        l4 = AsyncMock(spec=L4Handler)
        l4.execute.return_value = [{"id": "p1"}]
        plan = LayerQueryPlan(layer="L4", conditions=L4Conditions(content_query="x"))
        result = await execute_plan(plan, l4=l4)
        assert result == [{"id": "p1"}]

    @pytest.mark.asyncio
    async def test_missing_handler_returns_empty(self):
        plan = LayerQueryPlan(layer="L1", conditions=L1Conditions(content_query="x"))
        result = await execute_plan(plan)  # no handlers
        assert result == []

    @pytest.mark.asyncio
    async def test_missing_l2_handler_returns_empty_dict(self):
        plan = LayerQueryPlan(layer="L2", conditions=L2Conditions())
        result = await execute_plan(plan)
        assert result == {"entity_cards": [], "relationships": []}


class TestExecuteLayerPlan:
    @pytest.mark.asyncio
    async def test_dispatches_to_layer_handler(self):
        l1 = AsyncMock(spec=L1Handler)
        l1.execute.return_value = [{"id": "e1"}]
        plan = LayerQueryPlan(layer="L1", conditions=L1Conditions(content_query="x"))

        result = await execute_layer_plan(plan, l1=l1)

        assert result == [{"id": "e1"}]


class TestL2HandlerEdgeVectorSupplement:
    """Test edge vector search integration in L2 pipeline."""

    @pytest.mark.asyncio
    async def test_adds_novel_edges_from_vector_search(self):
        structured_edge = {"triple_id": "t1", "predicate": "LIKES", "subject_id": "user:u1", "status": "active"}
        store = _make_l2_store(
            rels=[structured_edge],
            batch_rels={"user:u1": [structured_edge]},
            edge_vectors=[
                {"triple_id": "t2", "predicate": "LIKES", "vector_distance": 0.1, "status": "active"},
            ],
        )

        embedding_service = AsyncMock()
        embedding_service.embed_text.return_value = AsyncMock(vector=[0.1] * 8)
        edge_index = AsyncMock()

        handler = L2Handler(
            store,
            embedding_service=embedding_service,
            edge_vector_index=edge_index,
        )
        conds = L2Conditions(
            entities=["user:u1"],
            # RFC #65: structured channel abstains without a predicate.
            predicates=["LIKES"],
            include_relationships=True,
            content_query="what food does user like",
        )
        results = await handler.execute(conds)
        assert len(results["relationships"]) == 2
        assert results["trace"]["channel_counts"]["knowledge_edges"] == 2

    @pytest.mark.asyncio
    async def test_skips_when_no_embedding_service(self):
        store = _make_l2_store(
            rels=[
                {"triple_id": "t1", "predicate": "LIKES", "subject_id": "user:u1", "status": "active"}
            ],
        )

        handler = L2Handler(store)
        conds = L2Conditions(
            entities=["user:u1"],
            include_relationships=True,
            content_query="what food does user like",
        )
        results = await handler.execute(conds)
        store.search_edges_by_embedding.assert_not_called()

    @pytest.mark.asyncio
    async def test_deduplicates_existing_edges(self):
        store = _make_l2_store(
            rels=[
                {"triple_id": "existing-1", "predicate": "LIKES", "subject_id": "user:u1", "status": "active"}
            ],
            edge_vectors=[
                {"triple_id": "existing-1", "predicate": "LIKES", "vector_distance": 0.05, "status": "active"},
            ],
        )

        embedding_service = AsyncMock()
        embedding_service.embed_text.return_value = AsyncMock(vector=[0.1] * 8)
        edge_index = AsyncMock()

        handler = L2Handler(
            store,
            embedding_service=embedding_service,
            edge_vector_index=edge_index,
        )
        conds = L2Conditions(
            entities=["user:u1"],
            include_relationships=True,
            content_query="food preference",
        )
        results = await handler.execute(conds)
        assert len(results["relationships"]) == 1

    @pytest.mark.asyncio
    async def test_predicate_matching_edges_rank_higher(self):
        """Edges whose predicate matches the query's predicate family score higher in fusion."""
        store = _make_l2_store(
            edge_vectors=[
                {"triple_id": "t-unrelated", "predicate": "CREATED_BY", "vector_distance": 0.10, "status": "active"},
                {"triple_id": "t-affinity", "predicate": "LIKES", "vector_distance": 0.12, "status": "active"},
            ],
        )

        embedding_service = AsyncMock()
        embedding_service.embed_text.return_value = AsyncMock(vector=[0.1] * 8)
        edge_index = AsyncMock()

        handler = L2Handler(
            store,
            embedding_service=embedding_service,
            edge_vector_index=edge_index,
        )
        conds = L2Conditions(
            entities=["user:u1"],
            include_relationships=True,
            content_query="what does user like",
            predicate_family="preference",
        )
        results = await handler.execute(conds)

        edges = results["relationships"]
        assert len(edges) == 2
        # LIKES matches the preference family predicate set, so it should rank first
        assert edges[0]["triple_id"] == "t-affinity"
        assert edges[1]["triple_id"] == "t-unrelated"


class TestL2HandlerCreatorAffinityFallback:
    """Test that creator affinity works without platform constraint."""

    @pytest.mark.asyncio
    async def test_creator_affinity_returns_results_without_platform_constraint(self):
        store = _make_l2_store(
            batch_rels={
                "user:u1": [
                    {
                        "triple_id": "follow-1",
                        "subject_id": "user:u1",
                        "subject_type": "user",
                        "predicate": "FOLLOWS",
                        "object_id": "presence:bilibili:creator_1",
                        "object_type": "presence",
                        "status": "active",
                    }
                ]
            },
        )

        handler = L2Handler(store, entity_catalog=AsyncMock())
        conds = L2Conditions(
            content_query="我喜欢哪些UP主",
            subject_hint="self",
            predicate_family="preference",
            include_tom_snapshot=False,
            include_relationships=True,
            include_assertions=False,
            semantic_frame=L2SemanticFrame(
                query_family="affinity",
                subject_scope="self",
                answer_kind="creator",
                answer_unit="identity",
                constraints=[],
            ),
        )

        results = await handler.execute(conds, user_id="u1")

        assert len(results["relationships"]) >= 1


class TestL2HandlerSoftwareAffinityFallback:
    """Test that software affinity works when no target entity resolves."""

    @pytest.mark.asyncio
    async def test_software_affinity_returns_results_without_resolved_target(self):
        store = _make_l2_store(
            batch_rels={
                "user:u1": [
                    {
                        "triple_id": "sw-1",
                        "subject_id": "user:u1",
                        "subject_type": "user",
                        "predicate": "USES",
                        "object_id": "software:vscode",
                        "object_type": "software",
                        "status": "active",
                    }
                ]
            },
        )
        entity_catalog = AsyncMock()
        entity_catalog.resolve_query_entities.return_value = []

        handler = L2Handler(store, entity_catalog=entity_catalog)
        conds = L2Conditions(
            content_query="我平时用什么软件",
            entities=["软件"],
            subject_hint="self",
            predicate_family="preference",
            include_tom_snapshot=False,
            include_relationships=True,
            include_assertions=False,
            semantic_frame=L2SemanticFrame(
                query_family="affinity",
                subject_scope="self",
                answer_kind="software",
                answer_unit="mixed",
                entity_mentions=["软件"],
            ),
        )

        results = await handler.execute(conds, user_id="u1")

        assert len(results["relationships"]) >= 1


class TestL2HandlerPlaceAffinityFallback:
    """Test that place affinity works without location constraint."""

    @pytest.mark.asyncio
    async def test_place_affinity_returns_results_without_location_constraint(self):
        store = _make_l2_store(
            batch_rels={
                "user:u1": [
                    {
                        "triple_id": "visit-1",
                        "subject_id": "user:u1",
                        "subject_type": "user",
                        "predicate": "VISITED",
                        "object_id": "place:cafe-xyz",
                        "object_type": "place",
                        "status": "active",
                    }
                ]
            },
        )

        handler = L2Handler(store, entity_catalog=AsyncMock())
        conds = L2Conditions(
            content_query="我喜欢去哪些地方",
            subject_hint="self",
            predicate_family="preference",
            include_tom_snapshot=False,
            include_relationships=True,
            include_assertions=False,
            semantic_frame=L2SemanticFrame(
                query_family="affinity",
                subject_scope="self",
                answer_kind="place",
                answer_unit="place",
                constraints=[],
            ),
        )

        results = await handler.execute(conds, user_id="u1")

        assert len(results["relationships"]) >= 1
