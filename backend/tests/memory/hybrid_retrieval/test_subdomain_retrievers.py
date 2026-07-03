"""Tests for L2 subdomain retrievers."""

import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from magi.memory.hybrid_retrieval.grounding import (
    GroundedEntityCandidate,
    L2GroundingPlan,
)
from magi.memory.hybrid_retrieval.l2_subdomain_retrievers import (
    retrieve_assertions,
    retrieve_episodes,
    retrieve_experiences,
    retrieve_snapshots,
)
from magi.memory.hybrid_retrieval.models import TemporalContext
from magi.memory.hybrid_retrieval.temporal import build_assertion_temporal_clause


def _make_store() -> MagicMock:
    store = MagicMock()
    store.batch_list_tom_assertions = AsyncMock(return_value={})
    store.list_tom_assertions = AsyncMock(return_value=[])
    store.batch_get_tom_snapshots = AsyncMock(return_value=[])
    store.list_episodes = AsyncMock(return_value=[])
    store.search_episodes_fts = AsyncMock(return_value=[])
    store.list_experiences = AsyncMock(return_value=[])
    store.list_experience_members = AsyncMock(return_value=[])
    store.get_episode = AsyncMock(return_value=None)
    return store


def _make_plan(**kwargs) -> L2GroundingPlan:
    defaults = {
        "query_kind": "preference",
        "subject_candidates": [
            GroundedEntityCandidate(
                entity_id="user:test",
                entity_type="person",
                surface="self",
                score=1.0,
            )
        ],
        "temporal_context": TemporalContext(mode="none"),
    }
    defaults.update(kwargs)
    return L2GroundingPlan(**defaults)


class TestRetrieveAssertions:
    @pytest.mark.asyncio
    async def test_calls_batch_when_entities_present(self):
        store = _make_store()
        store.batch_list_tom_assertions.return_value = {
            "user:test": [
                {
                    "assertion_id": "a1",
                    "first_inferred_at": time.time(),
                    "last_validated_at": time.time(),
                },
            ],
        }
        plan = _make_plan()
        result = await retrieve_assertions(plan, store)
        store.batch_list_tom_assertions.assert_called_once()
        assert len(result) == 1
        assert result[0]["_candidate_kind"] == "assertion"

    @pytest.mark.asyncio
    async def test_falls_back_to_list_when_no_entities(self):
        store = _make_store()
        store.list_tom_assertions.return_value = [
            {
                "assertion_id": "a1",
                "first_inferred_at": time.time(),
                "last_validated_at": time.time(),
            },
        ]
        plan = _make_plan(subject_candidates=[])
        result = await retrieve_assertions(plan, store)
        store.list_tom_assertions.assert_called_once()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_temporal_score_attached(self):
        store = _make_store()
        now = time.time()
        store.batch_list_tom_assertions.return_value = {
            "user:test": [
                {"assertion_id": "a1", "first_inferred_at": now - 3600, "last_validated_at": now},
            ],
        }
        plan = _make_plan()
        result = await retrieve_assertions(plan, store)
        assert "_temporal_score" in result[0]

    @pytest.mark.asyncio
    async def test_stable_state_included_in_assertion_query(self):
        """The graduated 'stable' state must be retrievable (regression for #133)."""
        store = _make_store()
        plan = _make_plan()
        await retrieve_assertions(plan, store)
        states = store.batch_list_tom_assertions.call_args.kwargs["validation_states"]
        assert "stable" in states

    @pytest.mark.asyncio
    async def test_phantom_states_excluded_from_assertion_query(self):
        """Phantom states the write side never emits must not be queried (#133)."""
        store = _make_store()
        plan = _make_plan()
        await retrieve_assertions(plan, store)
        states = store.batch_list_tom_assertions.call_args.kwargs["validation_states"]
        assert "active" not in states
        assert "stable-compatible" not in states


class TestAssertionTemporalClause:
    def test_current_mode_includes_stable(self):
        """The 'current' temporal clause must allow stable assertions (#133)."""
        _sql, params = build_assertion_temporal_clause(TemporalContext(mode="current"))
        assert "stable" in params
        assert "active" not in params
        assert "stable-compatible" not in params


class TestRetrieveSnapshots:
    @pytest.mark.asyncio
    async def test_current_mode_returns_snapshot(self):
        store = _make_store()
        store.batch_get_tom_snapshots.return_value = [
            {"entity_id": "user:test", "entity_type": "person", "core_traits": "{}"},
        ]
        plan = _make_plan()
        result = await retrieve_snapshots(plan, store)
        assert len(result) == 1
        assert result[0]["_candidate_kind"] == "snapshot"

    @pytest.mark.asyncio
    async def test_historical_mode_extracts_history(self):
        store = _make_store()
        now = time.time()
        history = [{"evolved_at": now - 3600, "value": "happy"}]
        store.batch_get_tom_snapshots.return_value = [
            {
                "entity_id": "user:test",
                "entity_type": "person",
                "core_traits_history": json.dumps(history),
                "preferences_history": "[]",
                "relationship_history": "[]",
                "mood_trajectory": "[]",
            },
        ]
        plan = _make_plan(
            temporal_context=TemporalContext(
                mode="during",
                start=now - 7200,
                end=now,
            ),
        )
        result = await retrieve_snapshots(plan, store)
        kinds = [r["_candidate_kind"] for r in result]
        assert "snapshot" in kinds
        assert "snapshot_history" in kinds

    @pytest.mark.asyncio
    async def test_mood_trajectory_uses_at_key(self):
        store = _make_store()
        now = time.time()
        mood = [{"at": now - 1800, "family": "mood", "value": "happy", "confidence": 0.8}]
        store.batch_get_tom_snapshots.return_value = [
            {
                "entity_id": "user:test",
                "entity_type": "person",
                "core_traits_history": "[]",
                "preferences_history": "[]",
                "relationship_history": "[]",
                "mood_trajectory": json.dumps(mood),
            },
        ]
        plan = _make_plan(
            temporal_context=TemporalContext(
                mode="during",
                start=now - 3600,
                end=now,
            ),
        )
        result = await retrieve_snapshots(plan, store)
        history_entries = [r for r in result if r.get("_candidate_kind") == "snapshot_history"]
        assert len(history_entries) == 1
        assert history_entries[0].get("_history_field") == "mood_trajectory"


