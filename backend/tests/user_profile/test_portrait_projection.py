from __future__ import annotations

import sqlite3

import pytest

from _shared.memory_schema import apply_memory_shared_schema
from magi.memory.l2.store import L2CognitionStore
from magi.user_profile.models import PORTRAIT_PROMPT_CONTRACT_VERSION, UserPortraitProjection, UserProfileProjection
from magi.user_profile.portrait_projection_builder import UserPortraitProjectionBuilder
from magi.user_profile.portrait_projection_freshness import portrait_projection_is_stale
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
                "natural_summary": "RAG",
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
                "natural_summary": "Magi 记忆系统",
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
                "natural_summary": "先讲结论，再讲原因",
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
                "natural_summary": "一次性页面标题",
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
                "natural_summary": "验证 L2 断言和画像质量",
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
                "natural_summary": "DeepSeek",
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
                "natural_summary": "Chrome",
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
                "natural_summary": "RAG",
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
                "natural_summary": "Magi 记忆系统",
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
                "natural_summary": "DeepSeek",
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


class _ExpiringGoalL2:
    def __init__(self) -> None:
        self.now = 150.0

    async def list_current_assertions(self, **kwargs):
        if self.now >= 200.0:
            return []
        return [
            {
                "assertion_id": "a-goal-beach",
                "trait_family": "goal_profile",
                "trait_name": "goal.intent",
                "trait_value": "去海边",
                "natural_summary": "去海边",
                "source_domain": "user_authored",
                "validation_state": "tentative",
                "confidence_score": 0.9,
                "evidence_events": ["event-goal"],
                "temporal_scope": "recent",
                "expires_at": 200.0,
                "updated_at": 100.0,
            }
        ]


