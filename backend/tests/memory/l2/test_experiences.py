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
