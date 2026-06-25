from __future__ import annotations

from _shared.memory_schema import apply_memory_shared_schema
from magi.memory.l2.store import L2CognitionStore
from magi.user_profile.models import UserPortraitProjection, UserProfileProjection
from magi.user_profile.portrait_projection_builder import UserPortraitProjectionBuilder
from magi.user_profile.portrait_projection_repository import UserPortraitProjectionRepository
from magi.user_profile.projection_repository import UserProfileProjectionRepository


class _FakeL2:
    async def list_tom_assertions(self, **kwargs):
        return [
            {
                "assertion_id": "a-interest-rag",
                "trait_family": "preference_profile",
                "trait_name": "interest.rag",
                "trait_value": "RAG",
                "source_domain": "external_activity",
                "validation_state": "corroborated",
                "confidence_score": 0.86,
                "evidence_events": ["event-1", "event-2", "event-3"],
                "last_validated_at": 1_700_000_001,
            },
            {
                "assertion_id": "a-interest-magi",
                "trait_family": "preference_profile",
                "trait_name": "interest.magi_memory",
                "trait_value": "Magi 记忆系统",
                "source_domain": "conversation",
                "validation_state": "stable",
                "confidence_score": 0.93,
                "evidence_events": ["event-4", "event-5"],
                "last_validated_at": 1_700_000_002,
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
            },
            {
                "assertion_id": "a-review",
                "trait_family": "preference_profile",
                "trait_name": "interest.one_off",
                "trait_value": "一次性页面标题",
                "source_domain": "external_activity",
                "validation_state": "tentative",
                "confidence_score": 0.5,
                "evidence_events": ["event-7"],
                "last_validated_at": 1_700_000_004,
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
    async def list_tom_assertions(self, **kwargs):
        return [
            {
                "assertion_id": "a-weak-passive",
                "trait_family": "preference_profile",
                "trait_name": "interest.deepseek",
                "trait_value": "DeepSeek",
                "source_domain": "external_activity",
                "validation_state": "stable",
                "confidence_score": 0.82,
                "evidence_events": ["event-1"],
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
            },
            {
                "assertion_id": "a-strong-passive",
                "trait_family": "preference_profile",
                "trait_name": "interest.rag",
                "trait_value": "RAG",
                "source_domain": "external_activity",
                "validation_state": "stable",
                "confidence_score": 0.9,
                "evidence_events": ["event-6", "event-7", "event-8"],
            },
            {
                "assertion_id": "a-user-authored",
                "trait_family": "preference_profile",
                "trait_name": "interest.magi_memory",
                "trait_value": "Magi 记忆系统",
                "source_domain": "user_authored",
                "validation_state": "stable",
                "confidence_score": 0.95,
                "evidence_events": ["event-9"],
            },
        ]

    async def list_tom_snapshots(self, **kwargs):
        return []


class _ConfirmedPassiveSignalL2:
    async def list_tom_assertions(self, **kwargs):
        return [
            {
                "assertion_id": "a-confirmed-passive",
                "trait_family": "preference_profile",
                "trait_name": "interest.deepseek",
                "trait_value": "DeepSeek",
                "source_domain": "external_activity",
                "validation_state": "stable",
                "user_feedback": "confirmed",
                "confidence_score": 0.9,
                "evidence_events": ["event-1"],
            },
        ]

    async def list_tom_snapshots(self, **kwargs):
        return []


async def test_portrait_projection_repository_roundtrips_prompt_and_page_model(tmp_path):
    repo = UserPortraitProjectionRepository(str(tmp_path / "memory.db"))
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
    assert [item["text"] for item in world_groups["preferences"]] == ["Magi 记忆系统", "RAG"]
    assert [item["text"] for item in world_groups["communication"]] == ["先讲结论，再讲原因"]
    assert [item["text"] for item in projection.review["items"]] == ["一次性页面标题"]
    assert [item["text"] for item in projection.recent["items"]] == [
        "正在检查画像投影效果",
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
    assert "DeepSeek" not in prompt_text
    assert "Chrome" not in prompt_text


async def test_portrait_projection_treats_confirmed_feedback_as_user_qualified():
    projection = await UserPortraitProjectionBuilder(_ConfirmedPassiveSignalL2()).build("local_user")

    world_groups = {group["id"]: group["items"] for group in projection.world["groups"]}
    assert [item["text"] for item in world_groups["preferences"]] == ["DeepSeek"]
    assert "DeepSeek" in "\n".join(projection.prompt_summary)


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
