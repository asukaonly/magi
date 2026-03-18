"""Tests for GLM thinking toggle handling in OpenAI adapter."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from magi.llm.openai import OpenAIAdapter


class _FakeCompletionsClient:
    def __init__(self) -> None:
        self.kwargs = {}

    async def create(self, **kwargs):
        self.kwargs = kwargs
        message = SimpleNamespace(content="ok")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _FakeOpenAIClient:
    def __init__(self) -> None:
        self.completions = _FakeCompletionsClient()
        self.chat = SimpleNamespace(completions=self.completions)


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
async def test_glm_chat_disable_thinking_sets_extra_body() -> None:
    adapter = OpenAIAdapter(api_key="test-key", model="glm-4.5", provider="glm")
    fake_client = _FakeOpenAIClient()
    adapter._client = fake_client

    await adapter.chat(
        messages=[{"role": "user", "content": "hello"}],
        disable_thinking=True,
    )

    assert fake_client.completions.kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


@pytest.mark.asyncio
async def test_openai_chat_disable_thinking_does_not_inject_glm_payload() -> None:
    adapter = OpenAIAdapter(api_key="test-key", model="gpt-4", provider="openai")
    fake_client = _FakeOpenAIClient()
    adapter._client = fake_client

    await adapter.chat(
        messages=[{"role": "user", "content": "hello"}],
        disable_thinking=True,
    )

    assert "extra_body" not in fake_client.completions.kwargs
    assert "disable_thinking" not in fake_client.completions.kwargs


@pytest.mark.asyncio
async def test_openai_generate_disable_thinking_does_not_forward_internal_flag() -> None:
    adapter = OpenAIAdapter(api_key="test-key", model="gpt-4", provider="openai")
    fake_client = _FakeOpenAIClient()
    adapter._client = fake_client

    await adapter.generate(
        "hello",
        disable_thinking=True,
    )

    assert "extra_body" not in fake_client.completions.kwargs
    assert "disable_thinking" not in fake_client.completions.kwargs


@pytest.mark.asyncio
async def test_glm_chat_disable_thinking_merges_existing_extra_body() -> None:
    adapter = OpenAIAdapter(api_key="test-key", model="glm-4.5", provider="glm")
    fake_client = _FakeOpenAIClient()
    adapter._client = fake_client

    await adapter.chat(
        messages=[{"role": "user", "content": "hello"}],
        disable_thinking=True,
        extra_body={"foo": "bar"},
    )

    assert fake_client.completions.kwargs["extra_body"] == {
        "foo": "bar",
        "thinking": {"type": "disabled"},
    }


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