class _FragmentedProfileSignalL2:
    async def list_current_assertions(self, **kwargs):
        return [
            {
                "assertion_id": "a-project",
                "trait_family": "project_profile",
                "trait_name": "project.magi_memory",
                "trait_value": "Magi 记忆系统",
                "natural_summary": "Magi 记忆系统",
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
                "natural_summary": "插件生态",
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
                "natural_summary": "Codex",
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
                "natural_summary": "先讲结论，再补关键依据",
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
                "natural_summary": "一次性页面",
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
        prompt_contract_version=PORTRAIT_PROMPT_CONTRACT_VERSION,
        evidence_refs=["assertion:a-interest-rag"],
        source_counts={"conversation": 1},
        generated_by="rule",
        input_assertion_highwater=11.0,
        input_claim_highwater=12.0,
        input_review_highwater=13.0,
        input_profile_highwater=14.0,
    )

    saved = await repo.upsert(projection)
    loaded = await repo.get("local_user")

    assert loaded is not None
    assert loaded.user_id == saved.user_id
    assert loaded.world["groups"][0]["items"][0]["text"] == "RAG"
    assert loaded.prompt_summary == ["用户关注 RAG。"]
    assert loaded.prompt_contract_version == PORTRAIT_PROMPT_CONTRACT_VERSION
    assert loaded.evidence_refs == ["assertion:a-interest-rag"]
    assert loaded.source_counts == {"conversation": 1}
    assert loaded.input_assertion_highwater == 11.0
    assert loaded.input_claim_highwater == 12.0
    assert loaded.input_review_highwater == 13.0
    assert loaded.input_profile_highwater == 14.0
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


async def test_review_items_use_distinct_natural_summaries_instead_of_enum_values():
    class _PreferenceReviewL2:
        async def list_current_assertions(self, **_kwargs):
            return [
                {
                    "assertion_id": "a-music-style",
                    "trait_family": "preference_profile",
                    "trait_name": "preference.affinity",
                    "trait_value": "like",
                    "natural_summary": "工作时更喜欢没有人声的音乐，不容易分心。",
                    "source_domain": "user_authored",
                    "validation_state": "tentative",
                    "evidence_events": ["event-music"],
                    "temporal_scope": "stable",
                },
                {
                    "assertion_id": "a-story-style",
                    "trait_family": "preference_profile",
                    "trait_name": "preference.affinity",
                    "trait_value": "like",
                    "natural_summary": "比起强情节，更喜欢人物关系自然的作品。",
                    "source_domain": "user_authored",
                    "validation_state": "tentative",
                    "evidence_events": ["event-story"],
                    "temporal_scope": "stable",
                },
            ]

    projection = await UserPortraitProjectionBuilder(_PreferenceReviewL2()).build("local_user")

    assert [item["text"] for item in projection.review["items"]] == [
        "工作时更喜欢没有人声的音乐，不容易分心。",
        "比起强情节，更喜欢人物关系自然的作品。",
    ]
    assert [item["correction_value"] for item in projection.review["items"]] == [
        "like",
        "like",
    ]


async def test_pending_review_change_invalidates_portrait_projection():
    class _ReviewChangedL2:
        async def current_subject_revision(self, _entity_id: str) -> int:
            return 0

        async def current_clear_generation(self) -> int:
            return 0

        async def list_current_assertions(self, **_kwargs):
            return []

        async def latest_pending_review_change_at(self, *, subject_id: str) -> float:
            assert subject_id == "user:local_user"
            return 20.0

    projection = UserPortraitProjection(
        user_id="local_user",
        entity_id="user:local_user",
        input_review_highwater=10.0,
        prompt_contract_version=PORTRAIT_PROMPT_CONTRACT_VERSION,
    )

    assert await portrait_projection_is_stale(
        projection,
        user_id="local_user",
        l2_store=_ReviewChangedL2(),
    )


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


async def test_goal_prompt_line_is_deterministic_and_expires_from_portrait():
    store = _ExpiringGoalL2()
    builder = UserPortraitProjectionBuilder(store)

    projection = await builder.build("local_user")

    assert projection.prompt_summary == ["近期计划：去海边"]
    assert projection.generated_by == "rule"

    store.now = 250.0
    assert await portrait_projection_is_stale(
        projection,
        user_id="local_user",
        l2_store=store,
    )

    expired = await builder.build("local_user")
    assert "近期计划：去海边" not in expired.prompt_summary
    assert "去海边" not in str(expired.recent)


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
                "natural_summary": "本地插件仓库",
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


def test_goal_display_preserves_grounded_subject_and_original_time():
    from magi.i18n import language_context
    from magi.user_profile.portrait_projection_builder import _item_from_assertion
    with language_context("zh-CN"):
        item = _item_from_assertion({
            "assertion_id": "a-goal", "entity_type": "user", "trait_family": "goal_profile", "trait_name": "goal.intent",
            "trait_value": "申请项目", "natural_summary": "用户计划明年申请项目。 原文时间: 明年",
            "temporal_scope": "recent", "source_domain": "user_authored", "validation_state": "tentative",
        })
    assert item is not None
    assert item["text"] == "近期计划：用户计划明年申请项目。 原文时间: 明年"
    assert item["correction_value"] == "申请项目"


async def test_unresolved_assertions_remain_distinct_when_fallback_text_matches():
    from magi.i18n import language_context
    class UnresolvedTargets:
        async def list_current_assertions(self, **kwargs):
            return [{
                "assertion_id": f"assert-{index}", "entity_id": "user:local_user", "entity_type": "user",
                "trait_family": "preference_profile", "trait_name": "preference.affinity", "trait_value": "like",
                "target_entity_id": f"food:unresolved-{index}", "natural_summary": "", "temporal_scope": "stable",
                "source_domain": "user_authored", "inference_depth": "direct", "validation_state": "tentative",
                "confidence_score": 0.3,
            } for index in (1, 2)]
    with language_context("zh-CN"):
        projection = await UserPortraitProjectionBuilder(UnresolvedTargets()).build("local_user")
    assert {item["assertion_id"] for item in projection.review["items"]} == {"assert-1", "assert-2"}
    assert {item["text"] for item in projection.review["items"]} == {"用户喜欢尚未解析的对象。"}


def _governed_prompt_assertion(assertion_id: str, **values):
    return {
        "assertion_id": assertion_id, "entity_id": "user:local_user", "entity_type": "user",
        "trait_family": "preference_profile", "trait_name": "preference.affinity", "trait_value": "like",
        "target_entity_id": "food:strawberry", "natural_summary": "用户喜欢草莓。",
        "source_domain": "user_authored", "validation_state": "stable", "confidence_score": 0.95,
        "temporal_scope": "stable", "evidence_events": [f"event:{assertion_id}"], "updated_at": 100.0,
        **values,
    }


async def test_portrait_keeps_missing_fact_notices_out_of_model_context():
    from magi.i18n import language_context

    class MissingDescriptions:
        async def list_current_assertions(self, **kwargs):
            assert kwargs == {
                "entity_id": "user:local_user", "entity_type": "user", "context_scope": None, "limit": 500,
            }
            return [
                _governed_prompt_assertion("assert-complete"),
                _governed_prompt_assertion("assert-unresolved", natural_summary="", target_entity_id="food:hidden"),
                _governed_prompt_assertion(
                    "assert-unavailable", trait_family="interest_profile", trait_name="interest.unknown",
                    natural_summary="", trait_value="assert:internal-id", target_entity_id=None,
                ),
                _governed_prompt_assertion(
                    "assert-behavior", trait_family="routine_profile", trait_name="routine.interaction.repeat",
                    natural_summary="", trait_value="tool:internal-id", target_entity_id="tool:internal-id",
                    inference_depth="topology_only", temporal_scope="recent",
                ),
            ]

    with language_context("zh-CN"):
        projection = await UserPortraitProjectionBuilder(MissingDescriptions()).build("local_user")
    ui_text = str(projection.world) + str(projection.recent)
    assert "尚未解析的对象" in ui_text
    assert "这条记录缺少完整事实描述。" in ui_text
    items = [item for group in projection.world["groups"] for item in group["items"]]
    items.extend(projection.recent["items"])
    assert {item["assertion_id"]: item["display_status"] for item in items} == {
        "assert-complete": "complete", "assert-unresolved": "partial",
        "assert-unavailable": "unavailable", "assert-behavior": "partial",
    }
    assert len(projection.prompt_summary) == 1
    assert "用户喜欢草莓。" in projection.prompt_summary[0]
    assert "尚未解析" not in projection.prompt_summary[0]
    assert "缺少完整事实描述" not in projection.prompt_summary[0]
    assert "internal-id" not in projection.prompt_summary[0]
    assert set(projection.evidence_refs) == {
        "assertion:assert-complete", "assertion:assert-unresolved",
        "assertion:assert-unavailable", "assertion:assert-behavior",
    }


async def test_portrait_prompt_and_freshness_do_not_read_ui_item_text(monkeypatch):
    from magi.i18n import language_context
    from magi.user_profile import portrait_projection_builder as builder_module

    class GovernedFacts:
        async def list_current_assertions(self, **kwargs):
            return [
                _governed_prompt_assertion("assert-complete"),
                _governed_prompt_assertion(
                    "assert-goal", trait_family="goal_profile", trait_name="goal.intent",
                    trait_value="申请项目", natural_summary="用户计划明年申请项目。 原文时间: 明年",
                    temporal_scope="recent", validation_state="tentative",
                ),
            ]

    original_assertion_item = builder_module._item_from_assertion
    original_profile_items = UserPortraitProjectionBuilder._profile_world_items

    def ui_assertion_item(assertion):
        item = original_assertion_item(assertion)
        assert item is not None
        return {**item, "text": "UI assertion notice"}

    def ui_profile_items(profile):
        grouped = original_profile_items(profile)
        for items in grouped.values():
            for item in items:
                item["text"] = "UI profile notice"
        return grouped

    monkeypatch.setattr(builder_module, "_item_from_assertion", ui_assertion_item)
    monkeypatch.setattr(UserPortraitProjectionBuilder, "_profile_world_items", staticmethod(ui_profile_items))
    store = GovernedFacts()
    profile = UserProfileProjection(preferred_form_of_address="小明")
    with language_context("zh-CN"):
        projection = await UserPortraitProjectionBuilder(store, profile_projection=profile).build("local_user")
        assert "UI assertion notice" in str(projection.world)
        assert "UI profile notice" in str(projection.world)
        prompt = "\n".join(projection.prompt_summary)
        assert "用户喜欢草莓。" in prompt
        assert "希望称呼为「小明」" in prompt
        assert projection.prompt_summary[-1] == "近期计划：用户计划明年申请项目。 原文时间: 明年"
        assert "UI" not in prompt
        assert not await portrait_projection_is_stale(
            projection, user_id="local_user", l2_store=store, profile_projection=profile,
        )
        projection.prompt_summary = ["UI assertion notice"]
        assert await portrait_projection_is_stale(
            projection, user_id="local_user", l2_store=store, profile_projection=profile,
        )


@pytest.mark.parametrize("state", ["tentative", "contradicted"])
async def test_complete_description_does_not_admit_review_assertion_to_prompt(state):
    from magi.i18n import language_context

    class ReviewFact:
        async def list_current_assertions(self, **kwargs):
            return [_governed_prompt_assertion("assert-review-only", validation_state=state)]

    with language_context("zh-CN"):
        projection = await UserPortraitProjectionBuilder(ReviewFact()).build("local_user")
    assert projection.review["items"][0]["text"] == "用户喜欢草莓。"
    assert projection.prompt_summary == []


async def test_portrait_cache_requires_fact_completeness_outside_prompt_budget():
    from magi.i18n import language_context

    class ReviewFact:
        async def list_current_assertions(self, **kwargs):
            return [_governed_prompt_assertion("assert-review-only", validation_state="tentative")]

    store = ReviewFact()
    with language_context("zh-CN"):
        projection = await UserPortraitProjectionBuilder(store).build("local_user")
        assert projection.prompt_summary == []
        assert not await portrait_projection_is_stale(
            projection, user_id="local_user", l2_store=store,
        )
        projection.review["items"][0].pop("display_status")
        assert await portrait_projection_is_stale(
            projection, user_id="local_user", l2_store=store,
        )


async def test_old_prompt_contract_is_stale_without_any_assertion_ui_items():
    old = UserPortraitProjection(
        user_id="local_user", world={}, review={}, recent={},
        prompt_summary=["用户关注或偏好：这条记录缺少完整事实描述。"],
    )
    assert await portrait_projection_is_stale(old, user_id="local_user", l2_store=object())
    assert old.prompt_contract_version == 0


async def test_successful_builder_marks_semantic_prompt_contract():
    projection = await UserPortraitProjectionBuilder(_FakeL2()).build("local_user")
    assert projection.prompt_contract_version == PORTRAIT_PROMPT_CONTRACT_VERSION


async def test_portrait_rejects_polluted_summary_and_preserves_source_semantics():
    from magi.i18n import language_context

    identity = "opaque-apple-identity"

    class PollutedFact:
        async def list_current_assertions(self, **kwargs):
            return [_governed_prompt_assertion(
                "assert-polluted", target_entity_id=identity, temporal_scope="recent",
                natural_summary=f"用户不喜欢{identity}。 原文时间: 上周",
                trait_value="dislike", validation_state="tentative", inference_depth="direct",
            )]

    with language_context("zh-CN"):
        projection = await UserPortraitProjectionBuilder(PollutedFact()).build("local_user")
    [item] = projection.recent["items"]
    assert item["display_status"] == "unavailable"
    assert item["correction_value"] == "dislike"
    assert item["evidence_basis"] == "direct_report"
    assert "event:event:assert-polluted" in item["basis_refs"]
    assert projection.prompt_summary == []
    assert identity not in str(projection.recent)


async def test_portrait_detects_changed_fact_outside_prompt_budget_without_highwater_change():
    from magi.i18n import language_context

    class ReviewFact:
        summary = "用户喜欢草莓。"

        async def list_current_assertions(self, **kwargs):
            return [_governed_prompt_assertion(
                "assert-review-only", validation_state="tentative", natural_summary=self.summary,
            )]

    store = ReviewFact()
    with language_context("zh-CN"):
        projection = await UserPortraitProjectionBuilder(store).build("local_user")
        assert projection.prompt_summary == []
        assert not await portrait_projection_is_stale(projection, user_id="local_user", l2_store=store)
        store.summary = "用户这周喜欢草莓。"
        assert await portrait_projection_is_stale(projection, user_id="local_user", l2_store=store)
        rebuilt = await UserPortraitProjectionBuilder(store).build("local_user")
        assert rebuilt.prompt_summary == []
        assert rebuilt.input_assertion_highwater == projection.input_assertion_highwater
        assert rebuilt.review["items"][0]["text"] == store.summary
        assert not await portrait_projection_is_stale(rebuilt, user_id="local_user", l2_store=store)


async def test_portrait_cache_without_semantic_signature_requires_governed_rebuild():
    from magi.i18n import language_context

    class ReviewFact:
        async def list_current_assertions(self, **kwargs):
            return [_governed_prompt_assertion("assert-review-only", validation_state="tentative")]

    store = ReviewFact()
    with language_context("zh-CN"):
        projection = await UserPortraitProjectionBuilder(store).build("local_user")
        projection.review["items"][0].pop("fact_signature")
        assert await portrait_projection_is_stale(projection, user_id="local_user", l2_store=store)


async def test_portrait_signature_survives_repository_restart_and_checks_recovered_wording(tmp_path):
    from magi.i18n import language_context

    class ReviewFact:
        summary = "用户不喜欢苹果。 原文时间: 上周"

        async def list_current_assertions(self, **kwargs):
            return [_governed_prompt_assertion(
                "assert-review-only", validation_state="tentative", trait_value="dislike",
                target_entity_id="opaque-apple", natural_summary=self.summary,
            )]

    store = ReviewFact()
    db_path = str(tmp_path / "portrait.db")
    with language_context("zh-CN"):
        projection = await UserPortraitProjectionBuilder(store).build("local_user")
        await UserPortraitProjectionRepository(db_path).upsert(projection)
        loaded = await UserPortraitProjectionRepository(db_path).get("local_user")
        assert loaded is not None
        assert loaded.review["items"] == projection.review["items"]
        assert not await portrait_projection_is_stale(loaded, user_id="local_user", l2_store=store)
        store.summary = "用户不喜欢opaque-apple。 原文时间: 上周"
        assert await portrait_projection_is_stale(loaded, user_id="local_user", l2_store=store)
        invalidated = await UserPortraitProjectionBuilder(store).build("local_user")
        await UserPortraitProjectionRepository(db_path).upsert(invalidated)
        reloaded = await UserPortraitProjectionRepository(db_path).get("local_user")
        assert reloaded is not None
        assert reloaded.review["items"][0]["display_status"] == "unavailable"
        assert reloaded.prompt_summary == []
        assert "opaque-apple" not in str(reloaded.review)
