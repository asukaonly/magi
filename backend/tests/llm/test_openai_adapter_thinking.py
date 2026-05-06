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
async def test_embedding_uses_selected_model_instead_of_hardcoded_default() -> None:
    adapter = OpenAIAdapter(api_key="test-key", model="embedding-3", provider="glm")
    fake_client = _FakeOpenAIEmbeddingClient()
    adapter._client = fake_client

    vector = await adapter.get_embedding("hello world")

    assert vector == [0.1, 0.2, 0.3]
    assert fake_client.embeddings.kwargs["model"] == "embedding-3"


@pytest.mark.asyncio
async def test_embedding_forwards_configured_dimension() -> None:
    adapter = OpenAIAdapter(
        api_key="test-key",
        model="embedding-3",
        provider="glm",
        embedding_dimension=1024,
    )
    fake_client = _FakeOpenAIEmbeddingClient()
    adapter._client = fake_client

    vector = await adapter.get_embedding("hello world")

    assert vector == [0.1, 0.2, 0.3]
    assert fake_client.embeddings.kwargs["dimensions"] == 1024
