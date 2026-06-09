"""Streaming behaviour of the OpenAI-compatible adapter."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from magi.llm.openai import OpenAIAdapter


def _delta_chunk(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content))]
    )


def _empty_chunk():
    # Some OpenAI-compatible providers emit a chunk with no choices — e.g. a
    # final usage-only chunk (stream_options.include_usage) or a keep-alive.
    return SimpleNamespace(choices=[])


def _fake_client_yielding(chunks):
    async def _stream():
        for c in chunks:
            yield c

    class _FakeCompletions:
        async def create(self, **kwargs):
            return _stream()

    class _FakeChat:
        def __init__(self):
            self.completions = _FakeCompletions()

    class _FakeClient:
        def __init__(self):
            self.chat = _FakeChat()

    return _FakeClient()


@pytest.mark.asyncio
async def test_chat_stream_skips_chunks_with_empty_choices() -> None:
    """A chunk with ``choices == []`` must be skipped, not raise IndexError."""
    adapter = OpenAIAdapter(api_key="k", model="m", provider="custom")
    adapter._client = _fake_client_yielding(
        [
            _delta_chunk("Hello"),
            _empty_chunk(),          # usage/keep-alive chunk → no choices
            _delta_chunk(" world"),
            _delta_chunk(None),      # delta present but content is None
        ]
    )

    out = [chunk async for chunk in adapter.chat_stream([{"role": "user", "content": "hi"}])]

    assert out == ["Hello", " world"]


@pytest.mark.asyncio
async def test_generate_stream_skips_chunks_with_empty_choices() -> None:
    """The prompt-streaming path has the same empty-choices guard."""
    adapter = OpenAIAdapter(api_key="k", model="m", provider="custom")
    adapter._client = _fake_client_yielding(
        [_delta_chunk("foo"), _empty_chunk(), _delta_chunk("bar")]
    )

    out = [chunk async for chunk in adapter.generate_stream("hi")]

    assert out == ["foo", "bar"]
