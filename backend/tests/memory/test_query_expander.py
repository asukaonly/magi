"""Tests for query expander."""

from __future__ import annotations

import pytest

from magi.memory.hybrid_retrieval.query_expander import QueryExpander


class _MockBridge:
    """Minimal mock for LLM provider bridge."""

    def __init__(self, response: str):
        self._response = response

    async def chat(self, **kwargs):
        return self._response


class _FailingBridge:
    async def chat(self, **kwargs):
        raise RuntimeError("LLM unavailable")


@pytest.mark.asyncio
async def test_expand_returns_reformulations():
    bridge = _MockBridge('["what food do I enjoy", "which dishes do I prefer"]')
    expander = QueryExpander(bridge)
    result = await expander.expand("what food do I like")
    assert len(result) == 2
    assert "what food do I enjoy" in result
    assert "which dishes do I prefer" in result


@pytest.mark.asyncio
async def test_expand_strips_whitespace():
    bridge = _MockBridge('[" padded query ", "  another  "]')
    expander = QueryExpander(bridge)
    result = await expander.expand("test")
    assert result == ["padded query", "another"]


@pytest.mark.asyncio
async def test_expand_caps_at_two():
    bridge = _MockBridge('["a", "b", "c", "d"]')
    expander = QueryExpander(bridge)
    result = await expander.expand("test")
    assert len(result) == 2


@pytest.mark.asyncio
async def test_expand_handles_no_bridge():
    expander = QueryExpander(None)
    result = await expander.expand("test")
    assert result == []


@pytest.mark.asyncio
async def test_expand_handles_llm_failure():
    bridge = _FailingBridge()
    expander = QueryExpander(bridge)
    result = await expander.expand("test")
    assert result == []


@pytest.mark.asyncio
async def test_expand_handles_invalid_json():
    bridge = _MockBridge("This is not JSON at all")
    expander = QueryExpander(bridge)
    result = await expander.expand("test")
    assert result == []


@pytest.mark.asyncio
async def test_expand_handles_json_with_surrounding_text():
    bridge = _MockBridge('Here are the queries: ["query one", "query two"] hope this helps!')
    expander = QueryExpander(bridge)
    result = await expander.expand("test")
    assert len(result) == 2


@pytest.mark.asyncio
async def test_expand_filters_empty_strings():
    bridge = _MockBridge('["good query", "", "  ", "another good"]')
    expander = QueryExpander(bridge)
    result = await expander.expand("test")
    assert result == ["good query", "another good"]
