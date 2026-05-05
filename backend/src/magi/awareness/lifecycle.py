"""L9 Sensors Layer lifecycle module."""

from __future__ import annotations

from typing import Any

from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..config import get_config
from ..core.logger import get_logger
from ..timeline.adapter import TimelineAdapter
from .ingestion_gateway import SensorIngestionGateway
from .sensor_state import SqliteSensorStateStore
from .sensor_hub import SensorHub
from .event_emitter import RuntimeEventEmitter
from .scheduler_contrib import SensorSchedulerContrib
from .sensor_sync_executor import SensorSyncExecutor

logger = get_logger(__name__)


class SensorModule(LifecycleModule):
    """Initialize SensorHub and RuntimeEventEmitter (L9 - Sensors layer)."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_sensor_hub",
            dependencies=("runtime_message_bus",),
        )
        self._context = context

    async def init(self) -> None:
        message_bus = require_initialized(self._context.message_bus.message_bus, "message bus")

        self._context.agent_runtime.sensor_hub = SensorHub(message_bus=message_bus)
        self._context.agent_runtime.event_emitter = RuntimeEventEmitter(message_bus=message_bus)
        logger.info("SensorHub and RuntimeEventEmitter initialized (L9)")

    async def shutdown(self) -> None:
        self._context.agent_runtime.sensor_hub = None
        self._context.agent_runtime.event_emitter = None


class SensorScheduleRegistrationModule(LifecycleModule):
    """Register sensor-owned scheduled handlers after scheduler startup."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_sensor_scheduler",
            dependencies=(
                "runtime_plugin_system",
                "runtime_scheduler",
                "runtime_memory",
                "runtime_core_dependencies",
                "runtime_timeline",
                "runtime_message_bus",
            ),
        )
        self._context = context
        self._contrib: SensorSchedulerContrib | None = None

    async def init(self) -> None:
        scheduler_service = require_initialized(self._context.scheduler.scheduler_service, "scheduler service")
        runtime_paths = require_initialized(self._context.core.runtime_paths, "runtime paths")
        sensor_registry = require_initialized(self._context.plugins.sensor_registry, "sensor registry")
        plugin_manager = require_initialized(self._context.plugins.plugin_manager, "plugin manager")
        message_bus = require_initialized(self._context.message_bus.message_bus, "message bus")

        ingestion_gateway = SensorIngestionGateway(event_bus=message_bus)

        self._contrib = SensorSchedulerContrib(
            scheduler_service=scheduler_service,
            sensor_registry=sensor_registry,
            plugin_manager=plugin_manager,
            runtime_paths=runtime_paths,
            get_config=get_config,
            ingestion_gateway=ingestion_gateway,
        )
        self._context.agent_runtime.sensor_scheduler_contrib = self._contrib
        await self._contrib.register_schedules(scheduler_service)
        logger.info("Sensor schedule registration initialized (L9)")

    async def shutdown(self) -> None:
        if self._contrib is None or self._context.scheduler.scheduler_service is None:
            self._context.agent_runtime.sensor_scheduler_contrib = None
            return
        await self._contrib.unregister_schedules(self._context.scheduler.scheduler_service)
        self._context.agent_runtime.sensor_scheduler_contrib = None
        self._contrib = None

    async def queue_manual_sync(self, source_type: str):
        """Queue a manual sync using the active sensor contributor."""
        if self._contrib is None:
            raise RuntimeError("sensor scheduler contributor is not initialized")
        return await self._contrib.queue_manual_sync(source_type)


class SensorSyncExecutorModule(LifecycleModule):
    """Run queued sensor sync work on a dedicated thread."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_sensor_sync_executor",
            dependencies=("runtime_sensor_scheduler",),
        )
        self._context = context
        self._executor: SensorSyncExecutor | None = None

    async def init(self) -> None:
        scheduler_service = require_initialized(self._context.scheduler.scheduler_service, "scheduler service")
        contrib = require_initialized(
            self._context.agent_runtime.sensor_scheduler_contrib,
            "sensor scheduler contributor",
        )
        self._executor = SensorSyncExecutor(
            repository=scheduler_service.repository,
            run_job=contrib.execute_sensor_sync_job,
            flush_state=contrib.flush_sensor_state,
        )
        await self._executor.start()
        self._context.agent_runtime.sensor_sync_executor = self._executor
        logger.info("Sensor sync executor initialized (L9)")

    async def shutdown(self) -> None:
        if self._executor is not None:
            await self._executor.stop()
        self._context.agent_runtime.sensor_sync_executor = None
        self._executor = None


class TimelineSubscriberModule(LifecycleModule):
    """Wire TimelineSubscriber to the runtime event bus."""

    def __init__(self, context: RuntimeBootstrapContext) -> None:
        super().__init__(
            name="runtime_timeline_subscriber",
            dependencies=("runtime_message_bus", "runtime_timeline"),
        )
        self._context = context
        self._subscriber: Any = None

    async def init(self) -> None:
        from .subscribers.timeline_subscriber import TimelineSubscriber
        bus = require_initialized(self._context.message_bus.message_bus, "message bus")
        timeline = self._context.timeline.timeline_service
        if timeline is None:
            logger.info("Timeline service not available; TimelineSubscriber idle")
            return
        adapter = TimelineAdapter(timeline)
        self._subscriber = TimelineSubscriber(event_bus=bus, timeline_adapter=adapter)
        await self._subscriber.start()
        logger.info("TimelineSubscriber started")

    async def shutdown(self) -> None:
        if self._subscriber is not None:
            await self._subscriber.stop()
            self._subscriber = None


class KGSubscriberModule(LifecycleModule):
    """Wire KGSubscriber to the runtime event bus."""

    def __init__(self, context: RuntimeBootstrapContext) -> None:
        super().__init__(
            name="runtime_kg_subscriber",
            dependencies=("runtime_message_bus", "runtime_memory"),
        )
        self._context = context
        self._subscriber: Any = None

    async def init(self) -> None:
        from .subscribers.kg_subscriber import KGSubscriber
        bus = require_initialized(self._context.message_bus.message_bus, "message bus")
        unified_memory = require_initialized(self._context.memory.unified_memory, "unified memory")
        self._subscriber = KGSubscriber(event_bus=bus, unified_memory=unified_memory)
        await self._subscriber.start()
        logger.info("KGSubscriber started")

    async def shutdown(self) -> None:
        if self._subscriber is not None:
            await self._subscriber.stop()
            self._subscriber = None


class SensorStateUpdateSubscriberModule(LifecycleModule):
    """Wire SensorStateUpdateSubscriber to the runtime event bus."""

    def __init__(self, context: RuntimeBootstrapContext) -> None:
        super().__init__(
            name="runtime_sensor_state_subscriber",
            dependencies=("runtime_message_bus", "runtime_core_dependencies"),
        )
        self._context = context
        self._subscriber: Any = None

    async def init(self) -> None:
        from .subscribers.sensor_state_update_subscriber import SensorStateUpdateSubscriber
        bus = require_initialized(self._context.message_bus.message_bus, "message bus")
        runtime_paths = require_initialized(self._context.core.runtime_paths, "runtime paths")
        store = SqliteSensorStateStore(runtime_paths.sensor_state_db_path)
        self._subscriber = SensorStateUpdateSubscriber(event_bus=bus, sensor_state_store=store)
        await self._subscriber.start()
        logger.info("SensorStateUpdateSubscriber started")

    async def shutdown(self) -> None:
        if self._subscriber is not None:
            await self._subscriber.stop()
            self._subscriber = None
