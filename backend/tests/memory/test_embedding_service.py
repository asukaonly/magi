from __future__ import annotations

import asyncio

import pytest

from magi.llm.concurrency_limiter import LLMConcurrencyLimiter


class _RecordingLimiter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int | None]] = []
        self._delegate = LLMConcurrencyLimiter(default_limit=1)

    def build_key(self, **kwargs):  # type: ignore[no-untyped-def]
        return self._delegate.build_key(**kwargs)

    async def run_with_limit(self, key: str, operation, *, limit: int | None = None):
        self.calls.append((key, limit))
        return await operation()


class _BlockingEmbeddingAdapter:
    def __init__(self) -> None:
        self.provider_name = "openai"
        self.model_name = "text-embedding-3-small"
        self.base_url = "https://api.openai.com/v1"
        self.supports_embeddings = True
        self.embedding_dimension = 3
        self.active_calls = 0
        self.max_active_calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def get_embedding(self, text: str):
        _ = text
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        self.started.set()
        await self.release.wait()
        self.active_calls -= 1
        return [1.0, 0.0, 0.0]


class _EmbeddingScenarioPool:
    def __init__(self, adapter: object) -> None:
        self._adapter = adapter

    def get(self, scenario):  # type: ignore[no-untyped-def]
        from magi.config.models import LLMScenario

        assert scenario == LLMScenario.EMBEDDING
        return self._adapter


@pytest.mark.asyncio
async def test_embedding_requests_share_global_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from magi.llm.concurrency_limiter import LLMConcurrencyLimiter
    from magi.config.llm_registry import LLMEmbeddingModelMetaModel, LLMProviderMetaModel, LLMProviderRegistryModel
    from magi.memory.embedding.embedding_service import MemoryEmbeddingService

    adapter = _BlockingEmbeddingAdapter()
    pool = _EmbeddingScenarioPool(adapter)
    service = MemoryEmbeddingService(pool)

    limiter = LLMConcurrencyLimiter(default_limit=1)
    monkeypatch.setattr("magi.memory.embedding.embedding_service.get_llm_concurrency_limiter", lambda: limiter)
    monkeypatch.setattr(
        "magi.memory.embedding.embedding_service.get_config",
        lambda: SimpleNamespace(
            llm=SimpleNamespace(
                selections={},
                model_runtime_overrides={},
            )
        ),
    )
    monkeypatch.setattr(
        "magi.memory.embedding.embedding_service._load_provider_registry",
        lambda: LLMProviderRegistryModel(
            providers=[
                LLMProviderMetaModel(
                    id="openai",
                    embedding_models=[
                        LLMEmbeddingModelMetaModel(
                            id="text-embedding-3-small",
                            limits={"max_concurrency": 1},
                        )
                    ],
                )
            ]
        ),
    )

    first_task = asyncio.create_task(service.embed_text("alpha"))
    await asyncio.wait_for(adapter.started.wait(), timeout=1.0)

    second_task = asyncio.create_task(service.embed_text("beta"))
    await asyncio.sleep(0)

    assert adapter.max_active_calls == 1

    adapter.release.set()
    first_result = await first_task
    second_result = await second_task

    assert first_result is not None
    assert second_result is not None


@pytest.mark.asyncio
async def test_embedding_limit_uses_embedding_family_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from magi.config.llm_registry import LLMEmbeddingModelMetaModel, LLMProviderMetaModel, LLMProviderRegistryModel
    from magi.memory.embedding.embedding_service import MemoryEmbeddingService

    adapter = _BlockingEmbeddingAdapter()
    pool = _EmbeddingScenarioPool(adapter)
    service = MemoryEmbeddingService(pool)

    limiter = _RecordingLimiter()
    monkeypatch.setattr("magi.memory.embedding.embedding_service.get_llm_concurrency_limiter", lambda: limiter)
    monkeypatch.setattr(
        "magi.memory.embedding.embedding_service.get_config",
        lambda: SimpleNamespace(
            llm=SimpleNamespace(
                selections={
                    "embedding": SimpleNamespace(provider_id="openai", model="text-embedding-3-small"),
                },
                model_runtime_overrides={},
            )
        ),
    )
    monkeypatch.setattr(
        "magi.memory.embedding.embedding_service._load_provider_registry",
        lambda: LLMProviderRegistryModel(
            providers=[
                LLMProviderMetaModel(
                    id="openai",
                    embedding_models=[
                        LLMEmbeddingModelMetaModel(
                            id="text-embedding-3-small",
                            limits={"max_concurrency": 7},
                        )
                    ],
                )
            ]
        ),
    )

    adapter.release.set()
    result = await service.embed_text("alpha")

    assert result is not None
    assert limiter.calls
    key, limit = limiter.calls[0]
    assert key.endswith("::embedding")
    assert limit == 7
