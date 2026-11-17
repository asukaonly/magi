"""Explicit watch lifecycle, governed results, replay and in-flight cancellation."""

import json
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from magi.core.sqlite import sqlite_connection_async
from magi.memory.reflection_evidence import evidence_digest
from magi.personal_tasks.models import ItemPatch, TaskConflictError, TaskMutation, TaskNotFoundError
from magi.personal_tasks.watch_models import WatchFields, WatchMutation
from magi.personal_tasks.watch_service import AttentionWatchService, bind_attention_watch_service


@asynccontextmanager
async def guard():
    yield


@pytest.fixture
def watches(personal_service):
    events = [
        {
            "event_id": "e1",
            "content": "Version 2 is now released.",
            "source": "release-notes",
            "user_id": "local_user",
            "author_type": "user",
            "timestamp": time.time(),
        }
    ]
    evidence = SimpleNamespace(
        digest=evidence_digest,
        memory=SimpleNamespace(memory_operation_guard=guard, memory_operation_epoch=lambda: 1),
        watch_sources=AsyncMock(return_value=["release-notes"]),
        governance_revision=AsyncMock(return_value="r1"),
        watch_changes=AsyncMock(return_value=(events, time.time(), "e1")),
        current=AsyncMock(
            side_effect=lambda user, ids: [
                e for e in events if e["event_id"] in ids and e["user_id"] == user
            ]
        ),
    )
    matched = {
        "matched": True,
        "summary": "Version 2 is available.",
        "next_step": "Read the release notes.",
        "citations": [{"event_id": "e1", "quote": "Version 2 is now released."}],
    }
    generate = AsyncMock(
        side_effect=lambda _prompt, review: json.dumps({"supported": True} if review else matched)
    )
    service = AttentionWatchService(personal_service, evidence, generate)
    bind_attention_watch_service(service)
    yield SimpleNamespace(
        service=service,
        tasks=personal_service,
        evidence=evidence,
        events=events,
        generate=generate,
        matched=matched,
    )
    bind_attention_watch_service(None)


def command(key="create", **fields):
    return WatchMutation(
        request_id=key,
        action="create",
        fields=WatchFields(
            title="Release",
            condition="Tell me when version 2 ships",
            sources=["release-notes"],
            **fields,
        ),
    )


async def create(watches, key="create", **fields):
    return (await watches.service.mutate("local_user", command(key, **fields))).watch


async def test_match_is_durable_once_and_has_recheckable_evidence(watches):
    h = watches
    watch = await create(h)
    await h.service.tick("local_user")
    result = await h.service.get("local_user", watch.id)
    assert result.status == "matched" and result.result.summary == h.matched["summary"]
    await h.service.tick("local_user")
    assert h.generate.await_count == 2
    with pytest.raises(TaskNotFoundError):
        await h.service.get("other-user", watch.id)
    h.events.clear()
    result = await h.service.get("local_user", watch.id)
    assert result.result is None and result.check_status == "invalidated"


async def test_mutations_replay_do_not_resurrect_after_delete_or_full_clear(watches):
    h = watches
    watch = await create(h)
    replay = await h.service.mutate("local_user", command())
    assert replay.replayed and replay.watch.id == watch.id
    with pytest.raises(TaskConflictError):
        await h.service.mutate("local_user", command(expires_at=time.time() + 3600))
    await h.service.mutate(
        "local_user",
        WatchMutation(
            request_id="delete", action="delete", watch_id=watch.id, expected_version=watch.version
        ),
    )
    assert (await h.service.mutate("local_user", command())).watch is None
    await create(h, "second")
    async with h.tasks.user_content_clear_boundary():
        assert await h.tasks.store.clear_user_content() == 1
    assert (await h.service.mutate("local_user", command("second"))).watch is None
    assert not (await h.service.page("local_user")).items


