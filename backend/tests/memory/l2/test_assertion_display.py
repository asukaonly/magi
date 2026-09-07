"""Fact presentation preserves semantic targets without changing stored values."""

from __future__ import annotations

import sqlite3

import pytest

from magi.memory.l2.assertion_display import (
    assertion_value_options,
    decorate_assertion_display,
    render_assertion_display,
)


@pytest.fixture(autouse=True)
def _chinese_display_language():
    from magi.i18n import language_context
    with language_context("zh-CN"):
        yield


def _assertion(**overrides):
    return {
        "entity_id": "user:local_user",
        "entity_type": "user",
        "trait_family": "preference_profile",
        "trait_name": "preference.affinity",
        "trait_value": "like",
        "target_entity_id": "food:2d48737d923a52f99c571580dc8c9121",
        "target_entity_name": "草莓",
        "natural_summary": "用户喜欢草莓。",
        "source_domain": "user_authored",
        "status": "tentative",
        "temporal_scope": "stable",
        **overrides,
    }


@pytest.mark.parametrize(("updates", "expected"), [
    ({}, "用户喜欢草莓。"),
    ({"trait_value": "dislike", "natural_summary": "用户不喜欢草莓。"}, "用户不喜欢草莓。"),
    ({"natural_summary": ""}, "用户喜欢草莓。"),
    ({"natural_summary": "", "trait_value": "dislike"}, "用户不喜欢草莓。"),
    ({"natural_summary": "", "trait_name": "interest.attention", "trait_value": "interested"}, "用户关注草莓。"),
    ({"natural_summary": "", "trait_name": "communication.address.preferred", "trait_value": "小林"}, "用户希望被称为小林。"),
    ({"natural_summary": "", "trait_name": "communication.address.disallowed", "trait_value": "老师"}, "用户不希望被称为老师。"),
    ({"natural_summary": "", "temporal_scope": "recent"}, "用户最近喜欢草莓。"),
    ({"natural_summary": "用户喜欢草莓和芒果。"}, "用户喜欢草莓和芒果。"),
    ({"natural_summary": "", "target_entity_name": None}, "用户喜欢尚未解析的对象。"),
    ({"natural_summary": "", "entity_type": "person", "entity_name": "小李"}, "小李喜欢草莓。"),
    ({"natural_summary": "", "entity_type": "person", "entity_name": None}, "主体未解析的对象喜欢草莓。"),
])
def test_complete_fact_rendering(updates, expected):
    source = _assertion(**updates)
    assert render_assertion_display(source, language="zh-CN") == expected
    assert source["trait_value"] == updates.get("trait_value", "like")


def test_unresolved_target_keeps_grounded_summary():
    assert render_assertion_display(
        _assertion(target_entity_name=None), language="zh-CN"
    ) == "用户喜欢草莓。"


def test_value_only_correction_does_not_invent_target():
    assert render_assertion_display({"value": "like"}, language="zh-CN") == "这条记录缺少完整事实描述。"
    assert render_assertion_display({"value": "dislike"}, language="en") == "A complete description of this record is unavailable."


def test_missing_summary_uses_requested_language():
    assert render_assertion_display(
        _assertion(natural_summary="", temporal_scope="recent", trait_value="dislike"), language="en"
    ) == "The user recently dislikes 草莓."


def test_only_canonical_target_routes_have_enum_editor():
    assert assertion_value_options(_assertion()) == ["like", "dislike"]
    assert assertion_value_options(_assertion(trait_name="communication.address.preferred")) is None
    assert assertion_value_options(_assertion(trait_name="goal.intent")) is None


@pytest.mark.asyncio
async def test_batch_names_preserve_distinct_objects_and_source_rows(tmp_path):
    db_path = str(tmp_path / "memory.db")
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE entity_catalog (entity_id TEXT, canonical_name TEXT)")
        db.executemany("INSERT INTO entity_catalog VALUES (?, ?)", [
            ("food:first", "草莓"), ("food:second", "芒果"),
        ])
    sources = [
        _assertion(target_entity_id=target, natural_summary="")
        for target in ("food:first", "food:second", "food:opaque")
    ]
    results = await decorate_assertion_display(db_path, sources)
    assert [item["display_text"] for item in results] == [
        "用户喜欢草莓。", "用户喜欢芒果。", "用户喜欢尚未解析的对象。",
    ]
    assert all(item["trait_value"] == "like" for item in results)
    assert all(item["source_domain"] == "user_authored" for item in results)
    assert all(item["status"] == "tentative" for item in results)
    assert all("display_text" not in item for item in sources)


