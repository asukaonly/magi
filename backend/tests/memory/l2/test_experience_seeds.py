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


def test_episode_seed_text_reads_local_label_and_summary_quotes():
    from magi.memory.l2.experiences.seed_features import _episode_seed_text

    episode = {
        "episode_id": "ep1",
        "user_label": "手动标注",
        "label": "日本旅行",
        "summary": "围绕「新干线车票」和东京住宿做准备。",
    }
    text = _episode_seed_text(episode)
    assert "手动标注" in text
    assert "日本旅行" in text
    assert "新干线车票" in text
    # Whole summary prose is not folded into clustering tokens.
    assert "东京住宿" not in text


def test_text_tokens_reject_source_noise_phrases():
    from magi.memory.l2.experiences.seed_anchors import _text_tokens

    # A label composed purely of source-noise vocabulary is not a seed token.
    assert _text_tokens("Browse Chrome and Google Search") == []
    # Concrete phrases survive.
    assert _text_tokens("Book Shinkansen tickets") == ["book shinkansen tickets"]


@pytest.mark.asyncio
async def test_discovers_repeated_goal_seed_from_backwritten_episode_summaries(
    l2_store_with_schema,
):
    from magi.memory.l2.experiences.seed_discovery import discover_experience_seeds
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
    for episode_id, start, end, summary in episodes:
        await store.create_episode(
            episode_id=episode_id,
            status="active",
            label="日本旅行",
            summary=summary,
            time_start=start,
            time_end=end,
            primary_entity_ids=["user:local_user", "software:chrome"],
            source_event_count=8,
        )

    stats = await discover_experience_seeds(store)

    assert stats.created == 1
    seeds = await store.list_experience_seeds(status="candidate", seed_type="repeated_goal")
    assert len(seeds) == 1
    assert "Chrome" not in seeds[0]["title"]
    assert seeds[0]["confidence"] >= 0.6
    evidence = await store.list_experience_seed_evidence(seed_id=seeds[0]["seed_id"])
    assert [item["ref_id"] for item in evidence] == [
        "ep-japan-route",
        "ep-japan-hotel",
        "ep-japan-map",
    ]


@pytest.mark.asyncio
async def test_repeated_goal_seed_rejects_source_noise_from_episode_labels(
    l2_store_with_schema,
):
    from magi.memory.l2.experiences.seed_discovery import discover_experience_seeds
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema
    summaries = [
        "Chrome 浏览 Google Search、GitHub 通知和 Gmail 收件箱。",
        "Chrome 浏览 X 时间线、Reddit 首页和 Google Search。",
        "Chrome 浏览 YouTube 首页、Gmail 邮件和 GitHub 通知。",
    ]
    for index, summary in enumerate(summaries):
        start = 100.0 + index * 600.0
        await store.create_episode(
            episode_id=f"ep-source-noise-{index}",
            status="active",
            label="Chrome",
            summary=summary,
            time_start=start,
            time_end=start + 300.0,
            primary_entity_ids=[
                "user:local_user",
                "software:chrome",
                "software:google",
                "software:github",
                "software:gmail",
            ],
            source_event_count=20,
        )

    stats = await discover_experience_seeds(store)

    assert stats.created == 0
    assert await store.list_experience_seeds(statuses=["candidate", "accepted"]) == []


@pytest.mark.asyncio
async def test_repeated_goal_seed_rejects_technical_artifact_topic(
    l2_store_with_schema,
):
    from magi.memory.l2.experiences.seed_discovery import discover_experience_seeds
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema
    summaries = [
        "Terminal History 里多次运行 dev-tauri-hot.sh 并查看 backend-dev-hot.log。",
        "继续围绕 dev-tauri-hot.sh 重启本地开发服务，检查日志输出。",
        "清理 backend-dev-hot.log 后再次运行 dev-tauri-hot.sh。",
    ]
    for index, summary in enumerate(summaries):
        start = 100.0 + index * 600.0
        episode_id = f"ep-dev-script-{index}"
        await store.create_episode(
            episode_id=episode_id,
            status="active",
            label="dev-tauri-hot.sh",
            summary=summary,
            time_start=start,
            time_end=start + 300.0,
            primary_entity_ids=["software:terminal"],
            source_event_count=8,
        )

    stats = await discover_experience_seeds(store)

    assert stats.created == 0
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


