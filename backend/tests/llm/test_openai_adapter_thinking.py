"""Tests for OpenAI adapter behaviour.

Thinking-control is now handled exclusively by the provider bridge
(``LLMProviderBridge._apply_provider_options``); the adapter no longer accepts
``disable_thinking`` directly.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from magi.llm.openai import OpenAIAdapter


class _FakeEmbeddingsClient:
    def __init__(self) -> None:
        self.kwargs = {}

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3])])


class _FakeOpenAIEmbeddingClient:
    def __init__(self) -> None:
        self.embeddings = _FakeEmbeddingsClient()


@pytest.mark.asyncio
@pytest.mark.parametrize("dimension", [None, 1024])
async def test_embedding_request_forwards_selected_model_and_optional_dimension(dimension):
    adapter = OpenAIAdapter(
        api_key="test-key", model="embedding-3", provider="glm", embedding_dimension=dimension
    )
    fake_client = _FakeOpenAIEmbeddingClient()
    await adapter._client.close()
    adapter._client = fake_client
    assert await adapter.get_embedding("hello world") == [0.1, 0.2, 0.3]
    expected = {"model": "embedding-3", "input": "hello world"}
    if dimension is not None:
        expected["dimensions"] = dimension
    assert fake_client.embeddings.kwargs == expected