@pytest.mark.parametrize("value", ["food:opaque", "like", "literal without a known trait"])
def test_unknown_trait_never_guesses_value_semantics(value):
    assert render_assertion_display({"trait_name": "unregistered", "trait_value": value}, language="zh-CN") == "这条记录缺少完整事实描述。"


@pytest.mark.parametrize(("trait", "value", "expected"), [
    ("identity.real_name", "like", "用户姓名是like。"),
    ("goal.intent", "planned", "用户计划planned。"),
])
def test_known_literal_values_are_not_treated_as_internal_enums(trait, value, expected):
    assert render_assertion_display(
        _assertion(trait_name=trait, trait_value=value, natural_summary=""), language="zh-CN"
    ) == expected


def test_settings_profile_uses_authoritative_value_not_diagnostic_summary():
    assert render_assertion_display(_assertion(
        source_domain="settings_profile", trait_name="communication.address.preferred",
        trait_value="小林", natural_summary="User profile field communication.address.preferred was set from personal profile settings.",
    ), language="zh-CN") == "用户希望被称为小林。"


def test_controlled_state_value_keeps_subject_and_localized_meaning():
    assert render_assertion_display(_assertion(
        trait_family="stress", trait_name="stress", trait_value="high", natural_summary="", temporal_scope="recent",
    ), language="zh-CN") == "用户近期的压力水平是高。"


@pytest.mark.parametrize("stored_value", ["food:opaque", "opaque"])
def test_behavior_display_uses_catalog_target_not_rule_storage_strategy(stored_value):
    row = _assertion(inference_depth="topology_only", trait_value=stored_value, natural_summary=f"关注 {stored_value}")
    assert render_assertion_display(row, language="zh-CN") == "根据多次活动推测，你可能关注「草莓」。"
    row["target_entity_name"] = None
    assert render_assertion_display(row, language="zh-CN") == "根据多次活动推测，你可能关注「尚未解析的对象」。"


def test_free_text_mood_keeps_literal_editor_and_fact():
    row = {"entity_type": "user", "trait_name": "mood", "trait_family": "mood", "trait_value": "难过"}
    assert assertion_value_options(row) is None
    assert render_assertion_display(row, language="zh-CN") == "用户感到难过。"


def test_behavior_inference_preserves_named_third_party_subject():
    assert render_assertion_display(_assertion(
        inference_depth="topology_only", entity_type="person", entity_name="小李",
    ), language="zh-CN") == "根据多次活动推测，小李可能关注「草莓」。"


@pytest.mark.asyncio
async def test_assertion_list_and_count_find_catalog_names_without_summary(l2_store_with_schema):
    store = l2_store_with_schema
    from magi.core.sqlite import sqlite_connection_async
    async with sqlite_connection_async(store.db_path) as db:
        await db.executemany(
            "INSERT INTO entity_catalog (entity_id, canonical_name, entity_type, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            [("food:opaque", "草莓", "food", 1.0, 1.0), ("person:opaque", "小李", "person", 1.0, 1.0)],
        )
        await db.commit()
    assertion_id = await store.upsert_assertion_candidate({
        **_assertion(natural_summary="", trait_value="dislike", target_entity_id="food:opaque"),
        "entity_id": "person:opaque", "entity_type": "person", "confidence_score": 0.8,
        "evidence_events": ["evidence-display-search"], "volatility_index": 0.2,
        "inference_depth": "explicit", "validation_state": "stable",
        "first_inferred_at": 1.0, "last_validated_at": 1.0,
    })
    for query in ("草莓", "小李"):
        rows = await store.list_tom_assertions(query=query)
        assert [row["assertion_id"] for row in rows] == [assertion_id]
        assert await store.count_tom_assertions(query=query) == 1
        assert (await decorate_assertion_display(store.db_path, rows))[0]["display_text"] == "小李不喜欢草莓。"
    for query in ("芒果", "草%", "小_", "' OR 1=1 --"):
        assert await store.list_tom_assertions(query=query) == []
        assert await store.count_tom_assertions(query=query) == 0
