"""Read-only memory ports keep storage identities inside the host."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from magi.bootstrap.tool_capabilities import _HostMemoryQueryPort


@pytest.mark.asyncio
async def test_entity_lookup_uses_host_storage_without_exposing_path(monkeypatch):
    import magi.memory.l2.entities.catalog.lookup as lookup

    lookup_names = AsyncMock(return_value={"entity-1": "Example"})
    monkeypatch.setattr(lookup, "get_canonical_names", lookup_names)
    port = _HostMemoryQueryPort()
    port._service = SimpleNamespace(memory_db_path="/host/private/memory.db")
    assert await port.get_canonical_names({"entity-1"}) == {"entity-1": "Example"}
    lookup_names.assert_awaited_once_with("/host/private/memory.db", {"entity-1"})
    assert not hasattr(port, "memory_db_path")


@pytest.mark.asyncio
async def test_advisory_returns_data_and_not_a_live_store(monkeypatch):
    import magi.memory.provider as provider

    rows = [{"tool_name": "weather", "success_rate": 1.0}]
    store = SimpleNamespace(get_tool_advisory=AsyncMock(return_value=rows))
    monkeypatch.setattr(provider, "get_unified_memory", lambda: SimpleNamespace(l4=store))
    port = _HostMemoryQueryPort()
    assert await port.get_tool_advisory(tool_names=["weather"], task_context="forecast") == rows
    assert not hasattr(port, "get_l4_store")
