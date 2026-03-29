"""L6 Memory Layer lifecycle module."""

from __future__ import annotations

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..core.logger import get_logger
from ..llm.usage_events import LLMUsageEventPublisher
from ..llm import get_llm_usage_store
from ..config import get_config
from ..config.models import LLMScenario
from ..llm.provider_bridge import LLMProviderBridge
from . import UnifiedMemoryStore
from .embedding_service import MemoryEmbeddingService
from .hybrid_retrieval import HybridRetrievalService
from .integration import MemoryIntegrationConfig, MemoryIntegrationModule

logger = get_logger(__name__)


class MemoryStoreModule(LifecycleModule):
    """Initialize persistence, memory stores, usage metrics, and memory integration (L6)."""

    def __init__(self, context: RuntimeBootstrapContext, *, start_memory_integration: bool = True):
        dependencies = [
            "runtime_llm",
            "runtime_configuration",
            "runtime_core_dependencies",
            "runtime_plugin_system",
        ]
        if start_memory_integration:
            dependencies.append("runtime_message_bus")
        super().__init__(
            name="runtime_memory",
            dependencies=tuple(dependencies),
        )
        self._context = context
        self.start_memory_integration = start_memory_integration

    async def init(self) -> None:
        config = require_initialized(self._context.core.config, "runtime config")
        runtime_paths = require_initialized(self._context.core.runtime_paths, "runtime paths")
        plugin_manager = require_initialized(self._context.plugins.plugin_manager, "plugin manager")

        await self._context.core.db_initializer.insert_default_data(persona_name=self._context.core.current_personality)

        scenario_llm_pool = require_initialized(self._context.llm.scenario_llm_pool, "scenario llm pool")
        message_bus = self._context.message_bus.message_bus
        if self.start_memory_integration:
            runtime_message_bus = require_initialized(message_bus, "message bus")
            publisher = LLMUsageEventPublisher(runtime_message_bus)
            self._context.llm.llm_usage_event_publisher = publisher
            scenario_llm_pool.add_adapter_configurator(
                lambda adapter: setattr(adapter, "_llm_usage_event_publisher", publisher)
            )
            llm_adapter = self._context.llm.llm_adapter
            if llm_adapter is not None:
                setattr(llm_adapter, "_llm_usage_event_publisher", publisher)
            self._context.llm.llm_usage_store = get_llm_usage_store()
            await self._context.llm.llm_usage_store.start(runtime_message_bus)
            logger.info("LLM usage store started")
        else:
            logger.info("LLM usage store subscription skipped for API role")

        memory_config = config.agent.memory
        embedding_service = MemoryEmbeddingService(scenario_llm_pool)

        self._context.memory.unified_memory = UnifiedMemoryStore(
            l1_db_path=str(runtime_paths.l1_memory_db_path),
            memory_db_path=str(runtime_paths.memory_db_path),
            persist_dir=str(runtime_paths.memory_dir),
            embedding_service=embedding_service,
            scenario_llm_pool=scenario_llm_pool,
            memory_config_getter=lambda: get_config().agent.memory,
            async_embeddings=memory_config.async_embeddings,
            enable_l1_vectors=memory_config.l1.vectors_enabled,
            enable_l2_vectors=memory_config.l2.vectors_enabled,
            enable_l3_vectors=memory_config.l3.vectors_enabled,
            enable_l4_vectors=memory_config.l4.vectors_enabled,
            enable_l0=memory_config.l0.enabled,
            enable_l1=memory_config.l1.enabled,
            enable_l2=memory_config.l2.enabled,
            enable_l3=memory_config.l3.enabled,
            enable_l4=memory_config.l4.enabled,
            enable_l3_llm_summary=memory_config.l3.llm_summary_enabled,
            temporal_l3_llm_timeout_seconds=memory_config.l3.temporal_llm_timeout_seconds,
            temporal_l3_llm_min_event_count=memory_config.l3.temporal_llm_min_event_count,
            temporal_summary_features_builder=plugin_manager.build_temporal_summary_features,
            l0_checkpoint_interval_seconds=memory_config.l0.checkpoint_interval_seconds,
            l2_batch_flush_interval_seconds=memory_config.l2.batch_flush_interval_seconds,
            enable_l2_conflict_arbitration=memory_config.l2.conflict_arbitration_enabled,
            l2_conflict_arbitration_min_confidence=memory_config.l2.conflict_arbitration_min_confidence,
        )
        await self._context.memory.unified_memory.initialize()
        logger.info("UnifiedMemoryStore initialized (L0-L4)")

        self._context.memory.hybrid_retrieval_service = HybridRetrievalService(
            self._context.memory.unified_memory,
            llm_provider_bridge=LLMProviderBridge(
                scenario_llm_pool.get(LLMScenario.CONTEXT_DECIDER)
            ),
        )
        logger.info("HybridRetrievalService initialized")

        if self.start_memory_integration:
            runtime_message_bus = require_initialized(message_bus, "message bus")
            memory_integration_config = MemoryIntegrationConfig(
                enable_l0=memory_config.l0.enabled,
                enable_l1=memory_config.l1.enabled,
                enable_l2=memory_config.l2.enabled,
                enable_l3=memory_config.l3.enabled,
                enable_l4=memory_config.l4.enabled,
                summary_interval_minutes=memory_config.l3.summary_interval_minutes,
            )
            self._context.memory.memory_integration = MemoryIntegrationModule(
                unified_memory=self._context.memory.unified_memory,
                message_bus=runtime_message_bus,
                config=memory_integration_config,
            )
            await self._context.memory.memory_integration.start()
            logger.info("MemoryIntegrationModule started")
        else:
            logger.info("MemoryIntegrationModule skipped for API role")

    async def shutdown(self) -> None:
        if self._context.memory.memory_integration is not None:
            await self._context.memory.memory_integration.stop()
            self._context.memory.memory_integration = None

        if self._context.memory.unified_memory is not None:
            await self._context.memory.unified_memory.shutdown()

        if self._context.llm.llm_usage_store is not None:
            await self._context.llm.llm_usage_store.stop()
            self._context.llm.llm_usage_store = None
        if self._context.llm.llm_usage_event_publisher is not None:
            self._context.llm.llm_usage_event_publisher.configure(None)
            self._context.llm.llm_usage_event_publisher = None

        self._context.memory.unified_memory = None
        self._context.memory.hybrid_retrieval_service = None
