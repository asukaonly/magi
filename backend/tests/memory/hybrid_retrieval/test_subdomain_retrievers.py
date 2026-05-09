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
    retrieve_snapshots,
)
from magi.memory.hybrid_retrieval.models import TemporalContext


def _make_store() -> MagicMock:
    store = MagicMock()
    store.batch_list_tom_assertions = AsyncMock(return_value={})
    store.list_tom_assertions = AsyncMock(return_value=[])
    store.batch_get_tom_snapshots = AsyncMock(return_value=[])
    store.list_episodes = AsyncMock(return_value=[])
    store.search_episodes_fts = AsyncMock(return_value=[])
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
                {"assertion_id": "a1", "first_inferred_at": time.time(), "last_validated_at": time.time()},
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
            {"assertion_id": "a1", "first_inferred_at": time.time(), "last_validated_at": time.time()},
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
                mode="during", start=now - 7200, end=now,
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
                mode="during", start=now - 3600, end=now,
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
                mode="during", start=now - 7200, end=now,
            ),
        )
        result = await retrieve_episodes(plan, store)
        assert len(result) == 1
        assert result[0]["_candidate_kind"] == "episode"

    @pytest.mark.asyncio
    async def test_deduplicates_across_channels(self):
        store = _make_store()
        now = time.time()
        ep = {"episode_id": "ep1", "time_start": now - 3600, "time_end": now}
        store.list_episodes.return_value = [ep]
        store.search_episodes_fts.return_value = [ep]
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
        assert len(result) == 1

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
