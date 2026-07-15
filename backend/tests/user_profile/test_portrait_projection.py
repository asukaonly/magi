from __future__ import annotations

import sqlite3

from _shared.memory_schema import apply_memory_shared_schema
from magi.memory.l2.store import L2CognitionStore
from magi.user_profile.models import UserPortraitProjection, UserProfileProjection
from magi.user_profile.portrait_projection_builder import UserPortraitProjectionBuilder
from magi.user_profile.portrait_projection_repository import UserPortraitProjectionRepository
from magi.user_profile.projection_repository import UserProfileProjectionRepository


class _FakeL2:
    async def list_current_assertions(self, **kwargs):
        return [
            {
                "assertion_id": "a-interest-rag",
                "trait_family": "interest_profile",
                "trait_name": "interest.rag",
                "trait_value": "RAG",
                "source_domain": "external_activity",
                "validation_state": "corroborated",
                "confidence_score": 0.86,
                "evidence_events": ["event-1", "event-2", "event-3"],
                "last_validated_at": 1_700_000_001,
                "temporal_scope": "recent",
            },
            {
                "assertion_id": "a-interest-magi",
                "trait_family": "interest_profile",
                "trait_name": "interest.magi_memory",
                "trait_value": "Magi 记忆系统",
                "source_domain": "conversation",
                "validation_state": "stable",
                "confidence_score": 0.93,
                "evidence_events": ["event-4", "event-5"],
                "last_validated_at": 1_700_000_002,
                "temporal_scope": "stable",
            },
            {
                "assertion_id": "a-communication",
                "trait_family": "communication_profile",
                "trait_name": "communication.answer_style",
                "trait_value": "先讲结论，再讲原因",
                "source_domain": "user_authored",
                "validation_state": "stable",
                "confidence_score": 1.0,
                "evidence_events": ["event-6"],
                "last_validated_at": 1_700_000_003,
                "temporal_scope": "stable",
            },
            {
                "assertion_id": "a-review",
                "trait_family": "project_profile",
                "trait_name": "interest.one_off",
                "trait_value": "一次性页面标题",
                "source_domain": "external_activity",
                "validation_state": "tentative",
                "confidence_score": 0.5,
                "evidence_events": ["event-7"],
                "last_validated_at": 1_700_000_004,
                "temporal_scope": "stable",
            },
            {
                "assertion_id": "a-state",
                "trait_family": "state_profile",
                "trait_name": "current_focus",
                "trait_value": "验证 L2 断言和画像质量",
                "source_domain": "conversation",
                "validation_state": "stable",
                "confidence_score": 0.9,
                "evidence_events": ["event-8"],
                "last_validated_at": 1_700_000_005,
                "temporal_scope": "recent",
            },
        ]

    async def list_tom_snapshots(self, **kwargs):
        return [
            {
                "snapshot_id": "snap-1",
                "entity_id": "user:local_user",
                "entity_type": "user",
                "core_traits": {"近期线索": "正在检查画像投影效果"},
                "preferences": {
                    "interest.raw": {
                        "value": "不应直出",
                        "affinity": 1.0,
                        "family": "preference_profile",
                        "source_tier": "inferred",
                    }
                },
                "last_updated_at": 1_700_000_010,
            }
        ]


class _PassiveProfileSignalL2:
    async def list_current_assertions(self, **kwargs):
        return [
            {
                "assertion_id": "a-weak-passive",
                "trait_family": "interest_profile",
                "trait_name": "interest.deepseek",
                "trait_value": "DeepSeek",
                "source_domain": "external_activity",
                "validation_state": "stable",
                "confidence_score": 0.82,
                "evidence_events": ["event-1"],
                "temporal_scope": "recent",
            },
            {
                "assertion_id": "a-mismatched-passive",
                "trait_family": "preference_profile",
                "trait_name": "tool.chrome",
                "trait_value": "Chrome",
                "source_domain": "external_activity",
                "validation_state": "stable",
                "confidence_score": 0.9,
                "evidence_events": ["event-2", "event-3", "event-4", "event-5"],
                "temporal_scope": "stable",
            },
            {
                "assertion_id": "a-strong-passive",
                "trait_family": "interest_profile",
                "trait_name": "interest.rag",
                "trait_value": "RAG",
                "source_domain": "external_activity",
                "validation_state": "stable",
                "confidence_score": 0.9,
                "evidence_events": ["event-6", "event-7", "event-8"],
                "temporal_scope": "stable",
            },
            {
                "assertion_id": "a-user-authored",
                "trait_family": "interest_profile",
                "trait_name": "interest.magi_memory",
                "trait_value": "Magi 记忆系统",
                "source_domain": "user_authored",
                "validation_state": "stable",
                "confidence_score": 0.95,
                "evidence_events": ["event-9"],
                "temporal_scope": "stable",
            },
        ]

    async def list_tom_snapshots(self, **kwargs):
        return []


