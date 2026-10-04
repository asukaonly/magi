"""Tests for L2 subdomain retrievers."""

import json
import time
from types import SimpleNamespace

import aiosqlite
import pytest_asyncio
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
from magi.memory.hybrid_retrieval import temporal as temporal_module
from magi.memory.l2.store import L2CognitionStore


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


@pytest_asyncio.fixture
async def real_store(tmp_path):
    store = L2CognitionStore(db_path=str(tmp_path / "subdomain.db"))
    await store.initialize()
    return store


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["none", "current"])
@pytest.mark.parametrize("scoped", [True, False], ids=["subject-batch", "global-list"])
async def test_assertion_retrieval_selects_stored_states_owners_and_targets(
    real_store, monkeypatch, mode, scoped
):
    now = time.time()
    monkeypatch.setattr(temporal_module, "time", SimpleNamespace(time=lambda: now))
    rows = [
        ("tentative", "user:test", "preference_profile", "tentative", None, "topic:tea", 0),
        ("corroborated", "user:test", "preference_profile", "corroborated", None, "topic:tea", 10),
        ("stable", "user:test", "preference_profile", "stable", None, "topic:tea", 60),
        ("other_owner", "person:alice", "preference_profile", "stable", None, "topic:tea", 0),
        ("other_family", "user:test", "personality", "stable", None, "topic:tea", 0),
        ("other_target", "user:test", "preference_profile", "stable", None, "topic:coffee", 0),
        ("expired", "user:test", "preference_profile", "stable", now - 1, "topic:tea", 0),
        ("rejected", "user:test", "preference_profile", "user_rejected", None, "topic:tea", 0),
        ("superseded", "user:test", "preference_profile", "superseded", None, "topic:tea", 0),
        ("phantom_active", "user:test", "preference_profile", "active", None, "topic:tea", 0),
        (
            "phantom_stable",
            "user:test",
            "preference_profile",
            "stable-compatible",
            None,
            "topic:tea",
            0,
        ),
    ]
    ids = {}
    for name, owner, family, state, expires, target, age in rows:
        assertion_id = await real_store.upsert_assertion_candidate(
            {
                "entity_id": owner,
                "entity_type": "person",
                "trait_family": family,
                "trait_name": name,
                "trait_value": f"value-{name}",
                "confidence_score": 0.8,
                "evidence_events": [f"event-{name}"],
                "volatility_index": 0.1,
                "source_domain": "user_authored",
                "inference_depth": "direct",
                "validation_state": "tentative",
                "first_inferred_at": now - age * 86400,
                "last_validated_at": now - age * 86400,
                "temporal_scope": "stable",
                "decay_policy": "evidence_only",
                "target_entity_id": target,
                "target_entity_type": "topic",
            }
        )
        ids[name] = assertion_id
        async with aiosqlite.connect(real_store.db_path) as db:
            await db.execute(
                "UPDATE tom_trait_assertions SET status=?, validation_state=?, expires_at=? WHERE assertion_id=?",
                (state, state, expires, assertion_id),
            )
            await db.commit()
    plan = _make_plan(
        temporal_context=TemporalContext(mode=mode),
        object_candidates=[
            GroundedEntityCandidate(
                entity_id="topic:tea", entity_type="topic", surface="tea", score=1.0
            )
        ],
    )
    if not scoped:
        plan.subject_candidates = []
    result = await retrieve_assertions(plan, real_store)
    expected = {"tentative", "corroborated", "stable"} | ({"other_owner"} if not scoped else set())
    assert {r["assertion_id"] for r in result} == {ids[n] for n in expected}
    assert {r["trait_value"] for r in result} == {f"value-{n}" for n in expected}
    assert all(r["_candidate_kind"] == "assertion" for r in result)
    expected_scores = {"tentative": 1.0, "corroborated": 0.8, "stable": 0.6, "other_owner": 1.0}
    assert {r["trait_name"]: r["_temporal_score"] for r in result} == {
        name: expected_scores[name] if mode == "current" else 1.0 for name in expected
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["current", "during"])
async def test_snapshot_retrieval_selects_exact_entity_and_temporal_projection(real_store, mode):
    history_fields = ("core_traits_history", "preferences_history", "relationship_history")
    expected_history = []
    for entity in ("user:test", "person:alice", "person:unrelated", "place:paris"):
        histories = {}
        for field in history_fields:
            entries = [
                {"evolved_at": stamp, "value": f"{entity}:{field}:{label}"}
                for label, stamp in (
                    ("past", 99),
                    ("start", 100),
                    ("inside", 150),
                    ("end", 200),
                    ("future", 201),
                )
            ]
            entries.append({"value": "missing-time"})
            histories[field] = entries
            if entity in ("user:test", "person:alice"):
                expected_history.extend(
                    {
                        **entry,
                        "_history_field": field,
                        "_temporal_score": 0.0,
                        "_candidate_kind": "snapshot_history",
                        "_source_entity_id": entity,
                        "_source_entity_type": "person",
                    }
                    for entry in entries[1:4]
                )
        mood = [
            {"at": 150, "evolved_at": 999, "value": f"{entity}:happy"},
            {"at": 201, "evolved_at": 150, "value": "outside"},
            {"evolved_at": 150, "value": "missing-at"},
        ]
        if entity in ("user:test", "person:alice"):
            expected_history.append(
                {
                    **mood[0],
                    "_history_field": "mood_trajectory",
                    "_temporal_score": 0.0,
                    "_candidate_kind": "snapshot_history",
                    "_source_entity_id": entity,
                    "_source_entity_type": "person",
                }
            )
        async with aiosqlite.connect(real_store.db_path) as db:
            await db.execute(
                """INSERT INTO tom_snapshots
                (snapshot_id,entity_id,entity_type,core_traits,current_mood,core_traits_history,preferences_history,relationship_history,mood_trajectory,last_updated_at,created_at,source_revision,source_generation)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,0,(SELECT generation FROM memory_clear_state WHERE singleton_id=1))""",
                (
                    f"snapshot-{entity}",
                    entity,
                    "place" if entity.startswith("place:") else "person",
                    json.dumps({"current_trait": f"{entity}:current"}),
                    "current-mood",
                    *(json.dumps(histories[field]) for field in history_fields),
                    json.dumps(mood),
                    300,
                    300,
                ),
            )
            await db.commit()
    plan = _make_plan(
        temporal_context=TemporalContext(mode=mode, start=100, end=200),
        object_candidates=[
            GroundedEntityCandidate(
                entity_id="person:alice", entity_type="person", surface="Alice", score=1
            ),
            GroundedEntityCandidate(
                entity_id="place:paris", entity_type="place", surface="Paris", score=1
            ),
        ],
    )
    result = await retrieve_snapshots(plan, real_store)
    if mode == "current":
        expected = []
        for entity in ("user:test", "person:alice"):
            snapshot = await real_store.get_tom_snapshot(entity_id=entity, entity_type="person")
            assert snapshot["core_traits"] == {"current_trait": f"{entity}:current"}
            expected.append({**snapshot, "_candidate_kind": "snapshot", "_temporal_score": 1.0})
        assert sorted(result, key=lambda r: r["entity_id"]) == sorted(
            expected, key=lambda r: r["entity_id"]
        )
    else:
        assert sorted(result, key=lambda r: r["value"]) == sorted(
            expected_history, key=lambda r: r["value"]
        )


