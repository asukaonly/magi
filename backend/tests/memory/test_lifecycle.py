from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


class _FakeScenarioPool:
    def __init__(self) -> None:
        self.configurator = None

    def add_adapter_configurator(self, configurator):  # type: ignore[no-untyped-def]
        self.configurator = configurator

    def get(self, scenario):  # type: ignore[no-untyped-def]
        return SimpleNamespace(provider_name="openai", model_name="gpt-test")


class _FakeUsageStore:
    def __init__(self) -> None:
        self.started = False
        self.message_bus = None

    async def start(self, message_bus=None) -> None:  # type: ignore[no-untyped-def]
        self.started = True
        self.message_bus = message_bus

    async def stop(self) -> None:
        return None


class _FakeUnifiedMemoryStore:
    def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.kwargs = kwargs

    async def initialize(
        self,
        *,
        start_workers: bool = True,
        start_projection_workers: bool = True,
        recover_pending: bool = True,
        restore_runtime_state: bool = True,
    ) -> None:
        self.initialize_options = {
            "start_workers": start_workers,
            "start_projection_workers": start_projection_workers,
            "recover_pending": recover_pending,
            "restore_runtime_state": restore_runtime_state,
        }
        return None

    async def shutdown(self) -> None:
        return None

    def memory_operation_epoch(self) -> int:
        return 0


class _FakeHybridRetrievalService:
    def __init__(self, unified_memory, llm_provider_bridge, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.unified_memory = unified_memory
        self.llm_provider_bridge = llm_provider_bridge
        self.kwargs = kwargs


@pytest.mark.asyncio
async def test_memory_store_module_passes_l2_batch_flush_interval(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from magi.bootstrap.context import RuntimeBootstrapContext
    from magi.config.models import EmbeddingBackend
    from magi.memory.lifecycle import MemoryStoreModule

    usage_store = _FakeUsageStore()
    fake_pool = _FakeScenarioPool()
    captured: dict[str, object] = {}
    registered_stores: list[object] = []

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
                retention_days=90,
                history_behavior="delete",
                archive_path=str(tmp_path / "custom-archive"),
                embedding=SimpleNamespace(backend=EmbeddingBackend.OPENAI),
                async_embeddings=True,
                l0=SimpleNamespace(
                    enabled=True,
                    checkpoint_interval_seconds=60,
                ),
                l1=SimpleNamespace(
                    enabled=True,
                    vectors_enabled=True,
                ),
                l2=SimpleNamespace(
                    enabled=True,
                    vectors_enabled=True,
                    batch_flush_interval_seconds=90,
                    auto_extract_relations=True,
                ),
                l3=SimpleNamespace(
                    enabled=True,
                    vectors_enabled=True,
                    llm_summary_enabled=True,
                    temporal_llm_timeout_seconds=30,
                    temporal_llm_min_event_count=5,
                ),
                l4=SimpleNamespace(
                    enabled=True,
                    vectors_enabled=True,
                ),
            )
        )
    )
    context.core.runtime_paths = SimpleNamespace(
        l1_memory_db_path=tmp_path / "l1.db",
        memory_db_path=tmp_path / "memory.db",
        memory_dir=tmp_path / "memory",
    )
    context.llm.scenario_llm_pool = fake_pool
    context.message_bus.message_bus = _FakeMessageBus()
    context.plugins.plugin_projection_service = SimpleNamespace(
        build_temporal_summary_features=lambda *args, **kwargs: {},
        iter_extraction_profiles=lambda: [],
    )

    module = MemoryStoreModule(
        context,
        portrait_projection_refresh_registrar=registered_stores.append,
    )

    await module.init()

    assert captured["l2_batch_flush_interval_seconds"] == 90
    assert captured["archive_dir_path"] == str(tmp_path / "custom-archive")
    assert registered_stores == [context.memory.unified_memory]
    assert usage_store.started is True
    assert usage_store.message_bus is None
    assert len(context.message_bus.message_bus.subscriptions) == 6


class _FakeMessageBus:
    def __init__(self) -> None:
        self.subscriptions: list[tuple[str, object]] = []
        self.unsubscribed: list[str] = []
        self.bound_epoch_getters: list[object | None] = []
        self._next = 0

    def bind_memory_operation_epoch(self, getter) -> None:  # type: ignore[no-untyped-def]
        self.bound_epoch_getters.append(getter)

    async def subscribe(self, event_type, handler, *, propagation_mode=None):  # type: ignore[no-untyped-def]
        self._next += 1
        sid = f"sub-{self._next}"
        self.subscriptions.append((event_type, handler))
        return sid

    async def unsubscribe(self, sid):  # type: ignore[no-untyped-def]
        self.unsubscribed.append(sid)


