"""Read-only memory ports keep storage identities inside the host."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from magi.bootstrap.tool_capabilities import _HostMemoryQueryPort


@pytest.mark.asyncio
async def test_advisory_forwards_tool_and_task_scope_to_host(monkeypatch):
    import magi.memory.provider as provider

    rows = [{"tool_name": "weather", "success_rate": 1.0}]
    store = SimpleNamespace(get_tool_advisory=AsyncMock(return_value=rows))
    monkeypatch.setattr(provider, "get_unified_memory", lambda: SimpleNamespace(l4=store))
    port = _HostMemoryQueryPort()
    assert await port.get_tool_advisory(tool_names=["weather"], task_context="forecast") == rows
    store.get_tool_advisory.assert_awaited_once_with(
        tool_names=["weather"], task_context="forecast"
    )
