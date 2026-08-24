"""L6 Memory Layer lifecycle module."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..core.logger import get_logger
from ..llm import get_llm_usage_store
from ..config import get_config
from ..config.models import LLMScenario
from ..llm.provider_bridge import LLMProviderBridge
from . import MemoryStoreTuning, UnifiedMemoryStore
from .embedding.embedding_service import MemoryEmbeddingService
from .hybrid_retrieval import HybridRetrievalService
from .hybrid_retrieval.service import build_retrieval_config_from_app_config
from .integration import MemoryIntegrationConfig, MemoryIntegrationModule

logger = get_logger(__name__)


class MemoryStoreModule(LifecycleModule):
    """Initialize persistence, memory stores, usage metrics, and memory integration (L6)."""

    def __init__(
        self,
        context: RuntimeBootstrapContext,
        *,
        start_memory_integration: bool = True,
        enable_embedding: bool = True,
        portrait_projection_refresh_registrar: Callable[[Any], None] | None = None,
    ):
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
        self._enable_embedding = enable_embedding
        self._portrait_projection_refresh_registrar = portrait_projection_refresh_registrar

    async def init(self) -> None:
        config = require_initialized(self._context.core.config, "runtime config")
        runtime_paths = require_initialized(self._context.core.runtime_paths, "runtime paths")
        plugin_projection_service = require_initialized(
            self._context.plugins.plugin_projection_service,
            "plugin projection service",
        )

        recovery_pending = self._context.runtime_commands.full_clear_recovery_pending
        scenario_llm_pool = self._context.llm.scenario_llm_pool
        if not recovery_pending:
            scenario_llm_pool = require_initialized(scenario_llm_pool, "scenario llm pool")
        message_bus = self._context.message_bus.message_bus
        await self._start_llm_usage_store(message_bus)

        memory_config = config.agent.memory
        self._context.memory.unified_memory = self._build_unified_memory_store(
            runtime_paths=runtime_paths,
            scenario_llm_pool=scenario_llm_pool,
            plugin_projection_service=plugin_projection_service,
            memory_config=memory_config,
        )
        if self._portrait_projection_refresh_registrar is not None:
            self._portrait_projection_refresh_registrar(self._context.memory.unified_memory)
        await self._context.memory.unified_memory.initialize(
            start_workers=not recovery_pending,
            recover_pending=not recovery_pending,
            restore_runtime_state=not recovery_pending,
        )
        logger.info("UnifiedMemoryStore initialized (L0-L4)")

        if self.start_memory_integration:
            runtime_message_bus = require_initialized(message_bus, "message bus")
            runtime_message_bus.bind_memory_operation_epoch(
                self._context.memory.unified_memory.memory_operation_epoch
            )
            logger.info("MessageBus memory operation epoch bound")

        if recovery_pending:
            self._context.memory.hybrid_retrieval_service = None
            logger.warning("Hybrid retrieval held for full-clear recovery")
        else:
            self._context.memory.hybrid_retrieval_service = self._build_hybrid_retrieval_service(
                scenario_llm_pool
            )
            logger.info("HybridRetrievalService initialized")

        await self._start_memory_integration(
            message_bus,
            memory_config,
            start=not recovery_pending,
        )

    async def _start_llm_usage_store(self, message_bus: Any) -> None:
        if self.start_memory_integration:
            require_initialized(message_bus, "message bus")
            self._context.llm.llm_usage_store = get_llm_usage_store()
            await self._context.llm.llm_usage_store.start()
            logger.info("LLM usage store started")
            return
        logger.info("LLM usage store subscription skipped for API role")

    def _build_unified_memory_store(
        self,
        *,
        runtime_paths: Any,
        scenario_llm_pool: Any,
        plugin_projection_service: Any,
        memory_config: Any,
    ) -> UnifiedMemoryStore:
        embedding_service = self._build_embedding_service(scenario_llm_pool)
        return UnifiedMemoryStore(
            l1_db_path=str(runtime_paths.l1_memory_db_path),
            memory_db_path=str(runtime_paths.memory_db_path),
            persist_dir=str(runtime_paths.memory_dir),
            embedding_service=embedding_service,
            scenario_llm_pool=scenario_llm_pool,
            memory_config_getter=lambda: get_config().agent.memory,
            archive_dir_path=memory_config.archive_path,
            enable_l0=memory_config.l0.enabled,
            enable_l1=memory_config.l1.enabled,
            enable_l2=memory_config.l2.enabled,
            enable_l3=memory_config.l3.enabled,
            enable_l4=memory_config.l4.enabled,
            l2_batch_flush_interval_seconds=memory_config.l2.batch_flush_interval_seconds,
            temporal_summary_features_builder=plugin_projection_service.build_temporal_summary_features,
            extraction_profile_provider=plugin_projection_service.iter_extraction_profiles,
            tuning=self._build_store_tuning(memory_config),
        )

    def _build_embedding_service(self, scenario_llm_pool: Any) -> MemoryEmbeddingService | None:
        if not self._enable_embedding or self._context.runtime_commands.full_clear_recovery_pending:
            return None
        return MemoryEmbeddingService(scenario_llm_pool)

    def _build_store_tuning(self, memory_config: Any) -> MemoryStoreTuning:
        # When embedding is disabled (e.g. API role), skip vector index initialization entirely.
        vectors_enabled = (
            self._enable_embedding
            and not self._context.runtime_commands.full_clear_recovery_pending
        )
        return MemoryStoreTuning(
            async_embeddings=memory_config.async_embeddings,
            enable_l1_vectors=memory_config.l1.vectors_enabled and vectors_enabled,
            enable_l2_vectors=memory_config.l2.vectors_enabled and vectors_enabled,
            enable_l3_vectors=memory_config.l3.vectors_enabled and vectors_enabled,
            enable_l4_vectors=memory_config.l4.vectors_enabled and vectors_enabled,
            enable_l3_llm_summary=memory_config.l3.llm_summary_enabled,
            l0_checkpoint_interval_seconds=memory_config.l0.checkpoint_interval_seconds,
            temporal_l3_llm_timeout_seconds=memory_config.l3.temporal_llm_timeout_seconds,
            temporal_l3_llm_min_event_count=memory_config.l3.temporal_llm_min_event_count,
        )

    def _build_hybrid_retrieval_service(self, scenario_llm_pool: Any) -> HybridRetrievalService:
        unified_memory = require_initialized(
            self._context.memory.unified_memory,
            "unified memory",
        )
        return HybridRetrievalService(
            unified_memory,
            config_getter=lambda: build_retrieval_config_from_app_config(get_config()),
            llm_provider_bridge=LLMProviderBridge(
                scenario_llm_pool.get(LLMScenario.AUXILIARY)
            ),
        )

    async def _start_memory_integration(
        self,
        message_bus: Any,
        memory_config: Any,
        *,
        start: bool = True,
    ) -> None:
        if not self.start_memory_integration:
            logger.info("MemoryIntegrationModule skipped for API role")
            return
        runtime_message_bus = require_initialized(message_bus, "message bus")
        memory_integration_config = MemoryIntegrationConfig(
            enable_l1=memory_config.l1.enabled,
            enable_l2=memory_config.l2.enabled,
            enable_l3=memory_config.l3.enabled,
            enable_l4=memory_config.l4.enabled,
            summary_interval_minutes=memory_config.l3.summary_interval_minutes,
        )
        unified_memory = require_initialized(
            self._context.memory.unified_memory,
            "unified memory",
        )
        self._context.memory.memory_integration = MemoryIntegrationModule(
            unified_memory=unified_memory,
            message_bus=runtime_message_bus,
            config=memory_integration_config,
        )
        if start:
            await self._context.memory.memory_integration.start()
            logger.info("MemoryIntegrationModule started")
        else:
            logger.warning("MemoryIntegrationModule held for full-clear recovery")

    async def shutdown(self) -> None:
        if self._context.memory.memory_integration is not None:
            await self._context.memory.memory_integration.stop()
            self._context.memory.memory_integration = None

        if self._context.memory.unified_memory is not None:
            await self._context.memory.unified_memory.shutdown()

        if self._context.llm.llm_usage_store is not None:
            await self._context.llm.llm_usage_store.stop()
            self._context.llm.llm_usage_store = None

        if self.start_memory_integration and self._context.message_bus.message_bus is not None:
            self._context.message_bus.message_bus.bind_memory_operation_epoch(None)

        self._context.memory.unified_memory = None
        self._context.memory.hybrid_retrieval_service = None


class MemoryIngestionSubscriberModule(LifecycleModule):
    """Subscribe MemoryIngestionSubscriber to the runtime event bus."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_memory_ingestion_subscriber",
            dependencies=("runtime_memory", "runtime_message_bus"),
        )
        self._context = context
        self._subscriber: Any = None

    async def init(self) -> None:
        if self._context.runtime_commands.full_clear_recovery_pending:
            logger.warning("Memory ingestion subscriber held for full-clear recovery")
            return
        from .subscribers.memory_ingestion_subscriber import MemoryIngestionSubscriber

        unified_memory = require_initialized(self._context.memory.unified_memory, "unified memory")
        message_bus = require_initialized(self._context.message_bus.message_bus, "message bus")
        self._subscriber = MemoryIngestionSubscriber(
            event_bus=message_bus,
            unified_memory=unified_memory,
        )
        await self._subscriber.start()
        self._context.memory.ingestion_subscriber = self._subscriber
        logger.info("MemoryIngestionSubscriber started")

    async def shutdown(self) -> None:
        if self._subscriber is not None:
            await self._subscriber.stop()
            self._subscriber = None
        self._context.memory.ingestion_subscriber = None


