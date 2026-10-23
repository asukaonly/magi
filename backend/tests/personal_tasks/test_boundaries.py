"""Public HTTP routes and Agent tools share the same durable owner."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest
from magi.core.tool_context import ToolExecutionContext
from magi.core.tool_capabilities import ToolCapabilities

from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.api.routers.personal_tasks import personal_tasks_router
from magi.personal_tasks.tools import PersonalTaskQueryTool, PersonalTaskUpdateTool


@pytest.mark.asyncio
async def test_public_route_tool_and_ui_share_ids_versions_and_provenance(personal_service):
    app = FastAPI()
    app.include_router(
        _build_public_router(personal_tasks_router, _PUBLIC_ROUTE_METHODS["personal_tasks"]),
        prefix="/api/personal-tasks",
    )
    context = ToolExecutionContext(
        agent_id="chat",
        env_vars={"user_id": "local_user", "session_id": "session-a", "turn_id": "turn-a"},
    )
    update = PersonalTaskUpdateTool()
    result = await update.execute(
        {
            "request_id": "create-1",
            "action": "create",
            "fields": {"title": "Prepare quote", "body_md": "Budget 40,000"},
        },
        context,
    )
    assert result.success
    item = result.data["item"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        listed = await client.get("/api/personal-tasks")
        assert listed.status_code == 200 and listed.json()["items"][0]["id"] == item["id"]
        assert item["references"] == [
            {"kind": "chat", "id": "turn-a", "label": "", "session_id": "session-a"}
        ]
        patch = {
            "request_id": "ui-progress",
            "action": "progress",
            "item_id": item["id"],
            "expected_version": 1,
            "fields": {"status": "waiting"},
            "note": "Waiting for parameters",
        }
        changed = await client.post("/api/personal-tasks/mutations", json=patch)
        assert changed.status_code == 200 and changed.json()["item"]["version"] == 2
        assert (
            await client.post(
                "/api/personal-tasks/mutations", json={**patch, "request_id": "stale"}
            )
        ).status_code == 409
        assert (
            await client.get("/api/personal-tasks", params={"view": "unknown"})
        ).status_code == 422
        detail = await PersonalTaskQueryTool().execute({"item_id": item["id"]}, context)
        assert detail.success and detail.data["item"]["status"] == "waiting"
        removed = await client.post(
            "/api/personal-tasks/mutations",
            json={
                "request_id": "delete",
                "action": "delete",
                "item_id": item["id"],
                "expected_version": 2,
            },
        )
        assert removed.status_code == 200
        assert (await client.get("/api/personal-tasks/" + item["id"])).status_code == 404
        replay = await update.execute(
            {
                "request_id": "create-1",
                "action": "create",
                "fields": {"title": "Prepare quote", "body_md": "Budget 40,000"},
            },
            context,
        )
        assert replay.success and replay.data["item"] is None


@pytest.mark.asyncio
async def test_dated_capture_uses_host_client_timezone_and_rejects_missing_context(
    personal_service,
):
    tool = PersonalTaskUpdateTool()
    assert {p.name for p in tool.schema.parameters if p.required} >= {"request_id", "action"}
    params = {
        "request_id": "dated",
        "action": "create",
        "fields": {"title": "Collect camera", "due": "2030-01-05"},
    }
    context = ToolExecutionContext(
        agent_id="chat",
        env_vars={"user_id": "local_user", "session_id": "session", "turn_id": "turn"},
    )
    denied = await tool.execute(params, context)
    assert not denied.success and "timezone" in denied.error
    context.capabilities = ToolCapabilities(
        environment=SimpleNamespace(
            read_client=AsyncMock(return_value={"status": "available", "timezone": "Asia/Shanghai"})
        )
    )
    result = await tool.execute(params, context)
    assert result.success and result.data["item"]["timezone"] == "Asia/Shanghai"
    assert not (await tool.execute(params, ToolExecutionContext(agent_id="background"))).success


@pytest.mark.asyncio
async def test_selected_item_metadata_cannot_bypass_host_ownership(personal_service, monkeypatch):
    from fastapi import HTTPException
    from magi.api.routers import messages_dispatch
    from magi.api.routers.messages_models import UserMessageRequest
    from magi.personal_tasks.models import ItemPatch, TaskMutation

    monkeypatch.setattr(
        messages_dispatch, "build_bootstrap_l2_priority_metadata", AsyncMock(return_value={})
    )
    monkeypatch.setattr(messages_dispatch, "get_current_personality", lambda: "test")
    item = (
        await personal_service.mutate(
            "local_user",
            TaskMutation(
                request_id="create", action="create", fields=ItemPatch(title="Selected task")
            ),
            actor="user",
        )
    ).item
    request = UserMessageRequest(
        message="Continue",
        user_id="local_user",
        session_id="session",
        metadata={"personal_task_id": "forged"},
    )
    metadata, _ = await messages_dispatch._prepare_api_dispatch_metadata(request)
    assert "personal_task_id" not in metadata
    request.personal_task_id = item.id
    metadata, _ = await messages_dispatch._prepare_api_dispatch_metadata(request)
    assert metadata["personal_task_id"] == item.id
    request.user_id = "another-user"
    with pytest.raises(HTTPException) as error:
        await messages_dispatch._prepare_api_dispatch_metadata(request)
    assert error.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "proposals",
    [
        [{"key": "valid", "title": "Valid"}, {"key": "blank", "title": "   "}],
        [{"key": "same", "title": "First"}, {"key": "same", "title": "Second"}],
        [{"key": str(index), "title": "Too many"} for index in range(21)],
        [{"key": "x", "title": "Forged", "status": "active"}],
    ],
)
async def test_invalid_plugin_candidates_are_rejected_before_any_task_write(
    personal_service, proposals
):
    from magi.personal_tasks.source_proposals import ingest_source_task_proposals

    with pytest.raises(ValueError):
        await ingest_source_task_proposals(
            proposals,
            connection_id="connection",
            source_id="notes",
            object_id="object",
            event_id="event",
        )
    assert (await personal_service.store.query("local_user", view="all")).total == 0


@pytest.mark.asyncio
async def test_query_keeps_lists_bounded_and_returns_complete_detail_history(personal_service):
    from magi.personal_tasks.models import TaskMutation, ItemPatch

    body = "Preserve original context. " * 300
    item = (
        await personal_service.mutate(
            "local_user",
            TaskMutation(
                request_id="create",
                action="create",
                fields=ItemPatch(title="Long context", body_md=body),
            ),
            actor="user",
        )
    ).item
    for version in range(1, 53):
        await personal_service.mutate(
            "local_user",
            TaskMutation(
                request_id=f"progress-{version}",
                action="progress",
                item_id=item.id,
                expected_version=version,
                fields=ItemPatch(status="active"),
                note=f"Progress {version}",
            ),
            actor="user",
        )
    context = ToolExecutionContext(agent_id="chat", env_vars={"user_id": "local_user"})
    tool = PersonalTaskQueryTool()
    listing = await tool.execute({}, context)
    assert (
        listing.data["items"][0]["body_truncated"]
        and len(listing.data["items"][0]["body_preview"]) == 240
    )
    assert "body_md" not in listing.data["items"][0]
    detail = await tool.execute({"item_id": item.id}, context)
    assert detail.data["item"]["body_md"] == body
    assert len(detail.data["changes"]) == 50 and detail.data["next_history_offset"] == 50
    rest = await tool.execute({"item_id": item.id, "history_offset": 50}, context)
    assert len(rest.data["changes"]) == 3 and rest.data["next_history_offset"] is None


@pytest.mark.asyncio
async def test_first_date_on_an_undated_capture_binds_client_timezone(personal_service):
    from magi.personal_tasks.models import TaskMutation, ItemPatch

    item = (
        await personal_service.mutate(
            "local_user",
            TaskMutation(
                request_id="capture", action="create", fields=ItemPatch(title="Undated task")
            ),
            actor="user",
        )
    ).item
    context = ToolExecutionContext(
        agent_id="chat",
        env_vars={"user_id": "local_user", "session_id": "session", "turn_id": "turn"},
        capabilities=ToolCapabilities(
            environment=SimpleNamespace(
                read_client=AsyncMock(
                    return_value={"status": "available", "timezone": "Asia/Shanghai"}
                )
            )
        ),
    )
    tool = PersonalTaskUpdateTool()
    result = await tool.execute(
        {
            "request_id": "date",
            "action": "update",
            "item_id": item.id,
            "expected_version": 1,
            "fields": {"defer_until": "2030-01-05"},
        },
        context,
    )
    assert result.success and result.data["item"]["timezone"] == "Asia/Shanghai"
    context.capabilities.environment.read_client.return_value = {
        "status": "available",
        "timezone": "America/New_York",
    }
    next_result = await tool.execute(
        {
            "request_id": "revise",
            "action": "update",
            "item_id": item.id,
            "expected_version": 2,
            "fields": {"due": "2030-01-06"},
        },
        context,
    )
    assert next_result.success and next_result.data["item"]["timezone"] == "Asia/Shanghai"
