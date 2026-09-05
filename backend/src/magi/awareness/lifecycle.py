"""L9 Sources Layer lifecycle module."""

from __future__ import annotations

from typing import Any

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..config import get_config
from ..core.logger import get_logger
from ..memory.source_ingestion import SourceEventCommitter
from .ingestion_gateway import SourceIngestionGateway
from .source_state import SourceStateWriteQueue, SqliteSourceStateStore
from .source_hub import SourceHub
from .event_emitter import RuntimeEventEmitter
from .scheduler_contrib import SourceSchedulerContrib
from .source_sync_executor import SourceSyncExecutor, SourceSyncExecutorState

logger = get_logger(__name__)


class SourceModule(LifecycleModule):
    """Initialize SourceHub and RuntimeEventEmitter (L9 - Sources layer)."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_source_hub",
            dependencies=("runtime_message_bus", "runtime_memory"),
        )
        self._context = context

    async def init(self) -> None:
        message_bus = require_initialized(self._context.message_bus.message_bus, "message bus")
        unified_memory = require_initialized(self._context.memory.unified_memory, "unified memory")

        self._context.agent_runtime.source_hub = SourceHub(message_bus=message_bus)
        self._context.agent_runtime.event_emitter = RuntimeEventEmitter(message_bus=message_bus)
        self._context.agent_runtime.source_ingestion_gateway = SourceIngestionGateway(
            event_bus=message_bus,
            memory_committer=SourceEventCommitter(unified_memory=unified_memory),
        )
        logger.info("SourceHub and RuntimeEventEmitter initialized (L9)")

    async def shutdown(self) -> None:
        self._context.agent_runtime.source_ingestion_gateway = None
        self._context.agent_runtime.source_hub = None
        self._context.agent_runtime.event_emitter = None


class SourceScheduleRegistrationModule(LifecycleModule):
    """Register source-owned scheduled handlers after scheduler startup."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_source_scheduler",
            dependencies=(
                "runtime_plugin_system",
                "runtime_scheduler",
                "runtime_memory",
                "runtime_core_dependencies",
                "runtime_timeline",
                "runtime_message_bus",
                "runtime_source_hub",
            ),
        )
        self._context = context
        self._contrib: SourceSchedulerContrib | None = None

    async def init(self) -> None:
        if self._context.runtime_commands.full_clear_recovery_pending:
            logger.warning("Source schedule registration held for full-clear recovery")
            return
        scheduler_service = require_initialized(
            self._context.scheduler.scheduler_service, "scheduler service"
        )
        runtime_paths = require_initialized(self._context.core.runtime_paths, "runtime paths")
        source_registry = require_initialized(
            self._context.plugins.source_registry, "source registry"
        )
        plugin_manager = require_initialized(self._context.plugins.plugin_manager, "plugin manager")
        ingestion_gateway = require_initialized(
            self._context.agent_runtime.source_ingestion_gateway,
            "source ingestion gateway",
        )

        self._contrib = SourceSchedulerContrib(
            scheduler_service=scheduler_service,
            source_registry=source_registry,
            plugin_manager=plugin_manager,
            runtime_paths=runtime_paths,
            get_config=get_config,
            ingestion_gateway=ingestion_gateway,
            source_store=require_initialized(self._context.plugins.source_store, "source store"),
        )
        self._context.agent_runtime.source_scheduler_contrib = self._contrib
        await self._contrib.register_schedules(scheduler_service)
        logger.info("Source schedule registration initialized (L9)")

    async def shutdown(self) -> None:
        if self._contrib is None or self._context.scheduler.scheduler_service is None:
            self._context.agent_runtime.source_scheduler_contrib = None
            return
        await self._contrib.unregister_schedules(self._context.scheduler.scheduler_service)
        self._context.agent_runtime.source_scheduler_contrib = None
        self._contrib = None

    async def queue_manual_sync(
        self,
        source_type: str,
        *,
        connection_id: str,
        first_context: bool = False,
        sync_mode: str = "latest",
        backfill_scope: str | None = None,
        backfill_days: int | None = None,
        backfill_start_date: str | None = None,
        backfill_end_date: str | None = None,
    ):
        """Queue a manual sync using the active source contributor."""
        if self._contrib is None:
            raise RuntimeError("source scheduler contributor is not initialized")
        return await self._contrib.queue_manual_sync(
            source_type,
            connection_id=connection_id,
            first_context=first_context,
            sync_mode=sync_mode,
            backfill_scope=backfill_scope,
            backfill_days=backfill_days,
            backfill_start_date=backfill_start_date,
            backfill_end_date=backfill_end_date,
        )


class SourceSyncExecutorModule(LifecycleModule):
    """Run queued source sync work on a dedicated thread."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_source_sync_executor",
            dependencies=("runtime_source_scheduler", "runtime_scheduler_activation"),
        )
        self._context = context
        self._executor: SourceSyncExecutor | None = None

    async def init(self) -> None:
        if self._context.runtime_commands.full_clear_recovery_pending:
            logger.warning("Source sync executor held for full-clear recovery")
            return
        previous_executor = self._executor
        if previous_executor is not None:
            if previous_executor.state is not SourceSyncExecutorState.STOPPED:
                raise RuntimeError("Previous source sync executor worker has not stopped")
            if self._context.agent_runtime.source_sync_executor is previous_executor:
                self._context.agent_runtime.source_sync_executor = None
            self._executor = None

        scheduler_service = require_initialized(
            self._context.scheduler.scheduler_service, "scheduler service"
        )
        contrib = require_initialized(
            self._context.agent_runtime.source_scheduler_contrib,
            "source scheduler contributor",
        )
        self._executor = SourceSyncExecutor(
            repository=scheduler_service.repository,
            run_job=contrib.execute_source_sync_job,
            flush_state=contrib.flush_source_state,
            scheduler_service=scheduler_service,
        )
        await self._executor.start()
        self._context.agent_runtime.source_sync_executor = self._executor
        logger.info("Source sync executor initialized (L9)")

    async def shutdown(self) -> None:
        if self._executor is not None:
            await self._executor.stop()
        self._context.agent_runtime.source_sync_executor = None
        self._executor = None


class SourceStateUpdateSubscriberModule(LifecycleModule):
    """Wire SourceStateUpdateSubscriber to the runtime event bus."""

    def __init__(self, context: RuntimeBootstrapContext) -> None:
        super().__init__(
            name="runtime_source_state_subscriber",
            dependencies=("runtime_message_bus", "runtime_core_dependencies"),
        )
        self._context = context
        self._subscriber: Any = None

    async def init(self) -> None:
        if self._context.runtime_commands.full_clear_recovery_pending:
            logger.warning("Source state subscriber held for full-clear recovery")
            return
        from .subscribers.source_state_update_subscriber import SourceStateUpdateSubscriber

        bus = require_initialized(self._context.message_bus.message_bus, "message bus")
        runtime_paths = require_initialized(self._context.core.runtime_paths, "runtime paths")
        store = SqliteSourceStateStore(runtime_paths.source_state_db_path)
        writer = SourceStateWriteQueue(source_state_store=store)
        self._subscriber = SourceStateUpdateSubscriber(event_bus=bus, source_state_writer=writer)
        await self._subscriber.start()
        logger.info("SourceStateUpdateSubscriber started")

    async def shutdown(self) -> None:
        if self._subscriber is not None:
            await self._subscriber.stop()
            self._subscriber = None
