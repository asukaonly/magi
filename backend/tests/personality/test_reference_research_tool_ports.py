from __future__ import annotations

from types import SimpleNamespace

import pytest

from magi.personality.reference_research.tool_ports import (
    ToolReferenceFetchPort,
    ToolReferenceSearchPort,
)


class _InvocationService:
    def __init__(self, result) -> None:  # type: ignore[no-untyped-def]
        self.result = result
        self.calls = []

    async def invoke(self, call, context):  # type: ignore[no-untyped-def]
        self.calls.append((call, context))
        return self.result


@pytest.mark.asyncio
async def test_search_port_uses_governed_web_search_invocation() -> None:
    invocation = _InvocationService(
        SimpleNamespace(
            success=True,
            data={"results": [{"title": "Source", "url": "https://example.com"}]},
        )
    )

    results = await ToolReferenceSearchPort(invocation).search("reference query", limit=3)

    assert results == [{"title": "Source", "url": "https://example.com"}]
    call, context = invocation.calls[0]
    assert call.name == "web-search"
    assert call.args == {"query": "reference query", "num_results": 3}
    assert context.tool_category == "web"
    assert context.execution_context.agent_id == "personality_generation"


@pytest.mark.asyncio
async def test_fetch_port_uses_safe_web_fetch_invocation() -> None:
    invocation = _InvocationService(
        SimpleNamespace(success=True, data={"title": "Source", "content": "Evidence"})
    )

    result = await ToolReferenceFetchPort(invocation).fetch(
        "https://example.com/source",
        max_chars=5000,
    )

    assert result["content"] == "Evidence"
    call, _ = invocation.calls[0]
    assert call.name == "web-fetch"
    assert call.args["url"] == "https://example.com/source"
    assert call.args["max_chars"] == 5000


@pytest.mark.asyncio
async def test_tool_ports_surface_web_failures() -> None:
    invocation = _InvocationService(
        SimpleNamespace(success=False, error="Network unavailable")
    )

    with pytest.raises(RuntimeError, match="Network unavailable"):
        await ToolReferenceSearchPort(invocation).search("reference query")