class _ConfirmedPassiveSignalL2:
    async def list_current_assertions(self, **kwargs):
        return [
            {
                "assertion_id": "a-confirmed-passive",
                "trait_family": "interest_profile",
                "trait_name": "interest.deepseek",
                "trait_value": "DeepSeek",
                "source_domain": "external_activity",
                "validation_state": "stable",
                "user_feedback": "confirmed",
                "confidence_score": 0.9,
                "evidence_events": ["event-1"],
                "temporal_scope": "stable",
            },
        ]

    async def list_tom_snapshots(self, **kwargs):
        return []


class _FragmentedProfileSignalL2:
    async def list_current_assertions(self, **kwargs):
        return [
            {
                "assertion_id": "a-project",
                "trait_family": "project_profile",
                "trait_name": "project.magi_memory",
                "trait_value": "Magi 记忆系统",
                "source_domain": "conversation",
                "validation_state": "stable",
                "confidence_score": 0.92,
                "evidence_events": ["event-1", "event-2", "event-3"],
                "temporal_scope": "stable",
            },
            {
                "assertion_id": "a-interest-plugin",
                "trait_family": "interest_profile",
                "trait_name": "interest.plugin_ecosystem",
                "trait_value": "插件生态",
                "source_domain": "conversation",
                "validation_state": "stable",
                "confidence_score": 0.9,
                "evidence_events": ["event-4", "event-5"],
                "temporal_scope": "stable",
            },
            {
                "assertion_id": "a-tool-codex",
                "trait_family": "routine_profile",
                "trait_name": "routine.tool.codex",
                "trait_value": "Codex",
                "source_domain": "conversation",
                "validation_state": "stable",
                "confidence_score": 0.88,
                "evidence_events": ["event-6", "event-7"],
                "temporal_scope": "stable",
            },
            {
                "assertion_id": "a-communication",
                "trait_family": "communication_profile",
                "trait_name": "communication.answer_style",
                "trait_value": "先讲结论，再补关键依据",
                "source_domain": "user_authored",
                "validation_state": "stable",
                "confidence_score": 1.0,
                "evidence_events": ["event-8"],
                "temporal_scope": "stable",
            },
            {
                "assertion_id": "a-weak-passive",
                "trait_family": "interest_profile",
                "trait_name": "interest.one_off_page",
                "trait_value": "一次性页面",
                "source_domain": "external_activity",
                "validation_state": "stable",
                "confidence_score": 0.8,
                "evidence_events": ["event-9"],
                "temporal_scope": "recent",
            },
        ]

    async def list_tom_snapshots(self, **kwargs):
        return []


async def test_portrait_projection_repository_roundtrips_prompt_and_page_model(tmp_path):
    db_path = tmp_path / "memory.db"
    repo = UserPortraitProjectionRepository(str(db_path))
    projection = UserPortraitProjection(
        user_id="local_user",
        entity_id="user:local_user",
        world={"groups": [{"id": "preferences", "items": [{"text": "RAG"}]}]},
        review={"items": []},
        recent={"items": []},
        prompt_summary=["用户关注 RAG。"],
        evidence_refs=["assertion:a-interest-rag"],
        source_counts={"conversation": 1},
        generated_by="rule",
    )

    saved = await repo.upsert(projection)
    loaded = await repo.get("local_user")

    assert loaded is not None
    assert loaded.user_id == saved.user_id
    assert loaded.world["groups"][0]["items"][0]["text"] == "RAG"
    assert loaded.prompt_summary == ["用户关注 RAG。"]
    assert loaded.evidence_refs == ["assertion:a-interest-rag"]
    assert loaded.source_counts == {"conversation": 1}
    with sqlite3.connect(db_path) as db:
        columns = {
            str(row[1])
            for row in db.execute("PRAGMA table_info(user_portrait_projection)")
        }
    assert "version" not in columns