@pytest.mark.asyncio
async def test_seed_recall_includes_triggers_and_caps_raw_events(l2_store_with_schema):
    from magi.memory.l2.experiences.seed_recall import recall_candidate_evidence_for_seed
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema
    await store.create_episode(
        episode_id="ep-train",
        status="active",
        label="Book Shinkansen tickets",
        time_start=100.0,
        time_end=200.0,
        primary_entity_ids=["travel:shinkansen"],
        primary_topic_keys=["travel"],
        source_event_count=30,
    )
    await store.create_episode(
        episode_id="ep-map",
        status="active",
        label="Search Tokyo hotel map",
        time_start=260.0,
        time_end=320.0,
        primary_entity_ids=["place:tokyo"],
        primary_topic_keys=["travel"],
        source_event_count=3,
    )
    await store.create_episode(
        episode_id="ep-mc",
        status="active",
        label="Watch redstone minecart video",
        time_start=330.0,
        time_end=380.0,
        primary_entity_ids=["game:minecraft"],
        primary_topic_keys=["redstone"],
        source_event_count=2,
    )
    await store.add_episode_events(
        episode_id="ep-train",
        event_ids=[f"train-{index}" for index in range(30)],
    )
    await store.add_episode_events(episode_id="ep-map", event_ids=["map-1", "map-2", "map-3"])
    await store.add_episode_events(episode_id="ep-mc", event_ids=["mc-1", "mc-2"])
    seed_id = await store.create_experience_seed(
        seed_id="seed-japan-recall",
        seed_type="manual",
        status="accepted",
        title="Japan trip planning",
        anchor_entity_ids=["travel:shinkansen", "place:tokyo"],
        anchor_topic_keys=["travel"],
        time_start=100.0,
        time_end=320.0,
        confidence=0.9,
        created_by="user",
    )
    await store.add_experience_seed_evidence(
        seed_id=seed_id,
        evidence=[{"ref_type": "episode", "ref_id": "ep-train", "role": "trigger"}],
    )

    pack = await recall_candidate_evidence_for_seed(
        store,
        seed_id=seed_id,
        window_seconds=600,
        raw_event_limit=10,
    )

    assert pack["trigger_episode_ids"] == ["ep-train"]
    assert [episode["episode_id"] for episode in pack["candidate_episodes"]] == [
        "ep-train",
        "ep-map",
        "ep-mc",
    ]
    assert len(pack["candidate_event_ids"]) == 10


@pytest.mark.asyncio
async def test_seed_selection_can_exclude_unrelated_interlude(l2_store_with_schema):
    from magi.memory.l2.experiences.seed_recall import recall_candidate_evidence_for_seed
    from magi.memory.l2.experiences.seed_selection import select_experience_from_seed
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema
    for episode_id, label, entity, topic, start in [
        ("ep-train", "Book Shinkansen tickets", "travel:shinkansen", "travel", 100.0),
        ("ep-map", "Search Tokyo hotel map", "place:tokyo", "travel", 260.0),
        ("ep-mc", "Watch redstone minecart video", "game:minecraft", "redstone", 330.0),
    ]:
        await store.create_episode(
            episode_id=episode_id,
            status="active",
            label=label,
            time_start=start,
            time_end=start + 50.0,
            primary_entity_ids=[entity],
            primary_topic_keys=[topic],
            source_event_count=3,
        )
    seed_id = await store.create_experience_seed(
        seed_id="seed-japan-selection",
        seed_type="manual",
        status="accepted",
        title="Japan trip planning",
        anchor_entity_ids=["travel:shinkansen", "place:tokyo"],
        anchor_topic_keys=["travel"],
        time_start=100.0,
        time_end=320.0,
        confidence=0.9,
        created_by="user",
    )
    await store.add_experience_seed_evidence(
        seed_id=seed_id,
        evidence=[{"ref_type": "episode", "ref_id": "ep-train", "role": "trigger"}],
    )

    pack = await recall_candidate_evidence_for_seed(store, seed_id=seed_id, window_seconds=600)

    def selector(seed, evidence_pack):
        return {
            "is_experience": True,
            "title": "Japan trip planning",
            "one_sentence_review": "你在车票、地图和住宿之间整理日本旅行计划。",
            "included_episode_ids": ["ep-train", "ep-map"],
            "included_event_ids": [],
            "excluded_refs": [{"ref_type": "episode", "ref_id": "ep-mc", "reason": "Minecraft interlude"}],
            "time_start": 100.0,
            "time_end": 320.0,
            "confidence": 0.86,
            "reason": "Travel planning evidence forms a coherent experience.",
        }

    selection = await select_experience_from_seed(seed=pack["seed"], evidence_pack=pack, selector=selector)

    assert selection.is_experience is True
    assert selection.included_episode_ids == ["ep-train", "ep-map"]
    assert selection.excluded_refs == [
        {"ref_type": "episode", "ref_id": "ep-mc", "reason": "Minecraft interlude"}
    ]
    assert selection.one_sentence_review == "你在车票、地图和住宿之间整理日本旅行计划。"


@pytest.mark.asyncio
async def test_default_selection_rejects_generic_only_candidate(l2_store_with_schema):
    from magi.memory.l2.experiences.seed_recall import recall_candidate_evidence_for_seed
    from magi.memory.l2.experiences.seed_selection import select_experience_from_seed
    from magi.memory.l2.store import L2CognitionStore

    store: L2CognitionStore = l2_store_with_schema
    await store.create_episode(
        episode_id="ep-chrome",
        status="active",
        label="Browse Chrome tabs",
        time_start=100.0,
        time_end=160.0,
        primary_entity_ids=["software:chrome", "user:local_user"],
        primary_topic_keys=["browser"],
        source_event_count=40,
    )
    seed_id = await store.create_experience_seed(
        seed_id="seed-generic-only",
        seed_type="repeated_goal",
        status="candidate",
        title="Browser activity",
        time_start=100.0,
        time_end=160.0,
        confidence=0.35,
        created_by="system",
    )
    await store.add_experience_seed_evidence(
        seed_id=seed_id,
        evidence=[{"ref_type": "episode", "ref_id": "ep-chrome", "role": "candidate"}],
    )

    pack = await recall_candidate_evidence_for_seed(store, seed_id=seed_id)
    selection = await select_experience_from_seed(seed=pack["seed"], evidence_pack=pack)

    assert selection.is_experience is False
    assert selection.included_episode_ids == []
