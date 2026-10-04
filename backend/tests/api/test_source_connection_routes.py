"""Connection identity is mandatory through the product's public source router."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from magi_plugin_sdk.runtime import PluginConnection
from magi_plugin_sdk.sources import SourceSpec

from magi.api.routers import sources
from magi.api.routes import _PUBLIC_ROUTE_METHODS, _build_public_router
from magi.events.contracts import SourceStateFlushCommand, SourceSyncCommand


def setup_api(monkeypatch):
    connection = PluginConnection(connection_id="account-b", plugin_id="notes", display_name="Work", enabled=True)
    source = SimpleNamespace(connection=connection, supports_pull_sync=True, supports_state_flush=True, request_activation_authorization=AsyncMock(return_value={"authorized": True}))
    registry = Mock()
    registry.resolve_source.side_effect = lambda source_name, connection_id: (
        ("notes", "notes.source", source, SourceSpec(source_id="notes.source", display_name="Notes"))
        if source_name == "notes" and connection_id == "account-b" else None
    )
    queue = SimpleNamespace(enqueue_source_sync=AsyncMock(return_value=7), enqueue_source_state_flush=AsyncMock(return_value=8))
    monkeypatch.setattr(sources, "get_config", lambda: None)
    monkeypatch.setattr(sources, "resolve_source_registry", lambda: registry)
    monkeypatch.setattr(sources, "require_runtime_command_queue", lambda: queue)
    app = FastAPI()
    app.include_router(_build_public_router(sources.sources_router, _PUBLIC_ROUTE_METHODS["sources"]), prefix="/api/sources")
    return TestClient(app), queue, source


@pytest.mark.parametrize("action", ["sync", "flush-state", "authorize"])
def test_public_source_action_requires_connection_query(monkeypatch, action):
    client, queue, _ = setup_api(monkeypatch)
    assert client.post(f"/api/sources/notes/{action}", json={}).status_code == 422
    queue.enqueue_source_sync.assert_not_called()
    queue.enqueue_source_state_flush.assert_not_called()


@pytest.mark.parametrize("action", ["sync", "flush-state", "authorize"])
@pytest.mark.parametrize(
    "language,detail", [("en", "Source not found"), ("zh-CN", "未找到数据来源来源")]
)
def test_unknown_source_connection_returns_localized_error_without_side_effects(
    monkeypatch, action, language, detail
):
    from magi.i18n import language_context

    client, queue, source = setup_api(monkeypatch)
    with language_context(language):
        response = client.post(f"/api/sources/notes/{action}?connection_id=unknown", json={})
    assert response.status_code == 404
    assert response.json() == {"detail": detail}
    queue.enqueue_source_sync.assert_not_awaited()
    queue.enqueue_source_state_flush.assert_not_awaited()
    source.request_activation_authorization.assert_not_awaited()


@pytest.mark.parametrize(
    "action,body,mode,first_context,scope,days,start,end",
    [
        ("sync", None, "latest", False, None, None, None, None),
        ("sync", {"first_context": True}, "latest", True, None, None, None, None),
        (
            "sync",
            {"mode": "backfill", "backfill_scope": "last_30_days"},
            "backfill",
            False,
            "last_30_days",
            30,
            None,
            None,
        ),
        (
            "sync",
            {
                "mode": "backfill",
                "backfill_scope": "custom",
                "backfill_start_date": "2026-06-01",
                "backfill_end_date": "2026-06-30",
            },
            "backfill",
            False,
            "custom",
            None,
            "2026-06-01",
            "2026-06-30",
        ),
        ("flush-state", None, None, None, None, None, None, None),
    ],
)
def test_source_actions_enqueue_one_exact_connection_command(
    monkeypatch, action, body, mode, first_context, scope, days, start, end
):
    client, queue, _ = setup_api(monkeypatch)
    response = client.post(
        f"/api/sources/notes/{action}?connection_id=account-b",
        **({"json": body} if body is not None else {}),
    )
    assert response.status_code == 200
    expected_response = {
        "queued": True,
        "source_name": "notes",
        "connection_id": "account-b",
        "command_id": 7 if action == "sync" else 8,
    }
    expected_command = {
        "source": "api.sources",
        "source_name": "notes",
        "connection_id": "account-b",
    }
    if action == "sync":
        expected_response["mode"] = mode
        expected_response.update(
            {
                k: v
                for k, v in {
                    "backfill_scope": scope,
                    "backfill_days": days,
                    "backfill_start_date": start,
                    "backfill_end_date": end,
                }.items()
                if v is not None
            }
        )
        expected_command.update(
            first_context=first_context,
            sync_mode=mode,
            backfill_scope=scope,
            backfill_days=days,
            backfill_start_date=start,
            backfill_end_date=end,
        )
        queue.enqueue_source_sync.assert_awaited_once()
        queue.enqueue_source_state_flush.assert_not_awaited()
        command = queue.enqueue_source_sync.await_args.args[0]
    else:
        queue.enqueue_source_state_flush.assert_awaited_once()
        queue.enqueue_source_sync.assert_not_awaited()
        command = queue.enqueue_source_state_flush.await_args.args[0]
    assert response.json() == expected_response
    assert {
        k: v for k, v in command.to_payload().items() if k not in {"created_at", "correlation_id"}
    } == expected_command


def test_source_authorization_forwards_fields_once(monkeypatch):
    client, queue, source = setup_api(monkeypatch)
    result = client.post(
        "/api/sources/notes/authorize?connection_id=account-b",
        json={"field_values": {"scope": "notes"}},
    )
    assert result.status_code == 200
    assert result.json() == {"authorized": True}
    source.request_activation_authorization.assert_awaited_once_with({"scope": "notes"})
    queue.enqueue_source_sync.assert_not_awaited()
    queue.enqueue_source_state_flush.assert_not_awaited()


@pytest.mark.parametrize("command_type", [SourceSyncCommand, SourceStateFlushCommand])
def test_runtime_source_command_cannot_omit_or_blank_identity(command_type):
    with pytest.raises(TypeError):
        command_type(source="test", source_name="notes")
    with pytest.raises(ValueError):
        command_type(source="test", source_name="notes", connection_id="")
    assert command_type(source="test", source_name="notes", connection_id="account-b").to_payload()["connection_id"] == "account-b"


def test_memory_readiness_requires_a_connection(monkeypatch):
    client, _, _ = setup_api(monkeypatch)
    assert client.get("/api/sources/notes/memory-readiness?max_wait_ms=0").status_code == 422
    assert client.get("/api/sources/notes/memory-readiness?connection_id=unknown&max_wait_ms=0").status_code == 404


@pytest.mark.asyncio
async def test_status_reads_connection_settings_and_scheduler_identity(monkeypatch):
    from magi.api.routers import source_status_projection as projection
    from magi_plugin_sdk.contracts import PluginContribution
    from magi.scheduler.contracts import ScheduledTargetState, ScheduledTargetType

    item = PluginContribution(plugin_id="notes", contribution_id="account-b:notes.source", contribution_type="source", display_name="Notes", metadata={"source_type": "notes", "connection_id": "account-b"})
    connection = PluginConnection(connection_id="account-b", plugin_id="notes", display_name="Work", enabled=True, revision=4, settings={"sources": {"notes": {"enabled": True, "sync_interval_minutes": 7}}})
    source = SimpleNamespace(connection=connection, supports_pull_sync=True, supports_state_flush=False)
    registry = Mock()
    registry.resolve_source.return_value = ("notes", item.contribution_id, source, None)
    repository = SimpleNamespace(
        get_target_state=AsyncMock(return_value=ScheduledTargetState(ScheduledTargetType.SOURCE_SYNC, "unused")),
        get_schedule=AsyncMock(return_value=None), get_recurring_target_binding=AsyncMock(return_value=None),
        get_latest_source_sync_job=AsyncMock(return_value=None),
    )
    package = SimpleNamespace(manifest=SimpleNamespace(icon="", plugin_dir=""), current_settings={"sources": {"notes": {"enabled": False}}})
    monkeypatch.setattr(projection, "_load_plugin_i18n", lambda *_: None)
    result = await projection._build_source_status(item, packages={"notes": package}, source_registry=registry, repository=repository, runtime_base_dir="/test")
    assert result["connection_id"] == "account-b"
    assert result["connection_display_name"] == "Work"
    assert result["connection_revision"] == 4
    assert result["enabled"] is True
    assert result["sync_interval_minutes"] == 7
    assert repository.get_target_state.await_args.args[1] == "account-b:notes"
    registry.resolve_source.assert_called_once_with("notes", connection_id="account-b")
