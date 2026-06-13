"""OpenAIAdapter embedding usage capture (prompt_tokens from response.usage)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from magi.llm.base import LLMAdapter
from magi.llm.openai import OpenAIAdapter


class _FakeEmbeddingsClient:
    """Fake ``client.embeddings`` exposing an async ``create``."""

    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def create(self, **payload):
        self.calls.append(dict(payload))
        if self.error is not None:
            raise self.error
        return self.response


def _embedding_response(vectors, *, prompt_tokens):
    return SimpleNamespace(
        data=[SimpleNamespace(embedding=v) for v in vectors],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, total_tokens=prompt_tokens),
    )


@pytest.mark.asyncio
async def test_get_embedding_with_usage_captures_prompt_tokens() -> None:
    adapter = OpenAIAdapter(api_key="k", model="text-embedding-v3", provider="dashscope")
    fake = _FakeEmbeddingsClient(response=_embedding_response([[0.1, 0.2, 0.3]], prompt_tokens=7))
    adapter._client = SimpleNamespace(embeddings=fake)

    vector, prompt_tokens = await adapter.get_embedding_with_usage("hello world")

    assert vector == [0.1, 0.2, 0.3]
    assert prompt_tokens == 7


@pytest.mark.asyncio
async def test_get_embedding_with_usage_empty_text_returns_zero() -> None:
    adapter = OpenAIAdapter(api_key="k", model="text-embedding-v3", provider="dashscope")
    adapter._client = SimpleNamespace(embeddings=_FakeEmbeddingsClient())

    assert await adapter.get_embedding_with_usage("   ") == (None, 0)


@pytest.mark.asyncio
async def test_get_embedding_with_usage_error_returns_none_zero() -> None:
    adapter = OpenAIAdapter(api_key="k", model="text-embedding-v3", provider="dashscope")
    adapter._client = SimpleNamespace(embeddings=_FakeEmbeddingsClient(error=RuntimeError("boom")))

    assert await adapter.get_embedding_with_usage("hello") == (None, 0)


@pytest.mark.asyncio
async def test_get_embeddings_with_usage_captures_prompt_tokens() -> None:
    adapter = OpenAIAdapter(api_key="k", model="text-embedding-v3", provider="dashscope")
    fake = _FakeEmbeddingsClient(
        response=_embedding_response([[0.1, 0.2], [0.3, 0.4]], prompt_tokens=42)
    )
    adapter._client = SimpleNamespace(embeddings=fake)

    vectors, prompt_tokens = await adapter.get_embeddings_with_usage(["a", "b"])

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert prompt_tokens == 42


@pytest.mark.asyncio
async def test_get_embeddings_with_usage_skips_empty_texts() -> None:
    adapter = OpenAIAdapter(api_key="k", model="text-embedding-v3", provider="dashscope")
    # Only the two non-empty texts are sent; their order is preserved by index.
    fake = _FakeEmbeddingsClient(
        response=_embedding_response([[0.1], [0.2]], prompt_tokens=10)
    )
    adapter._client = SimpleNamespace(embeddings=fake)

    vectors, prompt_tokens = await adapter.get_embeddings_with_usage(["a", "", "b"])

    assert vectors == [[0.1], None, [0.2]]
    assert prompt_tokens == 10
    assert fake.calls[0]["input"] == ["a", "b"]


@pytest.mark.asyncio
async def test_get_embeddings_with_usage_no_valid_texts() -> None:
    adapter = OpenAIAdapter(api_key="k", model="text-embedding-v3", provider="dashscope")
    adapter._client = SimpleNamespace(embeddings=_FakeEmbeddingsClient())

    assert await adapter.get_embeddings_with_usage(["", "  "]) == ([None, None], 0)


@pytest.mark.asyncio
async def test_get_embeddings_with_usage_fallback_sums_per_text_tokens() -> None:
    """Batch failure falls back to per-text calls and sums the token counts."""

    class _FlakyEmbeddings:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def create(self, **payload):
            self.calls.append(dict(payload))
            # The batch call (input is a list) fails; per-text calls (str) succeed.
            if isinstance(payload["input"], list):
                raise RuntimeError("batch not supported")
            text = payload["input"]
            return _embedding_response([[0.5]], prompt_tokens=3 if text == "a" else 4)

    adapter = OpenAIAdapter(api_key="k", model="text-embedding-v3", provider="dashscope")
    adapter._client = SimpleNamespace(embeddings=_FlakyEmbeddings())

    vectors, prompt_tokens = await adapter.get_embeddings_with_usage(["a", "b"])

    assert vectors == [[0.5], [0.5]]
    assert prompt_tokens == 7  # 3 + 4 summed across per-text fallback calls


@pytest.mark.asyncio
async def test_base_adapter_default_reports_zero_tokens() -> None:
    """Non-overriding adapters (e.g. local/free) keep tokens at 0."""

    class _LocalAdapter(LLMAdapter):
        async def generate(self, *a, **k):  # pragma: no cover - unused
            return ""

        async def generate_stream(self, *a, **k):  # pragma: no cover - unused
            yield ""

        async def chat(self, *a, **k):  # pragma: no cover - unused
            return ""

        async def chat_stream(self, *a, **k):  # pragma: no cover - unused
            yield ""

        @property
        def model_name(self) -> str:
            return "local"

        async def get_embedding(self, text, model=None):
            return [1.0, 2.0]

    adapter = _LocalAdapter()
    assert await adapter.get_embedding_with_usage("x") == ([1.0, 2.0], 0)
    assert await adapter.get_embeddings_with_usage(["x", "y"]) == ([[1.0, 2.0], [1.0, 2.0]], 0)