class L1MaintenanceScheduleRegistrationModule(LifecycleModule):
    """Register L1 retention maintenance with the unified scheduler."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_l1_maintenance_scheduler",
            dependencies=(
                "runtime_scheduler",
                "runtime_configuration",
                "runtime_memory",
                "runtime_exports",
            ),
        )
        self._context = context
        self._contrib: Any = None

    async def init(self) -> None:
        if self._context.runtime_commands.full_clear_recovery_pending:
            logger.warning("L1 maintenance schedule held for full-clear recovery")
            return
        from .l1.maintenance_schedule import L1MaintenanceScheduleContrib

        scheduler_service = require_initialized(
            self._context.scheduler.scheduler_service, "scheduler service"
        )
        self._contrib = L1MaintenanceScheduleContrib()
        await self._contrib.register_schedules(scheduler_service)

    async def shutdown(self) -> None:
        if self._contrib is None or self._context.scheduler.scheduler_service is None:
            self._contrib = None
            return
        await self._contrib.unregister_schedules(self._context.scheduler.scheduler_service)
        self._contrib = None


class L2MaintenanceScheduleRegistrationModule(LifecycleModule):
    """Register L2 entity maintenance with the unified scheduler (runtime worker)."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_l2_maintenance_scheduler",
            dependencies=(
                "runtime_scheduler",
                "runtime_configuration",
                "runtime_memory",
                "runtime_exports",
            ),
        )
        self._context = context
        self._contrib: Any = None

    async def init(self) -> None:
        if self._context.runtime_commands.full_clear_recovery_pending:
            logger.warning("L2 maintenance schedule held for full-clear recovery")
            return
        from .l2.maintenance_schedule import L2MaintenanceScheduleContrib

        scheduler_service = require_initialized(
            self._context.scheduler.scheduler_service, "scheduler service"
        )
        self._contrib = L2MaintenanceScheduleContrib()
        await self._contrib.register_schedules(scheduler_service)

    async def shutdown(self) -> None:
        if self._contrib is None or self._context.scheduler.scheduler_service is None:
            self._contrib = None
            return
        await self._contrib.unregister_schedules(self._context.scheduler.scheduler_service)
        self._contrib = None