class TestRetrieveEpisodes:
    @pytest.mark.asyncio
    async def test_queries_by_time(self):
        store = _make_store()
        now = time.time()
        store.list_episodes.return_value = [
            {"episode_id": "ep1", "time_start": now - 3600, "time_end": now},
        ]
        plan = _make_plan(
            temporal_context=TemporalContext(
                mode="during",
                start=now - 7200,
                end=now,
            ),
        )
        result = await retrieve_episodes(plan, store)
        assert len(result) == 1
        assert result[0]["_candidate_kind"] == "episode"

    @pytest.mark.asyncio
    async def test_content_fts_not_consulted(self):
        """Episode recall is time-anchored only; content recall belongs to L1/experiences."""
        store = _make_store()
        now = time.time()
        ep = {"episode_id": "ep1", "time_start": now - 3600, "time_end": now}
        store.list_episodes.return_value = [ep]
        store.search_episodes_fts.return_value = [
            {"episode_id": "ep2", "time_start": now - 7200, "time_end": now - 3600},
        ]
        plan = _make_plan(
            predicate_family="preference",
            object_candidates=[
                GroundedEntityCandidate(
                    entity_id="food:pizza",
                    entity_type="food",
                    surface="Pizza",
                    score=0.9,
                ),
            ],
        )
        result = await retrieve_episodes(plan, store)
        assert [item["episode_id"] for item in result] == ["ep1"]
        store.search_episodes_fts.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_entity_overlap_scored(self):
        store = _make_store()
        now = time.time()
        store.list_episodes.return_value = [
            {
                "episode_id": "ep1",
                "time_start": now - 3600,
                "time_end": now,
                "primary_entity_ids": ["user:test"],
            },
        ]
        plan = _make_plan()
        result = await retrieve_episodes(plan, store)
        assert result[0].get("_entity_overlap_score", 0) > 0


class TestRetrieveExperiences:
    @pytest.mark.asyncio
    async def test_matches_user_curated_experience_text_and_expands_members(self):
        store = _make_store()
        now = time.time()
        store.list_experiences.return_value = [
            {
                "experience_id": "exp-japan",
                "status": "active",
                "title": "日本旅行",
                "user_label": "2026年5月日本旅行",
                "user_note": "东京、京都、新干线、酒店",
                "magi_interpretation": "用户在日本旅行期间规划路线和车票。",
                "time_start": now - 86400 * 3,
                "time_end": now,
                "primary_entity_ids": ["place:japan", "transport:shinkansen"],
                "primary_place_ids": ["place:tokyo"],
                "primary_topic_keys": ["旅行", "新干线"],
                "source_episode_count": 2,
                "source_event_count": 18,
                "narrative_score": 0.82,
                "user_pinned": True,
            }
        ]
        store.list_experience_members.return_value = [
            {
                "experience_id": "exp-japan",
                "member_type": "episode",
                "member_id": "ep-ticket",
                "role": "core",
                "confidence": 0.9,
            },
            {
                "experience_id": "exp-japan",
                "member_type": "event",
                "member_id": "evt-map",
                "role": "supporting",
                "confidence": 0.7,
            },
        ]
        store.get_episode.return_value = {
            "episode_id": "ep-ticket",
            "title": "查询新干线车票",
            "summary": "查看东京到京都的新干线车票。",
            "time_start": now - 3600,
            "time_end": now,
        }
        plan = _make_plan(
            object_candidates=[
                GroundedEntityCandidate(
                    entity_id="place:japan",
                    entity_type="place",
                    surface="日本",
                    score=0.95,
                )
            ],
        )

        result = await retrieve_experiences(plan, store, limit=5)

        assert [item["experience_id"] for item in result] == ["exp-japan"]
        assert result[0]["_candidate_kind"] == "experience"
        assert result[0]["source_episode_ids"] == ["ep-ticket"]
        assert result[0]["source_event_ids"] == ["evt-map"]
        assert result[0]["source_episodes"][0]["episode_id"] == "ep-ticket"

    @pytest.mark.asyncio
    async def test_excludes_hidden_or_merged_experiences(self):
        store = _make_store()
        now = time.time()
        store.list_experiences.return_value = [
            {
                "experience_id": "exp-hidden",
                "status": "hidden",
                "title": "日本旅行",
                "time_start": now - 100,
                "time_end": now,
                "source_event_count": 20,
            },
            {
                "experience_id": "exp-merged",
                "status": "active",
                "title": "日本旅行",
                "merged_into_experience_id": "exp-parent",
                "time_start": now - 100,
                "time_end": now,
                "source_event_count": 20,
            },
        ]
        plan = _make_plan(
            object_candidates=[
                GroundedEntityCandidate(
                    entity_id="place:japan",
                    entity_type="place",
                    surface="日本",
                    score=0.95,
                )
            ],
        )

        result = await retrieve_experiences(plan, store)

        assert result == []
