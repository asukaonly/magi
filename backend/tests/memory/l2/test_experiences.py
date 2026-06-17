"""Tests for L2 experience persistence."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_create_list_and_get_experience(l2_store_with_schema):
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema
    await store.create_experience(
        experience_id="exp-ai-tools",
        status="active",
        title="Evaluate AI coding tools",
        time_start=1000.0,
        time_end=2000.0,
        intent="Compare coding assistants",
        outcome="Narrowed the next tool choices",
        magi_interpretation="The user was choosing a future development workflow.",
        narrative_score=0.84,
        experience_type="work",
        primary_entity_ids=["software:codex", "software:claude-code"],
        primary_topic_keys=["ai-coding"],
        source_episode_count=2,
        source_event_count=5,
    )
    await store.create_experience(
        experience_id="exp-old",
        status="hidden",
        title="Hidden older memory",
        time_start=100.0,
        time_end=200.0,
    )

    active = await store.list_experiences(status="active")

    assert [item["experience_id"] for item in active] == ["exp-ai-tools"]
    experience = await store.get_experience(experience_id="exp-ai-tools")
    assert experience is not None
    assert experience["title"] == "Evaluate AI coding tools"
    assert experience["status"] == "active"
    assert experience["time_start"] == 1000.0
    assert experience["time_end"] == 2000.0
    assert experience["intent"] == "Compare coding assistants"
    assert experience["outcome"] == "Narrowed the next tool choices"
    assert experience["magi_interpretation"] == "The user was choosing a future development workflow."
    assert experience["narrative_score"] == 0.84
    assert experience["experience_type"] == "work"
    assert experience["primary_entity_ids"] == ["software:codex", "software:claude-code"]
    assert experience["primary_topic_keys"] == ["ai-coding"]
    assert experience["source_episode_count"] == 2
    assert experience["source_event_count"] == 5


@pytest.mark.asyncio
async def test_experience_memberships_recompute_counts_from_source_episodes(l2_store_with_schema):
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema
    await store.create_episode(
        episode_id="ep-a",
        status="active",
        time_start=10.0,
        time_end=20.0,
        source_event_count=0,
    )
    await store.create_episode(
        episode_id="ep-b",
        status="active",
        time_start=30.0,
        time_end=50.0,
        source_event_count=0,
    )
    await store.add_episode_events(episode_id="ep-a", event_ids=["evt-1", "evt-2"])
    await store.add_episode_events(episode_id="ep-b", event_ids=["evt-2", "evt-3", "evt-4"])
    await store.create_experience(
        experience_id="exp",
        status="active",
        title="Debug project",
        time_start=10.0,
        time_end=50.0,
    )

    added = await store.add_experience_members(
        experience_id="exp",
        members=[
            {"member_type": "episode", "member_id": "ep-a", "role": "core", "confidence": 0.9},
            {"member_type": "episode", "member_id": "ep-b", "role": "supporting", "confidence": 0.7},
        ],
    )
    counts = await store.recompute_experience_counts(experience_id="exp")

    assert added == 2
    assert await store.count_experience_members(experience_id="exp") == 2
    assert counts == {"source_episode_count": 2, "source_event_count": 4}
    updated = await store.get_experience(experience_id="exp")
    assert updated is not None
    assert updated["source_episode_count"] == 2
    assert updated["source_event_count"] == 4

    members = await store.list_experience_members(experience_id="exp")
    assert [(item["member_type"], item["member_id"], item["role"]) for item in members] == [
        ("episode", "ep-a", "core"),
        ("episode", "ep-b", "supporting"),
    ]


@pytest.mark.asyncio
async def test_list_experiences_orders_newest_first(l2_store_with_schema):
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema
    await store.create_experience(
        experience_id="older",
        status="active",
        title="Older",
        time_start=100.0,
        time_end=150.0,
    )
    await store.create_experience(
        experience_id="newer",
        status="active",
        title="Newer",
        time_start=200.0,
        time_end=250.0,
    )

    items = await store.list_experiences(status="active")

    assert [item["experience_id"] for item in items] == ["newer", "older"]


@pytest.mark.asyncio
async def test_promote_single_strong_episode_to_experience(l2_store_with_schema):
    from magi.memory.l2.experiences.promotion import promote_experiences_from_episodes
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema
    await store.create_episode(
        episode_id="ep-craft",
        status="active",
        label="Debug CraftWorld module",
        summary="Adjusted automated task parameters and network configuration.",
        time_start=100.0,
        time_end=3700.0,
        primary_entity_ids=["project:craftworld", "software:google-gemini"],
        primary_topic_keys=["debugging"],
        source_event_count=25,
    )
    await store.add_episode_events(
        episode_id="ep-craft",
        event_ids=[f"evt-{index}" for index in range(25)],
    )

    stats = await promote_experiences_from_episodes(store)

    assert stats.promoted == 1
    assert len(stats.promoted_experience_ids) == 1
    experiences = await store.list_experiences(status="active")
    assert len(experiences) == 1
    experience = experiences[0]
    assert experience["experience_id"] == stats.promoted_experience_ids[0]
    assert experience["title"] == "Debug CraftWorld module"
    assert experience["intent"] == "Debug CraftWorld module"
    assert experience["source_episode_count"] == 1
    assert experience["source_event_count"] == 25
    members = await store.list_experience_members(experience_id=experience["experience_id"])
    assert [(member["member_type"], member["member_id"], member["role"]) for member in members] == [
        ("episode", "ep-craft", "core")
    ]


@pytest.mark.asyncio
async def test_promote_adjacent_same_theme_episodes_to_one_experience(l2_store_with_schema):
    from magi.memory.l2.experiences.promotion import promote_experiences_from_episodes
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema
    await store.create_episode(
        episode_id="ep-claude",
        status="active",
        label="Research assistant history",
        time_start=100.0,
        time_end=900.0,
        primary_entity_ids=["software:claude-code"],
        primary_topic_keys=["ai-coding"],
        source_event_count=6,
    )
    await store.create_episode(
        episode_id="ep-codex",
        status="active",
        label="Compare coding tool usage",
        time_start=1200.0,
        time_end=1800.0,
        primary_entity_ids=["software:codex"],
        primary_topic_keys=["ai-coding"],
        source_event_count=7,
    )
    await store.add_episode_events(
        episode_id="ep-claude",
        event_ids=[f"claude-{index}" for index in range(6)],
    )
    await store.add_episode_events(
        episode_id="ep-codex",
        event_ids=[f"codex-{index}" for index in range(7)],
    )

    stats = await promote_experiences_from_episodes(store)

    assert stats.promoted == 1
    assert len(stats.promoted_experience_ids) == 1
    experiences = await store.list_experiences(status="active")
    assert len(experiences) == 1
    experience = experiences[0]
    assert experience["title"] == "Research assistant history / Compare coding tool usage"
    assert experience["source_episode_count"] == 2
    assert experience["source_event_count"] == 13
    members = await store.list_experience_members(experience_id=experience["experience_id"])
    assert [member["member_id"] for member in members] == ["ep-claude", "ep-codex"]


@pytest.mark.asyncio
async def test_experience_promotion_rejects_sparse_generic_episode(l2_store_with_schema):
    from magi.memory.l2.experiences.promotion import promote_experiences_from_episodes
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema
    await store.create_episode(
        episode_id="ep-noise",
        status="active",
        label="Browse random pages",
        time_start=100.0,
        time_end=200.0,
        source_event_count=3,
    )
    await store.add_episode_events(episode_id="ep-noise", event_ids=["e1", "e2", "e3"])

    stats = await promote_experiences_from_episodes(store)

    assert stats.promoted == 0
    assert stats.rejected >= 1
    assert await store.list_experiences(status="active") == []


@pytest.mark.asyncio
async def test_experience_promotion_suppresses_existing_duplicate(l2_store_with_schema):
    from magi.memory.l2.experiences.promotion import promote_experiences_from_episodes
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema
    await store.create_episode(
        episode_id="ep-existing",
        status="active",
        label="Evaluate AI coding tools",
        time_start=100.0,
        time_end=4000.0,
        primary_entity_ids=["software:codex", "software:claude-code"],
        primary_topic_keys=["ai-coding"],
        source_event_count=30,
    )
    await store.add_episode_events(
        episode_id="ep-existing",
        event_ids=[f"evt-{index}" for index in range(30)],
    )
    await store.create_experience(
        experience_id="exp-existing",
        status="active",
        title="Evaluate AI coding tools",
        time_start=100.0,
        time_end=4000.0,
        source_episode_count=1,
        source_event_count=30,
    )
    await store.add_experience_members(
        experience_id="exp-existing",
        members=[{"member_type": "episode", "member_id": "ep-existing", "role": "core"}],
    )

    stats = await promote_experiences_from_episodes(store)

    assert stats.promoted == 0
    assert stats.skipped_duplicates == 1
    experiences = await store.list_experiences(status="active")
    assert [experience["experience_id"] for experience in experiences] == ["exp-existing"]