async def test_portrait_projection_builder_filters_internal_fields_and_separates_review():
    projection = await UserPortraitProjectionBuilder(_FakeL2()).build("local_user")

    prompt_text = "\n".join(projection.prompt_summary)
    assert "interest." not in prompt_text
    assert "affinity" not in prompt_text
    assert "source_tier" not in prompt_text
    assert "external_activity" not in prompt_text
    assert "Magi 记忆系统" in prompt_text
    assert "先讲结论" in prompt_text

    world_groups = {group["id"]: group["items"] for group in projection.world["groups"]}
    assert [item["text"] for item in world_groups["preferences"]] == ["Magi 记忆系统"]
    assert [item["text"] for item in world_groups["work_style"]] == ["先讲结论，再讲原因"]
    assert [item["text"] for item in projection.review["items"]] == ["一次性页面标题"]
    assert [item["text"] for item in projection.recent["items"]] == [
        "RAG",
        "验证 L2 断言和画像质量",
    ]
    assert "assertion:a-interest-rag" in projection.evidence_refs


async def test_portrait_projection_requires_world_ready_profile_assertions():
    projection = await UserPortraitProjectionBuilder(_PassiveProfileSignalL2()).build("local_user")

    world_groups = {group["id"]: group["items"] for group in projection.world["groups"]}
    preference_texts = [item["text"] for item in world_groups["preferences"]]
    prompt_text = "\n".join(projection.prompt_summary)

    assert preference_texts == ["Magi 记忆系统", "RAG"]
    assert "DeepSeek" not in preference_texts
    assert "Chrome" not in preference_texts
    assert "DeepSeek" in [item["text"] for item in projection.recent["items"]]
    assert "DeepSeek" in prompt_text
    assert "Chrome" not in prompt_text


async def test_portrait_projection_treats_confirmed_feedback_as_user_qualified():
    projection = await UserPortraitProjectionBuilder(_ConfirmedPassiveSignalL2()).build("local_user")

    world_groups = {group["id"]: group["items"] for group in projection.world["groups"]}
    assert [item["text"] for item in world_groups["preferences"]] == ["DeepSeek"]
    assert "DeepSeek" in "\n".join(projection.prompt_summary)


async def test_portrait_projection_uses_profile_projection_as_strong_input_and_converges_groups():
    profile = UserProfileProjection(
        user_id="local_user",
        entity_id="user:local_user",
        display_name="子涵",
        preferred_form_of_address="子涵",
        home_location="杭州",
    )

    projection = await UserPortraitProjectionBuilder(
        _FragmentedProfileSignalL2(),
        profile_projection=profile,
    ).build("local_user")

    world_groups = {group["id"]: group for group in projection.world["groups"]}
    assert [group["id"] for group in projection.world["groups"]] == [
        "identity",
        "projects",
        "preferences",
        "work_style",
    ]
    assert "子涵" in world_groups["identity"]["summary"]
    assert "杭州" in world_groups["identity"]["summary"]
    assert "Magi 记忆系统" in world_groups["projects"]["summary"]
    assert "插件生态" in world_groups["preferences"]["summary"]
    assert "Codex" not in str(projection.world)
    assert "先讲结论" in world_groups["work_style"]["summary"]
    assert "一次性页面" not in str(projection.world)

    prompt_text = "\n".join(projection.prompt_summary)
    assert "子涵" in prompt_text
    assert "Magi 记忆系统" in prompt_text
    assert "插件生态" in prompt_text
    assert "先讲结论" in prompt_text
    assert "Codex" not in prompt_text
    assert "interest." not in prompt_text
    assert "tool." not in prompt_text
    assert "external_activity" not in prompt_text


class _GraphSignalL2:
    async def list_current_assertions(self, **kwargs):
        return [
            {
                "assertion_id": "a-tool",
                "trait_family": "routine_profile",
                "trait_name": "tool",
                "trait_value": "本地插件仓库",
                "validation_state": "stable",
                "source_domain": "user_authored",
                "evidence_events": ["e1", "e2"],
            },
        ]

    async def list_tom_snapshots(self, **kwargs):
        return []

    async def get_relationships(self, **kwargs):
        return [
            {
                "triple_id": "t-place",
                "predicate": "VISITED",
                "object_id": "place:东京",
                "object_type": "place",
                "source_type": "photo_library_apple_photos",
                "observation_count": 3,
            },
            {
                "triple_id": "t-tool",
                "predicate": "USES",
                "object_id": "software:Chrome",
                "object_type": "software",
                "source_type": "chrome_history",
                "observation_count": 5,
            },
            {
                "triple_id": "t-single",
                "predicate": "VISITED",
                "object_id": "place:一次性地点",
                "object_type": "place",
                "observation_count": 1,
            },
        ]


