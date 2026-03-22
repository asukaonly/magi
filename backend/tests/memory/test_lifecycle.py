from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


class _FakeDBInitializer:
    async def insert_default_data(self, *, persona_name: str) -> None:
        self.persona_name = persona_name


class _FakeScenarioPool:
    def __init__(self) -> None:
        self.configurator = None

    def add_adapter_configurator(self, configurator):  # type: ignore[no-untyped-def]
        self.configurator = configurator

    def get(self, scenario):  # type: ignore[no-untyped-def]
        return SimpleNamespace(provider_name="openai", model_name="gpt-test")


class _FakeUsageStore:
    async def start(self, message_bus) -> None:  # type: ignore[no-untyped-def]
        self.message_bus = message_bus

    async def stop(self) -> None:
        return None


class _FakeUnifiedMemoryStore:
    def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.kwargs = kwargs

    async def initialize(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None


class _FakeHybridRetrievalService:
    def __init__(self, unified_memory, llm_provider_bridge) -> None:  # type: ignore[no-untyped-def]
        self.unified_memory = unified_memory
        self.llm_provider_bridge = llm_provider_bridge


@pytest.mark.asyncio
async def test_memory_store_module_passes_l2_batch_flush_interval(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from magi.bootstrap.context import RuntimeBootstrapContext
    from magi.config.models import EmbeddingBackend
    from magi.memory.lifecycle import MemoryStoreModule

    usage_store = _FakeUsageStore()
    fake_pool = _FakeScenarioPool()
    captured: dict[str, object] = {}

    def fake_unified_memory_store(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return _FakeUnifiedMemoryStore(**kwargs)

    monkeypatch.setattr("magi.memory.lifecycle.get_llm_usage_store", lambda: usage_store)
    monkeypatch.setattr("magi.memory.lifecycle.UnifiedMemoryStore", fake_unified_memory_store)
    monkeypatch.setattr("magi.memory.lifecycle.HybridRetrievalService", _FakeHybridRetrievalService)

    context = RuntimeBootstrapContext()
    context.core.config = SimpleNamespace(
        agent=SimpleNamespace(
            memory=SimpleNamespace(
                embedding=SimpleNamespace(backend=EmbeddingBackend.OPENAI),
                async_embeddings=True,
                enable_l0=True,
                enable_l1=True,
                enable_l2=True,
                enable_l3=True,
                enable_l4=True,
                enable_l3_llm_summary=True,
                l3_temporal_llm_timeout_seconds=30,
                l3_temporal_llm_min_event_count=5,
                l0_checkpoint_interval_seconds=60,
                l2_batch_flush_interval_seconds=90,
                summary_interval_minutes=15,
            )
        )
    )
    context.core.runtime_paths = SimpleNamespace(
        l1_memory_db_path=tmp_path / "l1.db",
        memory_db_path=tmp_path / "memory.db",
        memories_dir=tmp_path / "memories",
    )
    context.core.db_initializer = _FakeDBInitializer()
    context.message_bus.message_bus = SimpleNamespace()
    context.llm.scenario_llm_pool = fake_pool

    module = MemoryStoreModule(context, start_memory_integration=False)

    await module.init()

    assert captured["l2_batch_flush_interval_seconds"] == 90
