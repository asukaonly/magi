from __future__ import annotations

from magi.user_profile.models import UserPortraitProjection
from magi.user_profile.portrait_projection_builder import UserPortraitProjectionBuilder
from magi.user_profile.portrait_projection_repository import UserPortraitProjectionRepository


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