class _RicherGraphSignalL2:
    async def list_current_assertions(self, **kwargs):
        return []

    async def list_tom_snapshots(self, **kwargs):
        return []

    async def get_relationships(self, **kwargs):
        return [
            {
                "triple_id": "t-music-artist",
                "predicate": "LISTENED",
                "object_id": "group:DIIV",
                "object_type": "group",
                "source_type": "netease_music",
                "observation_count": 3,
            },
            {
                "triple_id": "t-topic",
                "predicate": "INTERESTED_IN",
                "object_id": "topic:coding-agent",
                "object_type": "topic",
                "source_type": "chrome_history",
                "observation_count": 4,
            },
            {
                "triple_id": "t-project",
                "predicate": "WORKS_WITH",
                "object_id": "software:magi",
                "object_type": "software",
                "source_type": "github_activity",
                "observation_count": 2,
            },
            {
                "triple_id": "t-one-off-song",
                "predicate": "LISTENED",
                "object_id": "media:one-off-track",
                "object_type": "media",
                "source_type": "netease_music",
                "observation_count": 1,
            },
            {
                "triple_id": "t-noisy-url",
                "predicate": "INTERESTED_IN",
                "object_id": "topic:https://example.com/tmp.log",
                "object_type": "topic",
                "source_type": "chrome_history",
                "observation_count": 4,
            },
        ]


async def test_portrait_projection_keeps_inventory_graph_signals_out_of_world():
    projection = await UserPortraitProjectionBuilder(_GraphSignalL2()).build("local_user")

    world_groups = {group["id"]: [item["text"] for item in group["items"]] for group in projection.world["groups"]}
    assert world_groups["identity"] == []
    assert world_groups["projects"] == []
    assert world_groups["preferences"] == []
    assert world_groups["work_style"] == []
    assert "东京" not in str(projection.recent)
    assert "Chrome" not in str(projection.recent)
    assert "本地插件仓库" not in str(projection.recent)

    prompt_text = "\n".join(projection.prompt_summary)
    assert "本地插件仓库" not in prompt_text
    assert "Chrome" not in prompt_text
    assert "东京" not in prompt_text


async def test_portrait_projection_does_not_project_graph_edges_directly():
    projection = await UserPortraitProjectionBuilder(_RicherGraphSignalL2()).build("local_user")

    world_groups = {
        group["id"]: [item["text"] for item in group["items"]]
        for group in projection.world["groups"]
    }

    assert world_groups["identity"] == []
    assert world_groups["projects"] == []
    assert world_groups["preferences"] == []
    assert world_groups["work_style"] == []
    recent_text = str(projection.recent)
    assert "DIIV" not in recent_text
    assert "coding agent" not in recent_text
    assert "magi" not in recent_text
    assert "one-off-track" not in str(projection.world)
    assert "example.com" not in str(projection.world)

    prompt_text = "\n".join(projection.prompt_summary)
    assert "DIIV" not in prompt_text
    assert "coding-agent" not in prompt_text
    assert "magi" not in prompt_text


async def test_l2_clear_removes_profile_and_portrait_projection_caches(tmp_path):
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    profile_repo = UserProfileProjectionRepository(db_path)
    portrait_repo = UserPortraitProjectionRepository(db_path)
    await profile_repo.upsert(UserProfileProjection(
        user_id="local_user",
        entity_id="user:local_user",
        display_name="子涵",
        preferred_form_of_address="子涵",
    ))
    await portrait_repo.upsert(UserPortraitProjection(
        user_id="local_user",
        entity_id="user:local_user",
        world={"groups": [{"id": "identity", "items": [{"text": "子涵"}]}]},
        prompt_summary=["用户希望被称呼为子涵。"],
    ))

    store = L2CognitionStore(db_path=db_path)
    await store.clear()

    assert await profile_repo.get("local_user") is None
    assert await portrait_repo.get("local_user") is None
