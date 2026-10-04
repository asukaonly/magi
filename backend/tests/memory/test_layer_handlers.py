"""Tests for layer handlers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

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
    async def test_specific_user_evidence_outranks_generic_guidance_with_channel_trace(
        self, store, monkeypatch
    ):
        handler = L1Handler(store)
        conds = L1Conditions(
            content_query="What was the first issue I had with my new car after its first service?",
            limit=2,
        )

        async def _bm25_path(_query, _limit, *, user_id=None, l1_retrieval_scopes=None):
            return ["assistant-generic", "user-fact"]

        async def _vector_path(_query, _limit, *, user_id=None, l1_retrieval_scopes=None):
            return []

        async def _keyword_path(
            _conditions, _limit, *, session_id=None, user_id=None, l1_retrieval_scopes=None
        ):
            return ["assistant-generic", "user-fact"]

        async def _fetch_and_filter(
            *, event_ids, conditions, time_range, session_id, user_id, l1_retrieval_scopes=None
        ):
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

        assert results[0]["retrieval_trace"]["base_rrf_score"] == pytest.approx(0.024194)
        assert results[1]["retrieval_trace"]["base_rrf_score"] == pytest.approx(0.024590)
        assert results[0]["retrieval_trace"]["role_bias"] == 0.35
        assert results[1]["retrieval_trace"]["role_bias"] == -0.1
        assert results[0]["retrieval_trace"]["phrase_hits"] == ["first service"]


    @pytest.mark.asyncio
    async def test_prefers_titled_user_events_over_generic_assistant_comparison_guidance(
        self, store, monkeypatch
    ):
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

        async def _keyword_path(
            _conditions, _limit, *, session_id=None, user_id=None, l1_retrieval_scopes=None
        ):
            return ["assistant-generic", "user-workshop", "user-webinar"]

        async def _fetch_and_filter(
            *, event_ids, conditions, time_range, session_id, user_id, l1_retrieval_scopes=None
        ):
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

        by_id = {row["event_id"]: row for row in results}
        assert by_id["user-workshop"]["retrieval_trace"]["quoted_phrase_hits"] == [
            "effective time management"
        ]
        assert by_id["user-webinar"]["retrieval_trace"]["quoted_phrase_hits"] == [
            "data analysi using python"
        ]


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

    async def _current_assertions(**kwargs):
        return await s.list_tom_assertions(
            entity_id=kwargs.get("entity_id"),
            entity_type=kwargs.get("entity_type"),
            trait_families=kwargs.get("trait_families"),
            validation_states=kwargs.get("validation_states"),
            target_entity_id=kwargs.get("target_entity_id"),
            limit=kwargs.get("limit", 100),
        )

    async def _current_relationships(**kwargs):
        triple_ids = kwargs.get("triple_ids")
        if triple_ids:
            candidates = [
                item
                for item in overrides.get("edge_vectors", [])
                if item.get("triple_id") in set(triple_ids)
            ]
            candidates.extend(
                item
                for item in overrides.get("rels", [])
                if item.get("triple_id") in set(triple_ids) and item not in candidates
            )
            return candidates
        return await s.get_relationships(
            subject_id=kwargs.get("subject_id"),
            object_id=kwargs.get("object_id"),
            predicates=kwargs.get("predicates"),
            object_types=kwargs.get("object_types"),
            evidence_classes=kwargs.get("evidence_classes"),
            limit=kwargs.get("limit", 100),
        )

    async def _batch_current_assertions(**kwargs):
        return await s.batch_list_tom_assertions(
            entity_ids=kwargs["entity_ids"],
            entity_type=kwargs.get("entity_type"),
            trait_families=kwargs.get("trait_families"),
            validation_states=kwargs.get("validation_states"),
            target_entity_id=kwargs.get("target_entity_id"),
            limit_per_entity=kwargs.get("limit_per_entity", 100),
        )

    async def _batch_current_relationships(**kwargs):
        return await s.batch_get_relationships(
            entity_ids=kwargs["entity_ids"],
            direction=kwargs.get("direction", "outgoing"),
            predicates=kwargs.get("predicates"),
            target_object_id=kwargs.get("object_id"),
            object_types=kwargs.get("object_types"),
            limit_per_entity=kwargs.get("limit_per_entity", 100),
            evidence_classes=kwargs.get("evidence_classes"),
        )

    async def _iter_current_assertions(**kwargs):
        if kwargs.get("entity_ids"):
            by_entity = await _batch_current_assertions(**kwargs)
            rows = [row for items in by_entity.values() for row in items]
        else:
            rows = await _current_assertions(**kwargs)
        if rows:
            yield rows

    s.iter_current_assertions = MagicMock(side_effect=_iter_current_assertions)
    s.batch_list_current_assertions = AsyncMock(side_effect=_batch_current_assertions)
    s.batch_list_current_relationships = AsyncMock(side_effect=_batch_current_relationships)
    s.list_current_assertions = AsyncMock(side_effect=_current_assertions)
    s.list_current_relationships = AsyncMock(side_effect=_current_relationships)
    return s


@pytest_asyncio.fixture
async def real_l2(tmp_path):
    from _shared.memory_schema import apply_memory_shared_schema
    from magi.memory.l2.store import L2CognitionStore
    from magi.memory.l2.entities.catalog import L2EntityCatalog

    db_path = str(tmp_path / "cognition.db")
    await apply_memory_shared_schema(db_path)
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()
    catalog = L2EntityCatalog(db_path=db_path, vector_enabled=False)
    return store, catalog


async def _persist_edge(store, subject, predicate, target):
    return await store.upsert_knowledge_edge(
        subject_id=subject,
        subject_type=subject.split(":", 1)[0],
        predicate=predicate,
        object_id=target,
        object_type=target.split(":", 1)[0],
        evidence_event_ids=[f"event:{subject}:{predicate}:{target}"],
        confidence=0.9,
        observed_at=1000.0,
        source_type="chat",
        evidence_class="user_self_report",
    )


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
    @pytest.mark.parametrize("include_snapshots", [False, None])
    @pytest.mark.parametrize("include_relationships", [False, None])
    async def test_inclusion_flags_control_independent_result_groups(
        self, store, include_snapshots, include_relationships
    ):
        options = {
            key: value
            for key, value in {
                "include_tom_snapshot": include_snapshots,
                "include_relationships": include_relationships,
            }.items()
            if value is not None
        }
        conditions = L2Conditions(
            entities=["person:alice"],
            predicates=["KNOWS"],
            **options,
            include_assertions=False,
        )
        result = await L2Handler(store).execute(conditions)
        assert [row["entity_id"] for row in result["entity_cards"]] == (
            ["alice"] if include_snapshots is not False else []
        )
        assert [row["triple_id"] for row in result["relationships"]] == (
            ["t1"] if include_relationships is not False else []
        )
        if include_snapshots is not False:
            store.batch_get_tom_snapshots.assert_awaited_once()
            assert store.batch_get_tom_snapshots.await_args.kwargs["entities"] == [
                {"entity_id": "person:alice", "entity_type": "person"}
            ]
        else:
            store.batch_get_tom_snapshots.assert_not_awaited()
        if include_relationships is not False:
            assert store.batch_get_relationships.await_args_list
            assert {
                eid
                for call in store.batch_get_relationships.await_args_list
                for eid in call.kwargs["entity_ids"]
            } == {"person:alice"}
        else:
            store.batch_get_relationships.assert_not_awaited()
            store.search_edges_by_embedding.assert_not_awaited()

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
    @pytest.mark.parametrize(
        "scope,mentions,typed,expected_subject",
        [
            ("self", None, False, "user:u1"),
            ("self", ["天气", "小王"], True, "user:u1"),
            ("explicit", ["小王"], True, "person:xiaowang"),
        ],
    )
    async def test_subject_binding_selects_exact_owner_despite_other_people(
        self, real_l2, monkeypatch, scope, mentions, typed, expected_subject
    ):
        store, catalog = real_l2
        await catalog.upsert_entity(
            entity_id="person:xiaowang", entity_type="person", canonical_name="小王"
        )
        await catalog.upsert_entity(
            entity_id="weather_state:sunny", entity_type="weather_state", canonical_name="天气"
        )
        ids = {}
        for subject, target in (
            ("user:u1", "weather_state:sunny"),
            ("person:xiaowang", "food:ramen"),
            ("user:other", "food:pasta"),
        ):
            ids[subject] = await _persist_edge(store, subject, "LIKES", target)
        read = AsyncMock(wraps=store.batch_list_current_relationships)
        monkeypatch.setattr(store, "batch_list_current_relationships", read)
        frame = (
            L2SemanticFrame(
                query_family="affinity",
                subject_scope=scope,
                answer_kind="unknown",
                subject_mentions=["小王"] if scope == "explicit" else [],
            )
            if typed
            else None
        )
        conditions = L2Conditions(
            content_query="小王喜欢什么" if scope == "explicit" else "我喜欢什么天气",
            entities=mentions,
            subject_hint=scope,
            predicate_family="preference",
            include_tom_snapshot=False,
            include_relationships=True,
            include_assertions=False,
            semantic_frame=frame,
        )
        results = await L2Handler(store, entity_catalog=catalog).execute(conditions, user_id="u1")
        assert [row["triple_id"] for row in results["relationships"]] == [ids[expected_subject]]
        assert results["trace"]["grounding_plan"]["subject_entity_ids"] == [expected_subject]
        assert read.await_args_list
        assert {eid for call in read.await_args_list for eid in call.kwargs["entity_ids"]} == {
            expected_subject
        }


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
    @pytest.mark.parametrize("with_vectors", [False, True])
    @pytest.mark.parametrize("matching_container", [False, True])
    @pytest.mark.parametrize(
        "facet,kind,predicate,target_a,target_b,container_a,container_b,link",
        [
            (
                "platform",
                "creator",
                "FOLLOWS",
                "presence:creator-a",
                "presence:creator-b",
                "software:bilibili",
                "software:youtube",
                "ON_PLATFORM",
            ),
            (
                "located_in",
                "place",
                "VISITED",
                "place:cafe-hangzhou",
                "place:cafe-shanghai",
                "place:hangzhou",
                "place:shanghai",
                "LOCATED_IN",
            ),
        ],
    )
    async def test_affinity_constraint_selects_only_matching_graph_targets(
        self,
        real_l2,
        monkeypatch,
        facet,
        kind,
        predicate,
        target_a,
        target_b,
        container_a,
        container_b,
        link,
        with_vectors,
        matching_container,
    ):
        store, catalog = real_l2
        expected = await _persist_edge(store, "user:u1", predicate, target_a)
        await _persist_edge(store, "user:u1", predicate, target_b)
        await _persist_edge(store, "user:other", predicate, target_a)
        await _persist_edge(store, target_a, link, container_a)
        await _persist_edge(store, target_b, link, container_b)
        expected_pairs = {(expected, target_a)}
        if kind == "creator":
            person = "person:creator-a"
            person_edge = await _persist_edge(store, "user:u1", "FOLLOWS", person)
            await _persist_edge(store, target_a, "PRESENCE_OF", person)
            expected_pairs.add((person_edge, person))
        requested_container = container_a if matching_container else "missing:container"
        vector_rows = await store.get_relationships(subject_id="user:u1", predicates=[predicate])
        embedding_service = AsyncMock()
        embedding_service.embed_text.return_value = SimpleNamespace(vector=[0.1] * 8)
        embedding_service.result_for_index = lambda result, **kwargs: result
        search = AsyncMock(return_value=vector_rows)
        monkeypatch.setattr(store, "search_edges_by_embedding", search)
        lookup = AsyncMock(wraps=store.batch_list_current_relationships)
        monkeypatch.setattr(store, "batch_list_current_relationships", lookup)
        frame = L2SemanticFrame(
            query_family="affinity",
            subject_scope="self",
            answer_kind=kind,
            constraints=[
                SemanticConstraint(
                    scope="target",
                    facet=facet,
                    raw_value=requested_container,
                    resolved_entity_id=requested_container,
                )
            ],
        )
        conditions = L2Conditions(
            content_query="Which matching targets do I prefer?",
            subject_hint="self",
            predicate_family="preference",
            include_tom_snapshot=False,
            include_relationships=True,
            include_assertions=False,
            semantic_frame=frame,
        )
        handler = L2Handler(
            store,
            entity_catalog=catalog,
            embedding_service=embedding_service if with_vectors else None,
            edge_vector_index=AsyncMock(),
        )
        results = await handler.execute(conditions, user_id="u1")
        actual_pairs = {(r["triple_id"], r["object_id"]) for r in results["relationships"]}
        assert actual_pairs == (expected_pairs if matching_container else set())
        assert any(
            c.kwargs.get("predicates") == [link] and c.kwargs.get("object_id") == requested_container
            for c in lookup.await_args_list
        )
        if with_vectors:
            search.assert_awaited_once()
            embedding_service.embed_text.assert_awaited_once()
        else:
            search.assert_not_awaited()

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
    async def test_empty_query_skips_all_retrieval(self, store):
        assert await L4Handler(store).execute(L4Conditions(content_query="")) == []
        assert store.mock_calls == []

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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "dispatch", [execute_plan, execute_layer_plan], ids=["direct", "service-wrapper"]
)
@pytest.mark.parametrize(
    "layer,condition_type",
    [("L1", L1Conditions), ("L2", L2Conditions), ("L3", L3Conditions), ("L4", L4Conditions)],
)
@pytest.mark.parametrize("available", [False, True])
async def test_layer_dispatch_preserves_context_and_result_shape(
    dispatch, layer, condition_type, available
):
    conditions = condition_type(content_query="specific evidence", limit=7)
    time_range = TimeRange(start=1234.0, end=5678.0)
    plan = LayerQueryPlan(layer=layer, conditions=conditions, time_range=time_range)
    handlers = {
        "l1": AsyncMock(spec=L1Handler),
        "l2": AsyncMock(spec=L2Handler),
        "l3": AsyncMock(spec=L3Handler),
        "l4": AsyncMock(spec=L4Handler),
    }
    expected = (
        {
            "relationships": [{"triple_id": "retained-edge"}],
            "entity_cards": [{"entity_id": "person:alice"}],
        }
        if layer == "L2"
        else [{"id": "retained-result"}]
    )
    selected = handlers[layer.lower()]
    selected.execute.return_value = expected
    if not available:
        handlers[layer.lower()] = None
    result = await dispatch(plan, **handlers, user_id="owner-7", session_id="session-9")
    if available:
        assert result is expected
        kwargs = {"user_id": "owner-7"} if layer in {"L1", "L2"} else {}
        if layer == "L1":
            kwargs["session_id"] = "session-9"
        selected.execute.assert_awaited_once_with(conditions, time_range, **kwargs)
    else:
        assert result == ({"entity_cards": [], "relationships": []} if layer == "L2" else [])
        selected.execute.assert_not_awaited()
    for name, handler in handlers.items():
        if handler is not None and name != layer.lower():
            handler.execute.assert_not_awaited()


class TestL2HandlerEdgeVectorSupplement:
    """Test edge vector search integration in L2 pipeline."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("embedding_available", [False, True])
    async def test_embedding_availability_controls_only_the_vector_channel(self, embedding_available):
        structured_edge = {
            "triple_id": "t1",
            "predicate": "LIKES",
            "subject_id": "user:u1",
            "status": "active",
        }
        store = _make_l2_store(
            rels=[structured_edge],
            batch_rels={"user:u1": [structured_edge]},
            edge_vectors=[
                {"triple_id": "t2", "predicate": "LIKES", "vector_distance": 0.1, "status": "active"},
            ],
        )

        embedding_service = AsyncMock()
        embedding_service.embed_text.return_value = SimpleNamespace(vector=[0.1] * 8)
        embedding_service.result_for_index = lambda result, **_: result
        edge_index = AsyncMock()

        handler = L2Handler(
            store,
            embedding_service=embedding_service if embedding_available else None,
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
        by_id = {row["triple_id"]: row for row in results["relationships"]}
        assert set(by_id) == ({"t1", "t2"} if embedding_available else {"t1"})
        assert len(results["relationships"]) == len(by_id)
        assert by_id["t1"]["_fusion_trace"]["channels"] == ["structured_graph", "topology"]
        assert results["trace"]["channel_counts"]["knowledge_edges"] == len(by_id)
        if embedding_available:
            assert by_id["t2"]["_fusion_trace"]["channels"] == ["edge_vector"]
            embedding_service.embed_text.assert_awaited_once()
            store.search_edges_by_embedding.assert_awaited_once()
        else:
            embedding_service.embed_text.assert_not_awaited()
            store.search_edges_by_embedding.assert_not_awaited()
            assert edge_index.mock_calls == []


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
        embedding_service.embed_text.return_value = SimpleNamespace(vector=[0.1] * 8)
        embedding_service.result_for_index = lambda result, **_: result
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
        embedding_service.embed_text.return_value = SimpleNamespace(vector=[0.1] * 8)
        embedding_service.result_for_index = lambda result, **_: result
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,query,mentions,predicate,target",
    [
        ("creator", "我喜欢哪些UP主", None, "FOLLOWS", "presence:creator"),
        ("software", "我平时用什么软件", ["软件"], "USES", "software:vscode"),
        ("place", "我喜欢去哪些地方", None, "VISITED", "place:cafe"),
    ],
)
async def test_affinity_without_exact_target_still_excludes_wrong_types(
    real_l2, kind, query, mentions, predicate, target
):
    store, catalog = real_l2
    expected = await _persist_edge(store, "user:u1", predicate, target)
    expected_pairs = {(expected, "user:u1", target)}
    if kind == "creator":
        other_creator = await _persist_edge(store, "user:u1", "FOLLOWS", "person:creator")
        expected_pairs.add((other_creator, "user:u1", "person:creator"))
    await _persist_edge(store, "user:other", predicate, target)
    await _persist_edge(store, "user:u1", "LIKES", "food:ramen")
    conditions = L2Conditions(
        content_query=query,
        entities=mentions,
        subject_hint="self",
        predicate_family="preference",
        include_tom_snapshot=False,
        include_relationships=True,
        include_assertions=False,
        semantic_frame=L2SemanticFrame(
            query_family="affinity",
            subject_scope="self",
            answer_kind=kind,
            entity_mentions=mentions or [],
        ),
    )
    results = await L2Handler(store, entity_catalog=catalog).execute(conditions, user_id="u1")
    assert {
        (r["triple_id"], r["subject_id"], r["object_id"]) for r in results["relationships"]
    } == expected_pairs
