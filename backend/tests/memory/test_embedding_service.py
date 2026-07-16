from __future__ import annotations

import asyncio

import pytest

from magi.llm.concurrency_limiter import LLMConcurrencyLimiter


def test_local_embedding_manager_is_replaced_when_variant_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from magi.memory.embedding import local_embedding_manager
    from magi.memory.embedding.embedding_service import MemoryEmbeddingService

    local_config = SimpleNamespace(
        model_source="managed",
        managed_model_id="local-model",
        model_dir_path=None,
        variant="fp16",
        idle_timeout_seconds=1800,
    )
    config = SimpleNamespace(
        agent=SimpleNamespace(
            memory=SimpleNamespace(
                embedding=SimpleNamespace(local=local_config),
            )
        )
    )
    created_variants: list[str] = []

    class FakeLocalManager:
        def __init__(self, manager_config):  # type: ignore[no-untyped-def]
            created_variants.append(str(manager_config.variant))

        async def shutdown(self) -> None:
            return None

    monkeypatch.setattr(
        "magi.memory.embedding.embedding_service.get_config",
        lambda: config,
    )
    monkeypatch.setattr(local_embedding_manager, "LocalEmbeddingManager", FakeLocalManager)

    service = MemoryEmbeddingService(None)
    first = service._get_local_manager()
    local_config.variant = "int8"
    second = service._get_local_manager()

    assert first is not second
    assert created_variants == ["fp16", "int8"]


def test_profile_from_published_result_keeps_its_index_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from magi.memory.embedding.embedding_service import EmbeddingResult, MemoryEmbeddingService

    monkeypatch.setattr(
        "magi.memory.embedding.embedding_service.get_config",
        lambda: SimpleNamespace(
            agent=SimpleNamespace(
                memory=SimpleNamespace(
                    embedding=SimpleNamespace(mode="remote"),
                )
            )
        ),
    )
    service = MemoryEmbeddingService(None)

    profile = service.profile_from_result(
        EmbeddingResult(
            model_name="old-model",
            dimension=2,
            vector=[1.0, 0.0],
            index_identity="published-old-profile",
        ),
        text_builder_version="l3_summary_v1",
    )

    assert profile.profile_id == "published-old-profile"


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
        self.provider_instance_id = "openai"
        self.provider_plan = None
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

    async def get_embedding_with_usage(self, text: str, model=None):
        # Mirrors the LLMAdapter contract: delegate and report 0 tokens.
        return (await self.get_embedding(text), 0)


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
    from magi.memory.embedding.embedding_service import MemoryEmbeddingService

    adapter = _BlockingEmbeddingAdapter()
    pool = _EmbeddingScenarioPool(adapter)
    service = MemoryEmbeddingService(pool)

    limiter = LLMConcurrencyLimiter(default_limit=1)
    monkeypatch.setattr(
        "magi.memory.embedding.embedding_service.get_llm_concurrency_limiter", lambda: limiter
    )
    monkeypatch.setattr(
        "magi.memory.embedding.embedding_service.get_config",
        lambda: SimpleNamespace(
            llm=SimpleNamespace(
                selections={},
                model_runtime_overrides={
                    "openai::openai::api::api.openai.com::text-embedding-3-small::embedding": SimpleNamespace(
                        max_concurrency=1
                    )
                },
            ),
            agent=SimpleNamespace(
                memory=SimpleNamespace(
                    embedding=SimpleNamespace(mode="remote"),
                ),
            ),
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

    from magi.memory.embedding.embedding_service import MemoryEmbeddingService

    adapter = _BlockingEmbeddingAdapter()
    pool = _EmbeddingScenarioPool(adapter)
    service = MemoryEmbeddingService(pool)

    limiter = _RecordingLimiter()
    monkeypatch.setattr(
        "magi.memory.embedding.embedding_service.get_llm_concurrency_limiter", lambda: limiter
    )
    monkeypatch.setattr(
        "magi.memory.embedding.embedding_service.get_config",
        lambda: SimpleNamespace(
            llm=SimpleNamespace(
                selections={
                    "embedding": SimpleNamespace(
                        provider_id="openai", model="text-embedding-3-small"
                    ),
                },
                model_runtime_overrides={
                    "openai::openai::api::api.openai.com::text-embedding-3-small::embedding": SimpleNamespace(
                        max_concurrency=7
                    )
                },
            ),
            agent=SimpleNamespace(
                memory=SimpleNamespace(
                    embedding=SimpleNamespace(mode="remote"),
                ),
            ),
        ),
    )
    adapter.release.set()
    result = await service.embed_text("alpha")

    assert result is not None
    assert limiter.calls
    key, limit = limiter.calls[0]
    assert key.endswith("::embedding")
    assert limit == 7