class L2ConsolidationScheduleRegistrationModule(LifecycleModule):
    """Register L2 episode/experience consolidation with the unified scheduler."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_l2_consolidation_scheduler",
            dependencies=(
                "runtime_scheduler",
                "runtime_configuration",
                "runtime_memory",
                "runtime_exports",
            ),
        )
        self._context = context
        self._contrib: Any = None

    async def init(self) -> None:
        if self._context.runtime_commands.full_clear_recovery_pending:
            logger.warning("L2 consolidation schedule held for full-clear recovery")
            return
        from .l2.consolidation_schedule import L2ConsolidationScheduleContrib

        scheduler_service = require_initialized(
            self._context.scheduler.scheduler_service, "scheduler service"
        )
        self._contrib = L2ConsolidationScheduleContrib()
        await self._contrib.register_schedules(scheduler_service)

    async def shutdown(self) -> None:
        if self._contrib is None or self._context.scheduler.scheduler_service is None:
            self._contrib = None
            return
        await self._contrib.unregister_schedules(self._context.scheduler.scheduler_service)
        self._contrib = None


class L2DeriveScheduleRegistrationModule(LifecycleModule):
    """Register L2 derived-data schedule (interest aggregation + conflict notifications) with the unified scheduler (runtime worker)."""

    def __init__(
        self,
        context: RuntimeBootstrapContext,
        *,
        portrait_refresh_scheduler: Callable[[Any, str], Awaitable[None]] | None = None,
    ):
        super().__init__(
            name="runtime_l2_derive_scheduler",
            dependencies=(
                "runtime_scheduler",
                "runtime_configuration",
                "runtime_memory",
                "runtime_exports",
            ),
        )
        self._context = context
        self._portrait_refresh_scheduler = portrait_refresh_scheduler
        self._contrib: Any = None

    async def init(self) -> None:
        if self._context.runtime_commands.full_clear_recovery_pending:
            logger.warning("L2 derive schedule held for full-clear recovery")
            return
        from .l2.derive_schedule import L2DeriveScheduleContrib

        scheduler_service = require_initialized(
            self._context.scheduler.scheduler_service, "scheduler service"
        )
        self._contrib = L2DeriveScheduleContrib(
            portrait_refresh_scheduler=self._portrait_refresh_scheduler,
        )
        await self._contrib.register_schedules(scheduler_service)

    async def shutdown(self) -> None:
        if self._contrib is None or self._context.scheduler.scheduler_service is None:
            self._contrib = None
            return
        await self._contrib.unregister_schedules(self._context.scheduler.scheduler_service)
        self._contrib = None


class L3SummaryScheduleRegistrationModule(LifecycleModule):
    """Register L3 temporal summary cascade with the unified scheduler (runtime worker)."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_l3_summary_scheduler",
            dependencies=(
                "runtime_scheduler",
                "runtime_configuration",
                "runtime_memory",
                "runtime_exports",
            ),
        )
        self._context = context
        self._contrib: Any = None

    async def init(self) -> None:
        if self._context.runtime_commands.full_clear_recovery_pending:
            logger.warning("L3 summary schedule held for full-clear recovery")
            return
        from .l3.summary_schedule import L3SummaryScheduleContrib

        scheduler_service = require_initialized(
            self._context.scheduler.scheduler_service, "scheduler service"
        )
        self._contrib = L3SummaryScheduleContrib()
        await self._contrib.register_schedules(scheduler_service)

    async def shutdown(self) -> None:
        if self._contrib is None or self._context.scheduler.scheduler_service is None:
            self._contrib = None
            return
        await self._contrib.unregister_schedules(self._context.scheduler.scheduler_service)
        self._contrib = None


