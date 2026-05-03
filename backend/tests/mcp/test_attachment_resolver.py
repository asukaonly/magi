from unittest.mock import AsyncMock, MagicMock

import pytest

from magi.mcp.attachment_resolver import resolve_attachment_resources
from magi.mcp import attachment_resolver as resolver_mod
from magi.mcp.resource_cache import MCPResourceCache


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    cache = MCPResourceCache(ttl_seconds=10)
    monkeypatch.setattr(resolver_mod, "get_default_cache", lambda: cache)
    yield cache


@pytest.mark.asyncio
async def test_passes_through_non_mcp_attachments(monkeypatch):
    monkeypatch.setattr(resolver_mod, "get_active_manager", lambda: None)
    out = await resolve_attachment_resources(
        [{"kind": "image", "attachment_id": "x"}]
    )
    assert out == [{"kind": "image", "attachment_id": "x"}]


@pytest.mark.asyncio
async def test_resolves_mcp_resource_into_block(monkeypatch):
    manager = MagicMock()
    manager.read_resource = AsyncMock(
        return_value={
            "contents": [
                {
                    "uri": "file:///x.txt",
                    "mimeType": "text/plain",
                    "text": "hello world",
                }
            ]
        }
    )
    monkeypatch.setattr(resolver_mod, "get_active_manager", lambda: manager)

    out = await resolve_attachment_resources(
        [{"kind": "mcp_resource", "server_id": "demo", "uri": "file:///x.txt"}]
    )
    assert len(out) == 1
    assert "<mcp_resource" in out[0]["resolved_text"]
    assert "hello world" in out[0]["resolved_text"]
    manager.read_resource.assert_awaited_once_with("demo", "file:///x.txt")


@pytest.mark.asyncio
async def test_records_error_when_manager_missing(monkeypatch):
    monkeypatch.setattr(resolver_mod, "get_active_manager", lambda: None)
    out = await resolve_attachment_resources(
        [{"kind": "mcp_resource", "server_id": "demo", "uri": "u"}]
    )
    assert out[0]["resolved_error"] == "MCP manager not initialized"
    assert "resolved_text" not in out[0]


@pytest.mark.asyncio
async def test_records_error_when_read_fails(monkeypatch):
    manager = MagicMock()
    manager.read_resource = AsyncMock(side_effect=RuntimeError("upstream 503"))
    monkeypatch.setattr(resolver_mod, "get_active_manager", lambda: manager)

    out = await resolve_attachment_resources(
        [{"kind": "mcp_resource", "server_id": "demo", "uri": "u"}]
    )
    assert "503" in out[0]["resolved_error"]


@pytest.mark.asyncio
async def test_skips_already_resolved_attachments(monkeypatch):
    manager = MagicMock()
    manager.read_resource = AsyncMock()
    monkeypatch.setattr(resolver_mod, "get_active_manager", lambda: manager)

    pre = {"kind": "mcp_resource", "server_id": "s", "uri": "u", "resolved_text": "done"}
    out = await resolve_attachment_resources([pre])
    assert out[0]["resolved_text"] == "done"
    manager.read_resource.assert_not_called()


@pytest.mark.asyncio
async def test_uses_cache_for_repeated_uri(monkeypatch):
    manager = MagicMock()
    manager.read_resource = AsyncMock(
        return_value={"contents": [{"uri": "u", "mimeType": "text/plain", "text": "x"}]}
    )
    monkeypatch.setattr(resolver_mod, "get_active_manager", lambda: manager)

    items = [
        {"kind": "mcp_resource", "server_id": "s", "uri": "u"},
        {"kind": "mcp_resource", "server_id": "s", "uri": "u"},
    ]
    out = await resolve_attachment_resources(items)
    assert len(out) == 2
    assert all("resolved_text" in o for o in out)
    manager.read_resource.assert_awaited_once()
