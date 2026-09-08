"""Stored conflict notifications must render retained facts at the public read boundary."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from magi.api.routers.notifications_routes import build_default_notifications_router
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.core.sqlite import sqlite_connection_async
from magi.i18n import language_context
from magi.memory.l2.assertions.conflict_notification_display import (
    project_profile_conflict_notifications,
    render_profile_conflict_notifications,
)
from magi.memory.l2.retrieval.shadow_conflicts import ShadowConflictPair, ShadowConflictRef
from magi.memory.l2.assertions.conflict_notifications import (
    materialize_shadow_conflict_notifications,
)
from magi.notifications.service import NotificationService
from magi.notifications.store import NotificationRow, NotificationStore


@pytest.fixture(autouse=True)
def _chinese_language():
    with language_context("zh-CN"):
        yield


async def _conflict(store, *, summary: bool = True):
    async with sqlite_connection_async(store.db_path) as db:
        await db.execute(
            "INSERT INTO entity_catalog (entity_id, canonical_name, entity_type, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("food:opaque", "草莓", "food", 1.0, 1.0),
        )
        await db.commit()
    base = {
        "entity_id": "user:local_user",
        "entity_type": "user",
        "trait_family": "preference_profile",
        "trait_name": "preference.affinity",
        "target_entity_id": "food:opaque",
        "target_entity_type": "food",
        "target_scope": "entity_bound",
        "temporal_scope": "recent",
        "confidence_score": 0.4,
        "volatility_index": 0.2,
        "inference_depth": "explicit",
        "validation_state": "tentative",
        "first_inferred_at": 1710000000.0,
        "last_validated_at": 1710000000.0,
        "decay_policy": "evidence_only",
    }
    authoritative = await store.upsert_assertion_candidate(
        {
            **base,
            "trait_value": "dislike",
            "source_domain": "user_authored",
            "evidence_events": ["auth-evidence"],
            "natural_summary": "用户最近不喜欢草莓。某个已移除来源的私人细节。" if summary else "",
        }
    )
    shadow = await store.upsert_assertion_candidate(
        {
            **base,
            "trait_value": "like",
            "source_domain": "external_activity",
            "evidence_events": ["shadow-evidence"],
            "natural_summary": "用户最近喜欢草莓。" if summary else "",
            "first_inferred_at": 1710000100.0,
            "last_validated_at": 1710000100.0,
        }
    )
    assert (await store.get_tom_assertion(assertion_id=shadow))["status"] == "shadow"
    return authoritative, shadow


def _notification_service(
    tmp_path, *, authoritative: str = "missing-auth", shadow: str = "missing-shadow"
):
    store = NotificationStore(str(tmp_path / "notifications.db"))
    store.ensure_schema()
    payload = {
        "conflict_type": "profile_conflict",
        "authoritative_id": authoritative,
        "shadow_id": shadow,
        "authoritative_value": "dislike",
        "inferred_value": "like",
        "trait_name": "preference.affinity",
        "entity_id": "user:local_user",
    }
    notification_id = store.insert(
        NotificationRow(
            user_id="default_user",
            kind="suggestion",
            dedupe_key="profile_conflict:preference.affinity:food:opaque",
            title="偏好冲突：preference.affinity",
            body="你最近常关注「like」，但你说过「dislike」—— 要更新偏好吗？",
            payload_json=json.dumps(payload),
            created_at_ms=1000,
        )
    )
    return store, NotificationService(store=store), notification_id, payload


async def _public_feed(service, memory, *, suppressed: bool = False):
    async def _suppression():
        return suppressed

    app = FastAPI()
    router = build_default_notifications_router(
        service_dep=lambda: service,
        unified_memory_dep=lambda: memory,
        profile_conflict_suppression_dep=_suppression,
    )
    app.include_router(_build_public_router(router, _PUBLIC_ROUTE_METHODS["notifications"]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/notifications?profile_conflicts_only=true")
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("summary", [True, False])
async def test_existing_raw_notification_projects_facts_without_rewriting_data(
    l2_store_with_schema, tmp_path, summary
):
    memory = l2_store_with_schema
    authoritative, shadow = await _conflict(memory, summary=summary)
    store, service, notification_id, payload = _notification_service(
        tmp_path, authoritative=authoritative, shadow=shadow
    )

    page = await _public_feed(service, SimpleNamespace(l2=memory))

    item = page["items"][0]
    assert item["title"] == "有两条记忆需要核对"
    assert item["body"] == "已有记录：用户最近不喜欢草莓。\n待确认候选：用户最近喜欢草莓。"
    assert item["payload"] == payload
    assert item["status"] == "unread"
    assert page["total"] == page["unread_count"] == 1
    assert store.get(notification_id).title == "偏好冲突：preference.affinity"
    assert "「like」" in store.get(notification_id).body
    assert (await memory.get_tom_assertion(assertion_id=authoritative))["trait_value"] == "dislike"
    assert (await memory.get_tom_assertion(assertion_id=shadow))["trait_value"] == "like"
    assert "私人细节" not in item["body"]


@pytest.mark.asyncio
async def test_new_notifications_use_the_same_complete_fact_renderer(
    l2_store_with_schema, tmp_path
):
    memory = l2_store_with_schema
    await _conflict(memory)
    store = NotificationStore(str(tmp_path / "notifications.db"))
    store.ensure_schema()
    stats = await materialize_shadow_conflict_notifications(
        memory,
        NotificationService(store=store),
        user_id="default_user",
        entity_id="user:local_user",
    )
    assert stats["notifications_emitted"] == 1
    item = store.list_for_user("default_user")[0]
    assert item.title == "有两条记忆需要核对"
    assert item.body == "已有记录：用户最近不喜欢草莓。\n待确认候选：用户最近喜欢草莓。"
    assert json.loads(item.payload_json)["inferred_value"] == "like"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("side", "mutation"),
    [
        ("authoritative", "status = 'archived'"),
        ("authoritative", "status = 'invalidated'"),
        ("authoritative", "status = 'user_rejected'"),
        ("authoritative", "status = 'superseded'"),
        ("authoritative", "status = 'expired'"),
        ("authoritative", "status = 'contradicted'"),
        ("authoritative", "authority_ref = 'forget:claim'"),
        ("authoritative", "expires_at = 1"),
        ("shadow", "status = 'user_rejected'"),
        ("shadow", "status = 'archived'"),
        ("shadow", "authority_ref = 'forget:event'"),
        ("shadow", "expires_at = 1"),
    ],
)
async def test_invisible_assertion_never_reappears_from_stored_notification(
    l2_store_with_schema, tmp_path, side, mutation
):
    memory = l2_store_with_schema
    authoritative, shadow = await _conflict(memory)
    _, service, _, _ = _notification_service(tmp_path, authoritative=authoritative, shadow=shadow)
    assertion_id = authoritative if side == "authoritative" else shadow
    async with sqlite_connection_async(memory.db_path) as db:
        await db.execute(
            f"UPDATE tom_trait_assertions SET {mutation} WHERE assertion_id = ?", (assertion_id,)
        )
        await db.commit()

    item = (await _public_feed(service, SimpleNamespace(l2=memory)))["items"][0]

    hidden_fact = "用户最近不喜欢草莓。" if side == "authoritative" else "用户最近喜欢草莓。"
    assert hidden_fact not in item["body"]
    assert "这条记录缺少完整事实描述。" in item["body"]
    assert "like" not in item["body"]
    assert "dislike" not in item["body"]
    scan = await memory.list_shadow_conflicts(entity_id="user:local_user", entity_type="user")
    assert scan.pairs == []
    stats = await materialize_shadow_conflict_notifications(
        memory,
        service,
        user_id="default_user",
        entity_id="user:local_user",
    )
    assert stats["notifications_emitted"] == 0


@pytest.mark.asyncio
async def test_missing_memory_and_missing_ids_have_honest_fallback(tmp_path):
    _, service, _, _ = _notification_service(tmp_path)
    page = await _public_feed(service, None)
    assert page["items"][0]["title"] == "有两条记忆需要核对"
    assert (
        page["items"][0]["body"]
        == "已有记录：这条记录缺少完整事实描述。\n待确认候选：这条记录缺少完整事实描述。"
    )


@pytest.mark.asyncio
async def test_pending_clear_suppresses_conflicts_before_assertion_reads(tmp_path):
    _, service, _, _ = _notification_service(tmp_path)
    page = await _public_feed(service, object(), suppressed=True)
    assert page == {"items": [], "unread_count": 0, "total": 0}


@pytest.mark.asyncio
async def test_notification_renderer_preserves_unresolved_subject_and_locale():
    row = {
        "entity_id": "person:private",
        "entity_type": "person",
        "trait_name": "preference.affinity",
        "trait_value": "dislike",
        "target_entity_id": "food:private",
        "temporal_scope": "recent",
        "status": "shadow",
    }
    [(title, body)] = await render_profile_conflict_notifications(
        db_path=None,
        pairs=[ShadowConflictPair(shadow=row)],
        language="en",
    )
    assert title == "Two memory records need review"
    assert "An unresolved subject recently dislikes an unresolved object." in body
    assert "person:private" not in body
    assert "food:private" not in body


@pytest.mark.asyncio
async def test_conflicts_with_diverged_slots_do_not_compare_unrelated_facts(
    l2_store_with_schema, tmp_path
):
    memory = l2_store_with_schema
    authoritative, shadow = await _conflict(memory)
    _, service, _, _ = _notification_service(tmp_path, authoritative=authoritative, shadow=shadow)
    async with sqlite_connection_async(memory.db_path) as db:
        await db.execute(
            "UPDATE tom_trait_assertions SET target_entity_id = 'food:other' WHERE assertion_id = ?",
            (shadow,),
        )
        await db.commit()
    item = (await _public_feed(service, SimpleNamespace(l2=memory)))["items"][0]
    assert "草莓" not in item["body"]
    assert item["body"].count("这条记录缺少完整事实描述。") == 2
    assert (
        await memory.list_shadow_conflicts(entity_id="user:local_user", entity_type="user")
    ).pairs == []


@pytest.mark.asyncio
async def test_domain_scan_and_reference_read_share_normalized_retained_pairs(l2_store_with_schema):
    memory = l2_store_with_schema
    authoritative, shadow = await _conflict(memory)
    [pair] = await memory.get_shadow_conflict_pairs(
        references=[
            ShadowConflictRef(shadow_id=shadow, authoritative_id=authoritative),
        ]
    )
    scan = await memory.list_shadow_conflicts(entity_id="user:local_user", entity_type="user")
    assert scan.shadows_seen == 1
    assert scan.pairs == [pair]
    assert pair.shadow["trait_value"] == "like"
    assert pair.authoritative["trait_value"] == "dislike"
    assert pair.authoritative["evidence_events"] == ["auth-evidence"]
    assert "私人细节" in pair.authoritative["natural_summary"]
    assert pair.authoritative == await memory.get_tom_assertion(assertion_id=authoritative)


@pytest.mark.asyncio
async def test_missing_notification_reference_never_substitutes_a_different_assertion(
    l2_store_with_schema,
):
    memory = l2_store_with_schema
    authoritative, shadow = await _conflict(memory)
    pairs = await memory.get_shadow_conflict_pairs(
        references=[
            ShadowConflictRef(shadow_id=None, authoritative_id=None),
            ShadowConflictRef(shadow_id=shadow, authoritative_id="removed-authority"),
            ShadowConflictRef(shadow_id="removed-shadow", authoritative_id=authoritative),
        ]
    )
    assert pairs[0] == ShadowConflictPair()
    assert pairs[1].shadow["assertion_id"] == shadow
    assert pairs[1].authoritative is None
    assert pairs[2].shadow is None
    assert pairs[2].authoritative["assertion_id"] == authoritative


@pytest.mark.asyncio
async def test_page_batches_unique_assertion_ids_and_catalog_reads(
    l2_store_with_schema, monkeypatch
):
    from unittest.mock import Mock
    from magi.memory.l2.assertions import conflict_notification_display as display
    from magi.memory.l2.retrieval import shadow_conflicts

    memory = l2_store_with_schema
    authoritative, _ = await _conflict(memory)
    connect = Mock(wraps=shadow_conflicts.sqlite_connection_async)
    decorate = Mock(wraps=display.decorate_assertion_display)
    monkeypatch.setattr(shadow_conflicts, "sqlite_connection_async", connect)
    monkeypatch.setattr(display, "decorate_assertion_display", decorate)
    payloads = [
        {"authoritative_id": authoritative, "shadow_id": f"missing-{i}"} for i in range(401)
    ]
    result = await project_profile_conflict_notifications(memory, payloads)
    assert len(result) == 401
    assert all("已有记录：用户最近不喜欢草莓。" in body for _, body in result)
    assert connect.call_count == 1
    assert decorate.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("old_title", ["偏好冲突：preference.affinity", None])
async def test_restore_list_projects_existing_conflict_titles_without_config_writes(
    monkeypatch, old_title
):
    from datetime import datetime, timezone
    from magi.api.routers.system_suggestions_routes import system_suggestions_router
    from magi.system_suggestions import dismissals
    from magi.system_suggestions.contracts import DismissalRecord

    record = DismissalRecord(
        dedupe_key="profile_conflict:preference.affinity:food:opaque",
        dismissed_at=datetime.now(timezone.utc),
        kind="explicit",
        title=old_title,
    )
    monkeypatch.setattr(dismissals, "list_active_dismissals", lambda: [record])
    app = FastAPI()
    app.include_router(
        _build_public_router(system_suggestions_router, _PUBLIC_ROUTE_METHODS["system_suggestions"])
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/system-suggestions/dismissals")
    assert response.status_code == 200
    assert response.json()["dismissals"][0]["title"] == "有两条记忆需要核对"
    assert record.title == old_title