class L3MaintenanceScheduleRegistrationModule(LifecycleModule):
    """Register L3 summary-retention maintenance with the unified scheduler."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_l3_maintenance_scheduler",
            dependencies=(
                "runtime_scheduler",
                "runtime_configuration",
                "runtime_memory",
                "runtime_exports",
            ),
        )
        self._context = context
        self._contrib: Any = None

    async def init(self) -> None:
        if self._context.runtime_commands.full_clear_recovery_pending:
            logger.warning("L3 maintenance schedule held for full-clear recovery")
            return
        from .l3.maintenance_schedule import L3MaintenanceScheduleContrib

        scheduler_service = require_initialized(
            self._context.scheduler.scheduler_service, "scheduler service"
        )
        self._contrib = L3MaintenanceScheduleContrib()
        await self._contrib.register_schedules(scheduler_service)

    async def shutdown(self) -> None:
        if self._contrib is None or self._context.scheduler.scheduler_service is None:
            self._contrib = None
            return
        await self._contrib.unregister_schedules(self._context.scheduler.scheduler_service)
        self._contrib = None


class L4MaintenanceScheduleRegistrationModule(LifecycleModule):
    """Register L4 procedural-memory maintenance with the unified scheduler (runtime worker)."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_l4_maintenance_scheduler",
            dependencies=(
                "runtime_scheduler",
                "runtime_configuration",
                "runtime_memory",
                "runtime_exports",
            ),
        )
        self._context = context
        self._contrib: Any = None

    async def init(self) -> None:
        if self._context.runtime_commands.full_clear_recovery_pending:
            logger.warning("L4 maintenance schedule held for full-clear recovery")
            return
        from .l4.maintenance_schedule import L4MaintenanceScheduleContrib

        scheduler_service = require_initialized(
            self._context.scheduler.scheduler_service, "scheduler service"
        )
        self._contrib = L4MaintenanceScheduleContrib()
        await self._contrib.register_schedules(scheduler_service)

    async def shutdown(self) -> None:
        if self._contrib is None or self._context.scheduler.scheduler_service is None:
            self._contrib = None
            return
        await self._contrib.unregister_schedules(self._context.scheduler.scheduler_service)
        self._contrib = None
