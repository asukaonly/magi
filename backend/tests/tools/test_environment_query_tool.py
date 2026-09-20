"""Verify environment provenance through host ports and durable stores."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from magi.bootstrap.tool_capabilities import build_tool_capabilities, reset_tool_capabilities
from magi.chat.store import ChatStore
from magi.core.client_environment import CLIENT_ENVIRONMENT_MAX_AGE_SECONDS
from magi.location.models import LocationSample
from magi.location.store import LocationSampleStore
from magi.tools.builtin.current_time_tool import CurrentTimeTool
from magi.tools.builtin.environment_query_tool import EnvironmentQueryTool
from magi.tools.core_tools import CORE_TOOL_CLASSES
from magi.tools.schema import ToolExecutionContext
from magi.tools.system_tools import resolve_resident_system_tools


@pytest.fixture
def environment(runtime_paths_with_schema, monkeypatch):
    chat = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    location = LocationSampleStore(db_path=str(runtime_paths_with_schema.memory_db_path))
    monkeypatch.setattr("magi.chat.provider.get_chat_store", lambda: chat)
    monkeypatch.setattr("magi.location.provider.get_location_sample_store", lambda: location)
    reset_tool_capabilities()
    context = ToolExecutionContext(
        agent_id="chat",
        workspace="/service/workspace",
        env_vars={"user_id": "alice", "session_id": "session-a", "turn_id": "turn-a"},
        capabilities=build_tool_capabilities(),
    )
    yield chat, location, context
    reset_tool_capabilities()


async def _client(chat, *, age=0, value=None):
    await chat.create_user_turn_once(
        user_id="alice",
        session_id="session-a",
        turn_id="turn-a",
        message_text="Hello",
        created_at_ms=int((time.time() - age) * 1000),
        request_fingerprint="same-turn",
        runtime_envelope={
            "client_environment": value or {"os": "windows", "timezone": "Pacific/Honolulu"}
        },
    )


@pytest.mark.asyncio
async def test_client_and_host_are_separate_and_clock_uses_client_timezone(environment):
    chat, _, context = environment
    await _client(chat)
    result = await EnvironmentQueryTool().execute({"section": "all"}, context)
    assert result.success
    assert result.data["client"]["os"] == "windows"
    assert result.data["client"]["subject"] == "interaction_client"
    assert result.data["service"]["subject"] == "service_host"
    assert result.data["service"]["workspace"] == "/service/workspace"
    assert result.data["service"]["client_device_access"] == "not_established"
    assert result.data["location"]["user_location"] == "unknown"
    clock = await CurrentTimeTool().execute({}, context)
    assert clock.data["timezone"] == "Pacific/Honolulu"
    assert clock.data["utc_offset"] == "-1000"
    assert clock.data["basis"] == "interaction_client"
    host_clock = await CurrentTimeTool().execute({"target": "service"}, context)
    assert host_clock.data["basis"] == "service_host"


@pytest.mark.asyncio
async def test_stale_snapshot_is_never_used_as_current_client_time(environment):
    chat, _, context = environment
    await _client(chat, age=CLIENT_ENVIRONMENT_MAX_AGE_SECONDS + 1)
    result = await EnvironmentQueryTool().execute({}, context)
    assert result.data["client"]["status"] == "stale"
    clock = await CurrentTimeTool().execute({"target": "client"}, context)
    assert not clock.success
    assert clock.error_code == "CLIENT_TIMEZONE_UNAVAILABLE"
    automatic = await CurrentTimeTool().execute({}, context)
    assert automatic.data["basis"] == "service_host"
    assert automatic.data["client_context_status"] == "stale"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value", [("user_id", "bob"), ("session_id", "session-b"), ("turn_id", "turn-b")]
)
async def test_client_snapshot_never_crosses_turn_scope(environment, field, value):
    chat, _, context = environment
    await _client(chat)
    context.env_vars[field] = value
    result = await EnvironmentQueryTool().execute({}, context)
    assert result.data["client"]["status"] == "unknown"
    assert "timezone" not in result.data["client"]


@pytest.mark.asyncio
async def test_invalid_persisted_context_is_unknown(environment):
    chat, _, context = environment
    await _client(chat, value={"os": "windows", "timezone": "invalid/zone"})
    result = await EnvironmentQueryTool().execute({}, context)
    assert result.data["client"]["status"] == "unknown"


@pytest.mark.asyncio
async def test_location_is_read_only_host_evidence_with_per_source_freshness(environment):
    _, location, context = environment
    now = time.time()
    for source, sampled_at, city in [
        ("wifi", now - 8000, "Old city"),
        ("ipgeo", now - 5, "Exit city"),
        ("photo", now, "Holiday city"),
    ]:
        await location.insert(
            LocationSample(
                sample_id="",
                source=source,
                sampled_at=sampled_at,
                city=city,
                lat=1.25,
                lng=2.5,
                accuracy_m=10000,
            )
        )
    result = await EnvironmentQueryTool().execute({"section": "location"}, context)
    assert set(result.data) == {"location"}
    snapshot = result.data["location"]
    assert snapshot["subject"] == "service_host"
    assert snapshot["user_location"] == "unknown"
    assert len(snapshot["observations"]) == 2
    wifi, ip = snapshot["observations"]
    assert wifi["freshness"] == "stale"
    assert ip["freshness"] == "fresh"
    assert ip["accuracy_m"] is None
    assert "lat" not in ip and "lng" not in ip


@pytest.mark.asyncio
async def test_missing_environment_ports_are_explicit():
    result = await EnvironmentQueryTool().execute(
        {"section": "all"}, ToolExecutionContext(agent_id="test")
    )
    assert result.data["client"]["status"] == "unavailable"
    assert result.data["location"]["status"] == "unavailable"
    assert result.data["service"]["status"] == "available"


def test_environment_query_is_registered_and_resident():
    assert EnvironmentQueryTool in CORE_TOOL_CLASSES
    registry = SimpleNamespace(
        list_tools=lambda category=None: [] if category else ["environment_query"]
    )
    assert "environment_query" in resolve_resident_system_tools(registry)