@pytest.mark.asyncio
@pytest.mark.parametrize("recovery_pending", [False, True])
async def test_memory_store_binds_epoch_before_subscribing_and_unbinds_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    recovery_pending: bool,
) -> None:
    from magi.bootstrap.context import RuntimeBootstrapContext
    from magi.config.models import EmbeddingBackend
    from magi.memory.lifecycle import MemoryStoreModule

    usage_store = _FakeUsageStore()
    bus = _FakeMessageBus()
    integration_state: dict[str, object] = {}

    class _FakeIntegration:
        def __init__(self, *, unified_memory, message_bus) -> None:  # type: ignore[no-untyped-def]
            assert message_bus.bound_epoch_getters
            assert message_bus.bound_epoch_getters[-1] is not None
            integration_state["instance"] = self
            integration_state["memory"] = unified_memory
            self.started = False
            self.stopped = False

        async def start(self) -> None:
            self.started = True

        async def stop(self) -> None:
            self.stopped = True

    monkeypatch.setattr("magi.memory.lifecycle.get_llm_usage_store", lambda: usage_store)
    monkeypatch.setattr(
        "magi.memory.lifecycle.UnifiedMemoryStore",
        _FakeUnifiedMemoryStore,
    )
    monkeypatch.setattr(
        "magi.memory.lifecycle.HybridRetrievalService",
        _FakeHybridRetrievalService,
    )
    monkeypatch.setattr(
        "magi.memory.lifecycle.MemoryIntegrationModule",
        _FakeIntegration,
    )

    context = RuntimeBootstrapContext()
    context.core.config = SimpleNamespace(
        agent=SimpleNamespace(
            memory=SimpleNamespace(
                archive_path=str(tmp_path / "archive"),
                embedding=SimpleNamespace(backend=EmbeddingBackend.OPENAI),
                async_embeddings=False,
                l0=SimpleNamespace(enabled=True, checkpoint_interval_seconds=60),
                l1=SimpleNamespace(enabled=True, vectors_enabled=False),
                l2=SimpleNamespace(
                    enabled=True,
                    vectors_enabled=False,
                    batch_flush_interval_seconds=0,
                ),
                l3=SimpleNamespace(
                    enabled=True,
                    vectors_enabled=False,
                    llm_summary_enabled=False,
                    temporal_llm_timeout_seconds=30,
                    temporal_llm_min_event_count=5,
                ),
                l4=SimpleNamespace(enabled=True, vectors_enabled=False),
            )
        )
    )
    context.core.runtime_paths = SimpleNamespace(
        l1_memory_db_path=tmp_path / "l1.db",
        memory_db_path=tmp_path / "memory.db",
        memory_dir=tmp_path / "memory",
    )
    context.llm.scenario_llm_pool = _FakeScenarioPool()
    context.plugins.plugin_projection_service = SimpleNamespace(
        build_temporal_summary_features=lambda *args, **kwargs: {},
        iter_extraction_profiles=lambda: [],
    )
    context.message_bus.message_bus = bus

    context.runtime_commands.full_clear_recovery_pending = recovery_pending
    module = MemoryStoreModule(context)
    await module.init()

    integration = integration_state["instance"]
    assert integration.started is (not recovery_pending)
    assert context.memory.unified_memory.initialize_options == {
        "start_workers": not recovery_pending,
        "start_projection_workers": False,
        "recover_pending": not recovery_pending,
        "restore_runtime_state": not recovery_pending,
    }
    assert callable(bus.bound_epoch_getters[0])

    await module.shutdown()

    assert integration.stopped is True
    assert bus.bound_epoch_getters[-1] is None


@pytest.mark.asyncio
async def test_memory_ingestion_subscriber_module_init_and_shutdown() -> None:
    from magi.events.events import EventTypes
    from magi.bootstrap.context import RuntimeBootstrapContext
    from magi.memory.lifecycle import MemoryIngestionSubscriberModule

    context = RuntimeBootstrapContext()
    context.memory.unified_memory = SimpleNamespace(
        ingest_event=lambda evt: None,
    )
    bus = _FakeMessageBus()
    context.message_bus.message_bus = bus

    module = MemoryIngestionSubscriberModule(context)

    await module.init()
    assert context.memory.ingestion_subscriber is not None
    assert [kind for kind, _ in bus.subscriptions] == [
        EventTypes.TOOL_INVOCATION_COMPLETED,
        EventTypes.SPAN_COMPLETED,
        EventTypes.USER_MESSAGE_RECEIVED,
        EventTypes.ASSISTANT_RESPONSE_PRODUCED,
        EventTypes.TASK_STARTED,
        EventTypes.TASK_COMPLETED,
        EventTypes.TASK_FAILED,
        EventTypes.SKILL_INVOCATION_COMPLETED,
    ]

    await module.shutdown()
    assert context.memory.ingestion_subscriber is None
    assert bus.unsubscribed == [f"sub-{index}" for index in range(1, 9)]


@pytest.mark.asyncio
@pytest.mark.parametrize("with_embeddings", [False, True])
async def test_unified_shutdown_closes_open_entity_and_edge_indexes(tmp_path, with_embeddings):
    from magi.memory.unified_store import UnifiedMemoryStore

    store = UnifiedMemoryStore(
        memory_db_path=str(tmp_path / "memory.db"),
        persist_dir=str(tmp_path / "memory"),
        enable_l0=False,
        enable_l1=False,
        enable_l3=False,
        enable_l4=False,
        embedding_service=SimpleNamespace() if with_embeddings else None,
    )
    await store.initialize(start_workers=False)
    catalog = store.l2_entity_catalog
    indexes = [catalog._vector_index]
    if with_embeddings:
        indexes.append(catalog.edge_vector_index)
    try:
        connections = []
        for index in indexes:
            await index.initialize()
            connection = index._db
            async with connection.execute("SELECT 1") as cursor:
                assert await cursor.fetchone() is not None
            connections.append(connection)

        await store.shutdown()
        for connection in connections:
            with pytest.raises(ValueError, match="no active connection"):
                await connection.execute("SELECT 1")
        await store.shutdown()
    finally:
        await catalog.close()
