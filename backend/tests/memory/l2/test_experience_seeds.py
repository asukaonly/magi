"""Tests for L2 experience seed persistence."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_create_list_update_seed_and_attach_to_experience(l2_store_with_schema):
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema

    seed_id = await store.create_experience_seed(
        seed_id="seed-japan-trip",
        seed_type="manual",
        status="candidate",
        title="Japan trip",
        description="User selected notes about planning and taking a Japan trip.",
        anchor_entity_ids=["place:japan", "travel:shinkansen"],
        anchor_topic_keys=["travel"],
        time_start=100.0,
        time_end=500.0,
        confidence=0.7,
        created_by="user",
    )
    await store.add_experience_seed_evidence(
        seed_id=seed_id,
        evidence=[
            {
                "ref_type": "episode",
                "ref_id": "ep-train-ticket",
                "role": "trigger",
                "confidence": 0.9,
                "reason": "User selected this episode as the starting point.",
            },
            {
                "ref_type": "episode",
                "ref_id": "ep-google-map",
                "role": "support",
                "confidence": 0.65,
                "reason": "Nearby travel planning evidence.",
            },
        ],
    )
    duplicate_count = await store.add_experience_seed_evidence(
        seed_id=seed_id,
        evidence=[
            {
                "ref_type": "episode",
                "ref_id": "ep-google-map",
                "role": "support",
                "confidence": 0.65,
            }
        ],
    )

    assert duplicate_count == 0
    seeds = await store.list_experience_seeds(status="candidate")
    assert [seed["seed_id"] for seed in seeds] == [seed_id]
    seed = await store.get_experience_seed(seed_id=seed_id)
    assert seed is not None
    assert seed["seed_type"] == "manual"
    assert seed["title"] == "Japan trip"
    assert seed["anchor_entity_ids"] == ["place:japan", "travel:shinkansen"]
    assert seed["anchor_topic_keys"] == ["travel"]
    assert seed["confidence"] == 0.7
    assert seed["created_by"] == "user"

    evidence = await store.list_experience_seed_evidence(seed_id=seed_id)
    assert [(item["ref_type"], item["ref_id"], item["role"]) for item in evidence] == [
        ("episode", "ep-train-ticket", "trigger"),
        ("episode", "ep-google-map", "support"),
    ]

    updated = await store.update_experience_seed(seed_id=seed_id, status="accepted", confidence=0.82)
    assert updated is True
    updated_seed = await store.get_experience_seed(seed_id=seed_id)
    assert updated_seed is not None
    assert updated_seed["status"] == "accepted"
    assert updated_seed["confidence"] == 0.82

    await store.create_experience(
        experience_id="exp-japan-trip",
        source_seed_id=seed_id,
        status="active",
        title="Japan trip",
        time_start=100.0,
        time_end=500.0,
    )
    experience = await store.get_experience(experience_id="exp-japan-trip")
    assert experience is not None
    assert experience["source_seed_id"] == seed_id


@pytest.mark.asyncio
async def test_manual_seed_uses_selected_episode_as_trigger(l2_store_with_schema):
    from magi.memory.l2.experiences.seed_discovery import discover_manual_experience_seed
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema
    await store.create_episode(
        episode_id="ep-japan-rail",
        status="active",
        label="Plan Japan rail route",
        summary="Compared Shinkansen tickets and Tokyo hotel options.",
        time_start=100.0,
        time_end=400.0,
        primary_entity_ids=["place:japan", "travel:shinkansen"],
        primary_topic_keys=["travel"],
        source_event_count=12,
    )

    seed_id = await discover_manual_experience_seed(
        store,
        episode_id="ep-japan-rail",
        title="Japan trip planning",
    )

    seed = await store.get_experience_seed(seed_id=seed_id)
    assert seed is not None
    assert seed["seed_type"] == "manual"
    assert seed["status"] == "accepted"
    assert seed["title"] == "Japan trip planning"
    assert seed["time_start"] == 100.0
    assert seed["time_end"] == 400.0
    assert seed["anchor_entity_ids"] == ["place:japan", "travel:shinkansen"]

    evidence = await store.list_experience_seed_evidence(seed_id=seed_id)
    assert [(item["ref_type"], item["ref_id"], item["role"]) for item in evidence] == [
        ("episode", "ep-japan-rail", "trigger")
    ]


@pytest.mark.asyncio
async def test_discovers_project_seed_from_repeated_concrete_anchor(l2_store_with_schema):
    from magi.memory.l2.experiences.seed_discovery import discover_experience_seeds
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema
    await store.create_episode(
        episode_id="ep-craft-debug",
        status="active",
        label="Debug CraftWorld automation",
        time_start=100.0,
        time_end=200.0,
        primary_entity_ids=["project:craftworld"],
        primary_topic_keys=["automation"],
        source_event_count=8,
    )
    await store.create_episode(
        episode_id="ep-craft-network",
        status="active",
        label="Adjust CraftWorld network config",
        time_start=500.0,
        time_end=900.0,
        primary_entity_ids=["project:craftworld", "software:google-gemini"],
        primary_topic_keys=["automation"],
        source_event_count=9,
    )

    stats = await discover_experience_seeds(store)

    assert stats.created == 1
    seeds = await store.list_experience_seeds(status="candidate", seed_type="project")
    assert len(seeds) == 1
    assert seeds[0]["title"] == "Craftworld"
    assert seeds[0]["anchor_entity_ids"] == ["project:craftworld"]
    evidence = await store.list_experience_seed_evidence(seed_id=seeds[0]["seed_id"])
    assert [item["ref_id"] for item in evidence] == ["ep-craft-debug", "ep-craft-network"]


@pytest.mark.asyncio
async def test_does_not_discover_seed_from_only_generic_anchors(l2_store_with_schema):
    from magi.memory.l2.experiences.seed_discovery import discover_experience_seeds
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema
    for index in range(2):
        await store.create_episode(
            episode_id=f"ep-generic-{index}",
            status="active",
            label="Browse Chrome",
            time_start=100.0 + index * 200.0,
            time_end=180.0 + index * 200.0,
            primary_entity_ids=["user:local_user", "software:chrome", "software:google"],
            primary_topic_keys=["browser"],
            source_event_count=50,
        )

    stats = await discover_experience_seeds(store)

    assert stats.created == 0
    assert stats.skipped_generic >= 1
    assert await store.list_experience_seeds(statuses=["candidate", "accepted"]) == []


@pytest.mark.asyncio
async def test_repeated_goal_selector_creates_candidate_for_weak_chrome_only_seed(
    l2_store_with_schema,
):
    from magi.memory.l2.experiences.seed_discovery import discover_experience_seeds
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema
    await store.create_episode(
        episode_id="ep-chrome-reading",
        status="active",
        label="Read scattered browser tabs",
        time_start=100.0,
        time_end=240.0,
        primary_entity_ids=["software:chrome"],
        primary_topic_keys=["browser"],
        source_event_count=4,
    )

    def selector(episodes):
        return [
            {
                "title": "Scattered browser reading",
                "description": "Weak repeated browsing pattern.",
                "episode_ids": ["ep-chrome-reading"],
                "confidence": 0.35,
            }
        ]

    stats = await discover_experience_seeds(store, repeated_goal_selector=selector)

    assert stats.created == 1
    seeds = await store.list_experience_seeds(status="candidate", seed_type="repeated_goal")
    assert len(seeds) == 1
    assert seeds[0]["title"] == "Scattered browser reading"
    assert seeds[0]["confidence"] == 0.35
    assert seeds[0]["anchor_entity_ids"] == []