@pytest.mark.parametrize(
    "action", ["pause", "stop", "delete", "edit", "expire", "clear", "source_deleted", "correction"]
)
async def test_inflight_check_cannot_publish_after_its_scope_changes(watches, action):
    h = watches
    watch = await create(h)

    async def generate(_prompt, review):
        if review:
            return '{"supported":true}'
        if action in {"pause", "stop", "delete"}:
            await h.service.mutate(
                "local_user",
                WatchMutation(
                    request_id="change",
                    action=action,
                    watch_id=watch.id,
                    expected_version=watch.version,
                ),
            )
        elif action == "edit":
            await h.service.mutate(
                "local_user",
                WatchMutation(
                    request_id="edit",
                    action="update",
                    watch_id=watch.id,
                    expected_version=watch.version,
                    fields=WatchFields(
                        title="Release", condition="Version 3 ships", sources=["release-notes"]
                    ),
                ),
            )
        elif action == "expire":
            async with sqlite_connection_async(h.tasks.store.db_path) as db:
                await db.execute(
                    "UPDATE attention_watches SET fields_json=json_set(fields_json,'$.expires_at',1)"
                )
                await db.commit()
        elif action == "clear":
            async with h.tasks.user_content_clear_boundary():
                await h.tasks.store.clear_user_content()
            h.evidence.memory.memory_operation_epoch = lambda: 2
        elif action == "source_deleted":
            h.events.clear()
        else:
            h.evidence.governance_revision.return_value = "r2"
        return json.dumps(h.matched)

    h.service.generate = generate
    await h.service.tick("local_user")
    assert all(item.result is None for item in (await h.service.page("local_user")).items)


async def test_paused_and_closed_linked_items_never_use_a_model(watches):
    h = watches
    watch = await create(h)
    await h.service.mutate(
        "local_user",
        WatchMutation(request_id="pause", action="pause", watch_id=watch.id, expected_version=1),
    )
    item = (
        await h.tasks.mutate(
            "local_user",
            TaskMutation(
                request_id="item", action="create", fields=ItemPatch(title="Release review")
            ),
            actor="user",
        )
    ).item
    linked = await create(h, "linked", item_id=item.id)
    await h.tasks.mutate(
        "local_user",
        TaskMutation(
            request_id="close",
            action="update",
            item_id=item.id,
            expected_version=1,
            fields=ItemPatch(status="completed"),
        ),
        actor="user",
    )
    await h.service.tick("local_user")
    h.generate.assert_not_awaited()
    assert (await h.service.get("local_user", linked.id)).status == "stopped"


async def test_no_material_and_durable_daily_budget_bound_model_usage(watches):
    h = watches
    watch = await create(h)
    h.evidence.watch_changes.return_value = ([], time.time(), "empty")
    await h.service.tick("local_user")
    h.generate.assert_not_awaited()
    h.evidence.watch_changes.return_value = (h.events, time.time(), "e1")
    h.generate.side_effect = lambda _prompt, _review: '{"matched":false}'
    for _ in range(3):
        async with sqlite_connection_async(h.tasks.store.db_path) as db:
            await db.execute(
                "UPDATE attention_watches SET last_checked_at=0 WHERE id=?", (watch.id,)
            )
            await db.commit()
        await h.service.tick("local_user")
    assert h.generate.await_count == 2


async def test_unknown_sources_false_quotes_and_review_rejection_never_match(watches):
    h = watches
    unknown = command()
    unknown.fields.sources = ["other-user-mail"]
    with pytest.raises(ValueError, match="authorized saved material"):
        await h.service.mutate("local_user", unknown)
    watch = await create(h)
    h.matched["citations"][0]["quote"] = "fabricated quote"
    await h.service.tick("local_user")
    assert (await h.service.get("local_user", watch.id)).check_status == "failed"
    assert (await h.service.get("local_user", watch.id)).result is None
    h.matched["citations"][0]["quote"] = h.events[0]["content"]
    h.generate.side_effect = lambda _prompt, review: json.dumps(
        {"supported": False} if review else h.matched
    )
    async with sqlite_connection_async(h.tasks.store.db_path) as db:
        await db.execute("UPDATE attention_watches SET last_checked_at=0")
        await db.commit()
    await h.service.tick("local_user")
    assert (await h.service.get("local_user", watch.id)).result is None


