from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from magi.api.services.personality_reference_tools import (
    ToolReferenceFetchAdapter,
    ToolReferenceSearchAdapter,
)
from magi.personality.reference_research.ports import ReferenceFetchError


class _InvocationService:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.calls: list[tuple[Any, Any]] = []

    async def invoke(self, call: Any, context: Any) -> Any:
        self.calls.append((call, context))
        return self.result


@pytest.mark.asyncio
async def test_search_adapter_uses_governed_web_search_invocation() -> None:
    invocation = _InvocationService(
        SimpleNamespace(
            success=True,
            data={"results": [{"title": "Source", "url": "https://example.com"}]},
        )
    )

    results = await ToolReferenceSearchAdapter(invocation).search("reference query", limit=3)

    assert results == [{"title": "Source", "url": "https://example.com"}]
    call, context = invocation.calls[0]
    assert call.name == "web-search"
    assert call.args == {"query": "reference query", "num_results": 3}
    assert context.tool_category == "web"
    assert context.execution_context.agent_id == "personality_generation"


@pytest.mark.asyncio
async def test_fetch_adapter_uses_safe_web_fetch_invocation() -> None:
    invocation = _InvocationService(
        SimpleNamespace(success=True, data={"title": "Source", "content": "Evidence"})
    )

    result = await ToolReferenceFetchAdapter(invocation).fetch(
        "https://example.com/source",
        max_chars=5000,
    )

    assert result["content"] == "Evidence"
    call, _ = invocation.calls[0]
    assert call.name == "web-fetch"
    assert call.args["url"] == "https://example.com/source"
    assert call.args["max_chars"] == 5000


@pytest.mark.asyncio
async def test_search_adapter_surfaces_web_failures() -> None:
    invocation = _InvocationService(
        SimpleNamespace(success=False, error="Network unavailable")
    )

    with pytest.raises(RuntimeError, match="Network unavailable"):
        await ToolReferenceSearchAdapter(invocation).search("reference query")


@pytest.mark.asyncio
async def test_fetch_adapter_preserves_fake_ip_compatibility_code() -> None:
    invocation = _InvocationService(
        SimpleNamespace(
            success=False,
            error="Blocked web-fetch URL",
            data={"reason_code": "FAKE_IP_COMPATIBILITY_REQUIRED"},
        )
    )

    with pytest.raises(ReferenceFetchError) as exc_info:
        await ToolReferenceFetchAdapter(invocation).fetch("https://example.com")

    assert exc_info.value.code == "FAKE_IP_COMPATIBILITY_REQUIRED"