@pytest.mark.asyncio
async def test_episode_retrieval_filters_real_intervals_and_ranks_entity_overlap(real_store):
    definitions = [
        ("full", "active", 100, 200, ["user:test", "food:pizza"]),
        ("half", "active", 100, 200, ["user:test"]),
        ("none", "active", 100, 200, ["person:unrelated"]),
        ("before", "active", 1, 99, ["user:test", "food:pizza"]),
        ("after", "active", 201, 300, ["user:test", "food:pizza"]),
        ("candidate", "candidate", 100, 200, ["user:test", "food:pizza"]),
        ("invalidated", "invalidated", 100, 200, ["user:test", "food:pizza"]),
    ]
    for name, status, start, end, entities in definitions:
        await real_store.create_episode(
            episode_id=name,
            status=status,
            time_start=start,
            time_end=end,
            primary_entity_ids=entities,
            summary=f"summary-{name}",
        )
    real_store.search_episodes_fts = AsyncMock(
        side_effect=AssertionError("Episode content search must not run")
    )
    plan = _make_plan(
        temporal_context=TemporalContext(mode="during", start=100, end=200),
        content_query="Pizza",
        object_candidates=[
            GroundedEntityCandidate(
                entity_id="food:pizza", entity_type="food", surface="Pizza", score=0.9
            )
        ],
    )
    result = await retrieve_episodes(plan, real_store, limit=20)
    assert [r["episode_id"] for r in result] == ["full", "half", "none"]
    assert [r["summary"] for r in result] == ["summary-full", "summary-half", "summary-none"]
    assert [r["_temporal_score"] for r in result] == [1.0, 1.0, 1.0]
    assert [r["_entity_overlap_score"] for r in result] == [1.0, 0.5, 0.0]
    assert all(r["_candidate_kind"] == "episode" for r in result)
    real_store.search_episodes_fts.assert_not_awaited()


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