async def test_source_forgetting_scrubs_result_content(watches):
    from _shared.sqlite_privacy import assert_sqlite_fragment_absent

    h = watches
    watch = await create(h)
    await h.service.tick("local_user")
    await h.tasks.store.forget_watch_events(["e1"])
    assert (await h.service.get("local_user", watch.id)).result is None
    assert_sqlite_fragment_absent(h.tasks.store.db_path, h.matched["summary"])


async def test_filtered_http_routes_and_current_user_tool_authorization(watches):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from magi.api.routers.personal_tasks import personal_tasks_router
    from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
    from magi.core.tool_context import ToolExecutionContext
    from magi.personal_tasks.watch_tools import AttentionWatchQueryTool, AttentionWatchUpdateTool
    from magi.bootstrap.attention_watches import AttentionWatchesModule

    message = SimpleNamespace(
        user_id="local_user",
        session_id="session",
        role="user",
        is_visible=True,
        replaced_by_message_id=None,
        content_text="Please watch the release notes for version 2.",
    )
    module = AttentionWatchesModule(
        SimpleNamespace(
            chat=SimpleNamespace(
                store=SimpleNamespace(list_messages_for_turn=AsyncMock(return_value=[message]))
            )
        )
    )
    watches.service.authorize = module._authorize
    context = ToolExecutionContext(
        agent_id="chat",
        env_vars={"user_id": "local_user", "session_id": "session", "turn_id": "turn"},
    )
    tool = AttentionWatchUpdateTool()
    params = {**command().model_dump(), "authorization_quote": "Invented request"}
    assert not (await tool.execute(params, context)).success
    params["authorization_quote"] = message.content_text
    result = await tool.execute(params, context)
    assert result.success
    identity = result.data["watch"]["id"]
    assert (await AttentionWatchQueryTool().execute({"watch_id": identity}, context)).success
    assert not (await tool.execute(params, ToolExecutionContext(agent_id="background"))).success
    app = FastAPI()
    app.include_router(
        _build_public_router(personal_tasks_router, _PUBLIC_ROUTE_METHODS["personal_tasks"]),
        prefix="/api/personal-tasks",
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        page = await client.get("/api/personal-tasks/watches")
        assert page.status_code == 200 and page.json()["items"][0]["id"] == identity
        assert (await client.get(f"/api/personal-tasks/watches/{identity}")).status_code == 200
        change = dict(request_id="pause", action="pause", watch_id=identity, expected_version=1)
        assert (await client.post("/api/personal-tasks/watch-mutations", json=change)).json()[
            "watch"
        ]["status"] == "paused"
        assert (
            await client.post(
                "/api/personal-tasks/watch-mutations", json={**change, "request_id": "conflict"}
            )
        ).status_code == 409
        assert (await client.get("/api/personal-tasks/watches/missing")).status_code == 404


async def test_notification_reconciliation_is_idempotent_and_retracts_invalid_results(
    watches, tmp_path, monkeypatch
):
    from magi.bootstrap.attention_watches import AttentionWatchesModule
    from magi.notifications.store import NotificationStore

    monkeypatch.setattr(
        "magi.bootstrap.attention_watches._emit_notification_added_signal", AsyncMock()
    )
    module = AttentionWatchesModule(
        SimpleNamespace(agent_runtime=SimpleNamespace(task_agent_manager=None))
    )
    module._tasks = watches.tasks
    module._memory = watches.evidence.memory
    module._service = watches.service
    module._notifications = NotificationStore(tmp_path / "notifications.db")
    module._notifications.ensure_schema()
    await create(watches)
    await module._run(None)
    await module._run(None)
    notices = module._notifications.list_by_kind(user_id="local_user", kind="attention_watch")
    assert len(notices) == 1
    assert watches.matched["summary"] not in notices[0].body
    watches.events.clear()
    await module._run(None)
    assert not module._notifications.list_by_kind(user_id="local_user", kind="attention_watch")
