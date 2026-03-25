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
from magi.memory.hybrid_retrieval.models import (
    L1Conditions,
    L2Conditions,
    L3Conditions,
    L4Conditions,
    LayerQueryPlan,
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
        s._semantic_search_event_hits.return_value = []
        s.query_events.return_value = [
            {"event_id": "e1", "content": "hello world", "timestamp": 1000},
            {"event_id": "e2", "content": "world peace", "timestamp": 2000},
        ]
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

        async def _bm25_path(_query, _limit):
            return ["assistant-generic", "user-fact"]

        async def _vector_path(_query, _limit):
            return []

        async def _keyword_path(_conditions, _limit, *, session_id=None, user_id=None):
            return ["assistant-generic", "user-fact"]

        async def _fetch_and_filter(*, event_ids, conditions, time_range, session_id, user_id):
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

        async def _bm25_path(_query, _limit):
            return ["user-fact"]

        async def _vector_path(_query, _limit):
            return []

        async def _keyword_path(_conditions, _limit, *, session_id=None, user_id=None):
            return ["user-fact"]

        async def _fetch_and_filter(*, event_ids, conditions, time_range, session_id, user_id):
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

        async def _bm25_path(_query, _limit):
            return ["assistant-generic", "user-workshop", "user-webinar"]

        async def _vector_path(_query, _limit):
            return []

        async def _keyword_path(_conditions, _limit, *, session_id=None, user_id=None):
            return ["assistant-generic", "user-workshop", "user-webinar"]

        async def _fetch_and_filter(*, event_ids, conditions, time_range, session_id, user_id):
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
        assert ranked_ids[-1] == "assistant-generic"
        assert set(ranked_ids[:2]) == {"user-workshop", "user-webinar"}

    @pytest.mark.asyncio
    async def test_records_quoted_title_hits_in_retrieval_trace(self, store, monkeypatch):
        handler = L1Handler(store)
        conds = L1Conditions(
            content_query="Did I attend the 'Effective Time Management' workshop?",
            limit=1,
        )

        async def _bm25_path(_query, _limit):
            return ["user-workshop"]

        async def _vector_path(_query, _limit):
            return []

        async def _keyword_path(_conditions, _limit, *, session_id=None, user_id=None):
            return ["user-workshop"]

        async def _fetch_and_filter(*, event_ids, conditions, time_range, session_id, user_id):
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

        async def _bm25_path(_query, _limit):
            return []

        async def _vector_path(_query, _limit):
            return []

        async def _fetch_and_filter(*, event_ids, conditions, time_range, session_id, user_id):
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
# L2Handler
# -----------------------------------------------------------------------


class TestL2Handler:
    @pytest.fixture
    def store(self):
        s = AsyncMock()
        s.get_tom_snapshot.return_value = {"entity_id": "alice", "name": "Alice"}
        s.get_relationships.return_value = [{"subject": "alice", "object": "bob"}]
        return s

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
        conds = L2Conditions(
            entities=["person:alice"],
            include_tom_snapshot=False,
            include_relationships=True,
        )
        results = await handler.execute(conds)
        assert len(results["relationships"]) == 1

    @pytest.mark.asyncio
    async def test_both_snapshot_and_relationships(self, store):
        handler = L2Handler(store)
        conds = L2Conditions(
            entities=["person:alice"],
            include_tom_snapshot=True,
            include_relationships=True,
        )
        results = await handler.execute(conds)
        assert len(results["entity_cards"]) == 1
        assert len(results["relationships"]) == 1

    @pytest.mark.asyncio
    async def test_no_entities_gets_all_relationships(self, store):
        handler = L2Handler(store)
        conds = L2Conditions(
            entities=None,
            include_tom_snapshot=True,
            include_relationships=True,
        )
        results = await handler.execute(conds)
        assert len(results["entity_cards"]) == 0  # no entities to snapshot
        store.get_relationships.assert_called_once()

    @pytest.mark.asyncio
    async def test_self_preference_binds_user_as_subject_and_weather_type(self):
        store = AsyncMock()
        store.get_tom_snapshot.return_value = {"entity_id": "user:u1", "entity_type": "user"}
        store.get_relationships.return_value = [{"triple_id": "pref-1", "subject_id": "user:u1"}]
        store.list_tom_assertions.return_value = []
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
        )

        results = await handler.execute(conds, user_id="u1")

        store.get_tom_snapshot.assert_called_once_with(entity_id="user:u1", entity_type="user")
        _, relationship_kwargs = store.get_relationships.call_args
        assert relationship_kwargs["subject_id"] == "user:u1"
        assert relationship_kwargs["object_types"] == ["weather_state"]
        assert relationship_kwargs.get("object_id") is None
        assert relationship_kwargs["predicates"] == ["LIKES"]
        assert results["trace"]["query_frame"]["chosen_subject_entity_id"] == "user:u1"
        assert results["trace"]["query_frame"]["subject_binding_source"] == "self_anchor"

    @pytest.mark.asyncio
    async def test_explicit_subject_preference_does_not_bind_self(self):
        store = AsyncMock()
        store.get_relationships.return_value = [{"triple_id": "pref-1", "subject_id": "person:xiaowang"}]
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

        _, relationship_kwargs = store.get_relationships.call_args
        assert relationship_kwargs["subject_id"] == "person:xiaowang"
        assert relationship_kwargs.get("object_types") is None
        assert results["trace"]["query_frame"]["chosen_subject_entity_id"] == "person:xiaowang"
        assert results["trace"]["query_frame"]["subject_binding_source"] == "explicit_entity"

    @pytest.mark.asyncio
    async def test_self_preference_filters_person_noise_from_targets(self):
        store = AsyncMock()
        store.get_tom_snapshot.return_value = {"entity_id": "user:local_user", "entity_type": "user"}
        store.get_relationships.return_value = []
        store.list_tom_assertions.return_value = []
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
            {
                "entity_id": "person:local-user",
                "entity_type": "person",
                "canonical_name": "Local User Person",
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
        )

        results = await handler.execute(conds, user_id="local_user")

        _, relationship_kwargs = store.get_relationships.call_args
        assert relationship_kwargs["subject_id"] == "user:local_user"
        assert relationship_kwargs["object_types"] == ["weather_state"]
        assert relationship_kwargs.get("object_id") is None
        assert results["trace"]["query_frame"]["chosen_target_entity_id"] == "weather_state:weather-state"
        assert results["trace"]["query_frame"]["target_entity_id_exact"] is None


# -----------------------------------------------------------------------
# L3Handler
# -----------------------------------------------------------------------


class TestL3Handler:
    @pytest.fixture
    def store(self):
        s = AsyncMock()
        s.db_path = ":memory:"
        s.bm25_search.return_value = [("s1", -1.0)]
        s._semantic_search_summaries.return_value = [{"summary_id": "s1", "content": "weekly summary"}]
        return s

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, store):
        handler = L3Handler(store)
        conds = L3Conditions(content_query="")
        results = await handler.execute(conds)
        assert results == []
        store.bm25_search.assert_not_called()


# -----------------------------------------------------------------------
# L4Handler
# -----------------------------------------------------------------------


class TestL4Handler:
    @pytest.fixture
    def store(self):
        s = AsyncMock()
        s.db_path = ":memory:"
        s.bm25_search.return_value = [("p1", -1.0)]
        s._semantic_query_strategies.return_value = [{"skill_id": "p1", "content": "deploy strategy"}]
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
