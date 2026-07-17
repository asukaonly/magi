"""Tests for L2 experience persistence."""

from __future__ import annotations

import json
import time

import pytest


async def _insert_episodic_summary(
    store,
    *,
    episode_id: str,
    content: str,
    period_start: float,
    period_end: float,
    key_topics: list[str] | None = None,
    key_entities: list[dict[str, str]] | None = None,
) -> None:
    from magi.core.sqlite import sqlite_connection_async

    now = time.time()
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute(
            """
            INSERT INTO summaries(
                summary_id, summary_type, summary_category,
                period_start, period_end, content,
                key_topics, key_entities, source_event_ids, source_event_count,
                generated_by_model, generation_reason, insight_metadata,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"summary-{episode_id}",
                "thematic",
                "episodic",
                period_start,
                period_end,
                content,
                "[]",
                "[]",
                "[]",
                0,
                "test",
                "test:episodic",
                json.dumps(
                    {
                        "source_episode_id": episode_id,
                        "key_topics": key_topics or [],
                        "key_entities": key_entities or [],
                    },
                    ensure_ascii=False,
                ),
                now,
                now,
            ),
        )
        await db.commit()


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
    assert (
        experience["magi_interpretation"] == "The user was choosing a future development workflow."
    )
    assert experience["narrative_score"] == 0.84
    assert experience["experience_type"] == "work"
    assert experience["primary_entity_ids"] == ["software:codex", "software:claude-code"]
    assert experience["primary_topic_keys"] == ["ai-coding"]
    assert experience["source_episode_count"] == 2
    assert experience["source_event_count"] == 5


@pytest.mark.asyncio
async def test_update_experience_cover_asset_ref(l2_store_with_schema):
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema
    await store.create_experience(
        experience_id="exp-japan",
        status="active",
        title="Japan trip",
        time_start=1000.0,
        time_end=2000.0,
    )

    updated = await store.update_experience(
        experience_id="exp-japan",
        user_cover_asset_ref="manual-entry-asset://cover.jpg",
    )
    experience = await store.get_experience(experience_id="exp-japan")

    assert updated is True
    assert experience is not None
    assert experience["user_cover_asset_ref"] == "manual-entry-asset://cover.jpg"


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
            {
                "member_type": "episode",
                "member_id": "ep-b",
                "role": "supporting",
                "confidence": 0.7,
            },
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
async def test_experience_promotion_requires_seed_for_single_strong_episode(l2_store_with_schema):
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

    assert stats.promoted == 0
    assert stats.rejected >= 1
    assert await store.list_experiences(status="active") == []


@pytest.mark.asyncio
async def test_experience_promotion_promotes_project_seed_from_concrete_anchor(
    l2_store_with_schema,
):
    from magi.memory.l2.experiences.promotion import promote_experiences_from_episodes
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema
    await store.create_episode(
        episode_id="ep-craft-debug",
        status="active",
        label="Debug CraftWorld automation",
        time_start=100.0,
        time_end=900.0,
        primary_entity_ids=["project:craftworld"],
        primary_topic_keys=["automation"],
        source_event_count=8,
    )
    await store.create_episode(
        episode_id="ep-craft-network",
        status="active",
        label="Adjust CraftWorld network config",
        time_start=1200.0,
        time_end=1800.0,
        primary_entity_ids=["project:craftworld", "software:google-gemini"],
        primary_topic_keys=["automation"],
        source_event_count=9,
    )
    await store.add_episode_events(
        episode_id="ep-craft-debug",
        event_ids=[f"debug-{index}" for index in range(8)],
    )
    await store.add_episode_events(
        episode_id="ep-craft-network",
        event_ids=[f"network-{index}" for index in range(9)],
    )

    stats = await promote_experiences_from_episodes(store)

    assert stats.promoted == 1
    assert len(stats.promoted_experience_ids) == 1
    experiences = await store.list_experiences(status="active")
    assert len(experiences) == 1
    experience = experiences[0]
    assert experience["title"] == "Craftworld"
    assert experience["source_seed_id"]
    assert experience["source_episode_count"] == 2
    assert experience["source_event_count"] == 17
    members = await store.list_experience_members(experience_id=experience["experience_id"])
    assert [member["member_id"] for member in members] == ["ep-craft-debug", "ep-craft-network"]
    seed = await store.get_experience_seed(seed_id=experience["source_seed_id"])
    assert seed is not None
    assert seed["status"] == "promoted"
    assert seed["promoted_experience_id"] == experience["experience_id"]


@pytest.mark.asyncio
async def test_experience_promotion_promotes_repeated_goal_seed_from_l3_summaries(
    l2_store_with_schema,
):
    from magi.memory.l2.experiences.promotion import promote_experiences_from_episodes
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema
    episodes = [
        (
            "ep-japan-route",
            100.0,
            500.0,
            "日本旅行前，把东京到京都的新干线车票和出发节奏定下来。",
        ),
        (
            "ep-japan-hotel",
            700.0,
            1100.0,
            "继续整理日本旅行，比较东京酒店、京都住宿和周边地图。",
        ),
        (
            "ep-japan-map",
            1300.0,
            1700.0,
            "围绕日本旅行查看 Google Maps，把奈良和大阪的路线串起来。",
        ),
    ]
    for index, (episode_id, start, end, summary) in enumerate(episodes):
        await store.create_episode(
            episode_id=episode_id,
            status="active",
            label="日本旅行",
            summary=summary,
            time_start=start,
            time_end=end,
            primary_entity_ids=["user:local_user", "software:chrome"],
            source_event_count=6,
        )
        await store.add_episode_events(
            episode_id=episode_id,
            event_ids=[f"japan-{index}-{event}" for event in range(6)],
        )

    stats = await promote_experiences_from_episodes(store)

    assert stats.promoted == 1
    experiences = await store.list_experiences(status="active")
    assert len(experiences) == 1
    experience = experiences[0]
    assert "日本旅行" in experience["title"]
    assert experience["source_episode_count"] == 3
    assert experience["source_event_count"] == 18
    assert "Chrome" not in experience["title"]
    members = await store.list_experience_members(experience_id=experience["experience_id"])
    assert [member["member_id"] for member in members] == [
        "ep-japan-route",
        "ep-japan-hotel",
        "ep-japan-map",
    ]


@pytest.mark.asyncio
async def test_experience_promotion_promotes_accepted_manual_seed(l2_store_with_schema):
    from magi.memory.l2.experiences.promotion import promote_experiences_from_episodes
    from magi.memory.l2.experiences.seed_discovery import discover_manual_experience_seed
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema
    await store.create_episode(
        episode_id="ep-train",
        status="active",
        label="Book Shinkansen tickets",
        summary="Compared Shinkansen routes for a Japan trip.",
        time_start=100.0,
        time_end=900.0,
        primary_entity_ids=["travel:shinkansen"],
        primary_topic_keys=["travel"],
        source_event_count=6,
    )
    await store.create_episode(
        episode_id="ep-map",
        status="active",
        label="Search Tokyo hotel map",
        time_start=1200.0,
        time_end=1800.0,
        primary_entity_ids=["place:tokyo"],
        primary_topic_keys=["travel"],
        source_event_count=5,
    )
    await store.add_episode_events(
        episode_id="ep-train",
        event_ids=[f"train-{index}" for index in range(6)],
    )
    await store.add_episode_events(
        episode_id="ep-map",
        event_ids=[f"map-{index}" for index in range(5)],
    )
    seed_id = await discover_manual_experience_seed(
        store,
        episode_id="ep-train",
        title="Japan trip planning",
    )

    stats = await promote_experiences_from_episodes(store)

    assert stats.promoted == 1
    experiences = await store.list_experiences(status="active")
    assert len(experiences) == 1
    experience = experiences[0]
    assert experience["title"] == "Japan trip planning"
    assert experience["source_seed_id"] == seed_id
    assert experience["magi_interpretation"] == "Compared Shinkansen routes for a Japan trip."
    members = await store.list_experience_members(experience_id=experience["experience_id"])
    assert [member["member_id"] for member in members] == ["ep-train", "ep-map"]


@pytest.mark.asyncio
@pytest.mark.parametrize("seed_status", ["stale", "rejected"])
async def test_targeted_experience_promotion_skips_inactive_seed(
    l2_store_with_schema,
    seed_status,
):
    from magi.memory.l2.experiences.promotion import promote_experiences_from_episodes
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema
    seed_id = await store.create_experience_seed(
        seed_id=f"seed-{seed_status}",
        seed_type="manual",
        status=seed_status,
        title="Private inactive seed",
        confidence=1.0,
        created_by="user",
    )

    stats = await promote_experiences_from_episodes(store, target_seed_id=seed_id)

    assert stats.promoted == 0
    assert await store.list_experiences(status="active") == []
    seed = await store.get_experience_seed(seed_id=seed_id)
    assert seed is not None
    assert seed["status"] == seed_status


@pytest.mark.asyncio
async def test_manual_experience_seed_rejects_invalidated_episode(l2_store_with_schema):
    from magi.memory.l2.experiences.seed_discovery import discover_manual_experience_seed
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema
    await store.create_episode(
        episode_id="ep-private",
        status="invalidated",
        time_start=100.0,
        time_end=200.0,
        summary="Private generated summary",
    )

    with pytest.raises(ValueError, match="not active"):
        await discover_manual_experience_seed(store, episode_id="ep-private")
    assert await store.list_experience_seeds(limit=20) == []


@pytest.mark.asyncio
async def test_forgotten_event_cannot_be_added_to_experience_seed(l2_store_with_schema):
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema
    await store.forget_source_events(["evt-private"], reason="user_delete_event")
    seed_id = await store.create_experience_seed(
        seed_id="seed-private-event",
        seed_type="manual",
        status="accepted",
        title="Private seed",
        created_by="user",
    )

    with pytest.raises(ValueError, match="forgotten"):
        await store.add_experience_seed_evidence(
            seed_id=seed_id,
            evidence=[{"ref_type": "event", "ref_id": "evt-private"}],
        )
    assert await store.list_experience_seed_evidence(seed_id=seed_id) == []


@pytest.mark.asyncio
async def test_stale_seed_cannot_create_validated_experience(l2_store_with_schema):
    from magi.memory.l2.experiences.seed_discovery import discover_manual_experience_seed
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema
    await store.create_episode(
        episode_id="ep-private-seed",
        status="active",
        time_start=100.0,
        time_end=200.0,
    )
    seed_id = await discover_manual_experience_seed(
        store,
        episode_id="ep-private-seed",
    )
    await store.forget_episode(episode_id="ep-private-seed")

    with pytest.raises(ValueError, match="not promotable"):
        await store.create_experience(
            experience_id="exp-private-seed",
            status="active",
            title="Private experience",
            time_start=100.0,
            time_end=200.0,
            source_seed_id=seed_id,
            validate_source_seed=True,
        )
    assert await store.get_experience(experience_id="exp-private-seed") is None


@pytest.mark.asyncio
async def test_forget_episode_stales_legacy_spaced_episode_group(l2_store_with_schema):
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema
    for episode_id in ("ep-group-a", "ep-group-private"):
        await store.create_episode(
            episode_id=episode_id,
            status="active",
            time_start=100.0,
            time_end=200.0,
        )
    seed_id = await store.create_experience_seed(
        seed_id="seed-spaced-group",
        seed_type="repeated_goal",
        status="candidate",
        title="Private grouped title",
        description="Private grouped description",
        source_ref_type="episode_group",
        source_ref_id="ep-group-a,ep-group-private",
    )
    from magi.core.sqlite import sqlite_connection_async

    async with sqlite_connection_async(store.db_path) as db:
        await db.execute(
            "UPDATE experience_seeds SET source_ref_id = ? WHERE seed_id = ?",
            ("ep-group-a,  ep-group-private", seed_id),
        )
        await db.commit()

    await store.forget_episode(episode_id="ep-group-private")

    seed = await store.get_experience_seed(seed_id=seed_id)
    assert seed is not None
    assert seed["status"] == "stale"
    assert seed["title"] is None
    assert seed["description"] is None
    assert seed["source_ref_type"] is None
    assert seed["source_ref_id"] is None


@pytest.mark.asyncio
async def test_experience_promotion_rejects_generic_adjacent_chain(l2_store_with_schema):
    from magi.memory.l2.experiences.promotion import promote_experiences_from_episodes
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema
    for index in range(2):
        await store.create_episode(
            episode_id=f"ep-generic-{index}",
            status="active",
            label="Browse Chrome",
            time_start=100.0 + index * 300.0,
            time_end=240.0 + index * 300.0,
            primary_entity_ids=["user:local_user", "software:chrome", "software:google"],
            primary_topic_keys=["browser"],
            source_event_count=80,
        )
        await store.add_episode_events(
            episode_id=f"ep-generic-{index}",
            event_ids=[f"generic-{index}-{event}" for event in range(80)],
        )

    stats = await promote_experiences_from_episodes(store)

    assert stats.promoted == 0
    assert stats.rejected >= 1
    assert await store.list_experiences(status="active") == []


@pytest.mark.asyncio
async def test_experience_promotion_rejects_source_only_seed_and_marks_it_rejected(
    l2_store_with_schema,
):
    from magi.memory.l2.experiences.promotion import promote_experiences_from_episodes
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema
    for index in range(3):
        episode_id = f"ep-browser-noise-{index}"
        await store.create_episode(
            episode_id=episode_id,
            status="active",
            label="Browse Chrome and Google Search",
            time_start=100.0 + index * 600.0,
            time_end=300.0 + index * 600.0,
            primary_entity_ids=["software:chrome", "software:google", "user:local_user"],
            primary_topic_keys=["browser"],
            source_event_count=20,
        )
        await store.add_episode_events(
            episode_id=episode_id,
            event_ids=[f"browser-noise-{index}-{event}" for event in range(20)],
        )
    seed_id = await store.create_experience_seed(
        seed_id="seed-browser-noise",
        seed_type="repeated_goal",
        status="candidate",
        title="Browser activity",
        anchor_entity_ids=["software:chrome", "software:google"],
        anchor_topic_keys=["browser"],
        time_start=100.0,
        time_end=1500.0,
        confidence=0.8,
        created_by="system",
    )
    await store.add_experience_seed_evidence(
        seed_id=seed_id,
        evidence=[
            {"ref_type": "episode", "ref_id": f"ep-browser-noise-{index}", "role": "support"}
            for index in range(3)
        ],
    )

    stats = await promote_experiences_from_episodes(store)

    assert stats.promoted == 0
    assert stats.rejected == 1
    assert await store.list_experiences(status="active") == []
    seed = await store.get_experience_seed(seed_id=seed_id)
    assert seed is not None
    assert seed["status"] == "rejected"
    assert seed["description"] == "Rejected: Seed has no concrete anchors."


@pytest.mark.asyncio
async def test_experience_promotion_rejects_technical_artifact_seed_before_creation(
    l2_store_with_schema,
):
    from magi.memory.l2.experiences.promotion import promote_experiences_from_episodes
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema
    for index in range(3):
        episode_id = f"ep-dev-script-{index}"
        await store.create_episode(
            episode_id=episode_id,
            status="active",
            label="Run dev-tauri-hot.sh and inspect backend-dev-hot.log",
            time_start=100.0 + index * 600.0,
            time_end=300.0 + index * 600.0,
            primary_entity_ids=["software:terminal"],
            primary_topic_keys=["dev-tauri-hot.sh"],
            source_event_count=8,
        )
        await store.add_episode_events(
            episode_id=episode_id,
            event_ids=[f"dev-script-{index}-{event}" for event in range(8)],
        )
    seed_id = await store.create_experience_seed(
        seed_id="seed-dev-script-candidate",
        seed_type="repeated_goal",
        status="candidate",
        title="Dev-tauri-hot.sh",
        anchor_topic_keys=["dev-tauri-hot.sh"],
        time_start=100.0,
        time_end=1500.0,
        confidence=0.88,
        created_by="system",
    )
    await store.add_experience_seed_evidence(
        seed_id=seed_id,
        evidence=[
            {"ref_type": "episode", "ref_id": f"ep-dev-script-{index}", "role": "support"}
            for index in range(3)
        ],
    )

    stats = await promote_experiences_from_episodes(store)

    assert stats.promoted == 0
    assert stats.rejected == 1
    assert await store.list_experiences(status="active") == []
    seed = await store.get_experience_seed(seed_id=seed_id)
    assert seed is not None
    assert seed["status"] == "rejected"
    assert seed["description"] == "Rejected: Technical artifact is not a user-facing experience."


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
    from magi.memory.l2.experiences.seed_discovery import discover_manual_experience_seed
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
    await discover_manual_experience_seed(
        store,
        episode_id="ep-existing",
        title="Evaluate AI coding tools",
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


@pytest.mark.asyncio
async def test_experience_promotion_hides_bad_legacy_experience(l2_store_with_schema):
    from magi.memory.l2.experiences.promotion import promote_experiences_from_episodes
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema
    await store.create_experience(
        experience_id="exp-legacy-bad",
        status="active",
        title="github / chrome / google",
        time_start=100.0,
        time_end=200.0,
        magi_interpretation="Magi grouped related episode evidence into a narratable memory.",
        primary_entity_ids=["user:local_user", "software:chrome", "software:google"],
        primary_topic_keys=["browser"],
        source_episode_count=8,
        source_event_count=400,
    )

    stats = await promote_experiences_from_episodes(store)

    assert stats.promoted == 0
    hidden = await store.get_experience(experience_id="exp-legacy-bad")
    assert hidden is not None
    assert hidden["status"] == "hidden"


@pytest.mark.asyncio
async def test_experience_promotion_hides_seeded_technical_artifact_experience(
    l2_store_with_schema,
):
    from magi.memory.l2.experiences.promotion import promote_experiences_from_episodes
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema
    seed_id = await store.create_experience_seed(
        seed_id="seed-dev-script",
        seed_type="repeated_goal",
        status="promoted",
        title="dev-tauri-hot.sh",
        anchor_topic_keys=["dev-tauri-hot.sh"],
        confidence=0.7,
    )
    await store.create_experience(
        experience_id="exp-dev-script",
        source_seed_id=seed_id,
        status="active",
        title="Dev-tauri-hot.sh",
        time_start=100.0,
        time_end=200.0,
        intent="Dev-tauri-hot.sh",
        primary_topic_keys=["dev-tauri-hot.sh"],
        source_episode_count=10,
        source_event_count=94,
    )

    stats = await promote_experiences_from_episodes(store)

    assert stats.promoted == 0
    hidden = await store.get_experience(experience_id="exp-dev-script")
    assert hidden is not None
    assert hidden["status"] == "hidden"
    seed = await store.get_experience_seed(seed_id=seed_id)
    assert seed is not None
    assert seed["status"] == "rejected"
