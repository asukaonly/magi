"""L12 Timeline Domain lifecycle module."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from ..awareness.kg_write_queue import KnowledgeGraphWriteQueue
from ..bootstrap.lifecycle import LifecycleModule
from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..core.logger import get_logger
from .adapter import TimelineAdapter
from .service import TimelineService

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class TimelineModule(LifecycleModule):
    """Initialize TimelineService (L12 - Timeline layer)."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_timeline",
            dependencies=(
                "runtime_memory",
                "runtime_plugin_system",
                "runtime_core_dependencies",
                "runtime_location",
                "runtime_manual_entries",
            ),
        )
        self._context = context

    async def init(self) -> None:
        unified_memory = require_initialized(self._context.memory.unified_memory, "unified memory")

        self._context.timeline.timeline_service = TimelineService(
            unified_memory,
            location_resolver=self._context.location.resolver,
            manual_entry_asset_store=self._context.manual_entries.asset_store,
        )
        logger.info("TimelineService initialized (L12)")

    async def shutdown(self) -> None:
        self._context.timeline.timeline_service = None


logger_schedulers = get_logger("magi.timeline.lifecycle.schedulers")


class TimelineSchedulersModule(LifecycleModule):
    """Construct and register the four timeline scheduler contributors.

    Depends on:
      - context.scheduler.scheduler_service (SchedulerModule)
      - context.memory.unified_memory (MemoryStoreModule) — provides .l2, .l3, .memory_db_path
      - context.memory.media_source_registry (MediaRegistryModule)
      - context.llm.scenario_llm_pool (LLMRuntime) — for diary narrative client

    If any required dep is missing, the affected contributors are silently
    skipped (with a warning) rather than crashing bootstrap.
    """

    def __init__(self, context: RuntimeBootstrapContext) -> None:
        super().__init__(
            name="runtime_timeline_schedulers",
            dependencies=(
                "runtime_scheduler",
                "runtime_configuration",
                "runtime_memory",
                "runtime_exports",
                "runtime_location",
            ),
        )
        self._context = context
        self._contribs: list[Any] = []

    async def init(self) -> None:
        scheduler_service = getattr(self._context.scheduler, "scheduler_service", None)
        if scheduler_service is None:
            logger_schedulers.warning(
                "TimelineSchedulersModule skipped: scheduler_service unavailable"
            )
            return

        from .narrative.scheduler_contrib import DiaryNarrativeSchedulerContrib
        from .narrative.orchestrator import DiaryNarrativeOrchestrator
        from .narrative.llm_client import DiaryNarrativeLLMClient
        from .standout.scheduler_contrib import StandoutScoringSchedulerContrib
        from .mood.scheduler_contrib import MoodAggregateSchedulerContrib
        from .mood.sample_source import L2ValenceSampleSource
        from ..media.scheduler_contrib import RepresentativeAssetPopulateSchedulerContrib
        from ..media.selector import MediaSelector
        from ..memory.l3.daily_mood.store import DailyMoodAggregateStore
        from ..location.scheduler_contrib import (
            IPGeoPollSchedulerContrib,
            WiFiPollSchedulerContrib,
        )

        unified = getattr(self._context.memory, "unified_memory", None)
        l1_store = getattr(unified, "l1", None) if unified else None
        l2_store = getattr(unified, "l2", None) if unified else None
        l3_store = getattr(unified, "l3", None) if unified else None
        memory_db_path = getattr(unified, "memory_db_path", None) if unified else None
        media_registry = getattr(self._context.memory, "media_source_registry", None)
        scenario_pool = getattr(getattr(self._context, "llm", None), "scenario_llm_pool", None)

        # 1. Diary narrative
        if l2_store is not None and l3_store is not None:
            llm_client = DiaryNarrativeLLMClient(scenario_llm_pool=scenario_pool)
            # l1_store is optional but recommended: without it, the LLM only
            # sees abstract episode metadata (label, topics, entity ids) and
            # writes generic prose. With it, the orchestrator pulls actual
            # content snippets the user touched and feeds them to the LLM.
            orchestrator = DiaryNarrativeOrchestrator(
                l2_store=l2_store,
                l3_store=l3_store,
                llm_client=llm_client,
                l1_store=l1_store,
            )
            contrib = DiaryNarrativeSchedulerContrib(orchestrator=orchestrator)
            await contrib.register_schedules(scheduler_service)
            self._contribs.append(contrib)
            logger_schedulers.info("Registered TIMELINE_DIARY_NARRATIVE scheduler")
        else:
            logger_schedulers.warning(
                "Skipping diary narrative scheduler: l2=%s l3=%s",
                l2_store is not None, l3_store is not None,
            )

        # 2. Standout rescoring
        if l2_store is not None and media_registry is not None:
            contrib = StandoutScoringSchedulerContrib(
                l2_store=l2_store, media_registry=media_registry,
            )
            await contrib.register_schedules(scheduler_service)
            self._contribs.append(contrib)
            logger_schedulers.info("Registered TIMELINE_STANDOUT_RESCORE scheduler")
        else:
            logger_schedulers.warning(
                "Skipping standout scheduler: l2=%s media_registry=%s",
                l2_store is not None, media_registry is not None,
            )

        # 3. Mood aggregate
        if l2_store is not None and memory_db_path is not None:
            sample_source = L2ValenceSampleSource(l2_store=l2_store)
            mood_store = DailyMoodAggregateStore(db_path=str(memory_db_path))
            await mood_store.initialize()
            contrib = MoodAggregateSchedulerContrib(
                sample_source=sample_source, mood_store=mood_store,
            )
            await contrib.register_schedules(scheduler_service)
            self._contribs.append(contrib)
            logger_schedulers.info("Registered TIMELINE_MOOD_AGGREGATE scheduler")
        else:
            logger_schedulers.warning(
                "Skipping mood aggregate scheduler: l2=%s memory_db_path=%s",
                l2_store is not None, memory_db_path is not None,
            )

        # 4. Representative asset populate
        if l2_store is not None and media_registry is not None:
            selector = MediaSelector(registry=media_registry)
            contrib = RepresentativeAssetPopulateSchedulerContrib(
                l2_store=l2_store, selector=selector,
            )
            await contrib.register_schedules(scheduler_service)
            self._contribs.append(contrib)
            logger_schedulers.info("Registered TIMELINE_REPRESENTATIVE_ASSET scheduler")
        else:
            logger_schedulers.warning(
                "Skipping representative-asset scheduler: l2=%s media_registry=%s",
                l2_store is not None, media_registry is not None,
            )

        # 5/6. Location pollers — the WiFi/IPGeo sources are owned and built
        # once by LocationModule (context.location); reuse them here instead of
        # rebuilding (previously these were a second, duplicate construction).
        loc = self._context.location
        ipgeo_source = getattr(loc, "ipgeo_source", None)
        wifi_source = getattr(loc, "wifi_source", None)
        if ipgeo_source is not None:
            contrib = IPGeoPollSchedulerContrib(ipgeo_source=ipgeo_source)
            await contrib.register_schedules(scheduler_service)
            self._contribs.append(contrib)
            logger_schedulers.info("Registered LOCATION_IPGEO_POLL scheduler")
        else:
            logger_schedulers.warning(
                "Skipping ipgeo scheduler: location source unavailable",
            )
        if wifi_source is not None:
            contrib = WiFiPollSchedulerContrib(wifi_source=wifi_source)
            await contrib.register_schedules(scheduler_service)
            self._contribs.append(contrib)
            logger_schedulers.info("Registered LOCATION_WIFI_POLL scheduler")
        else:
            logger_schedulers.warning(
                "Skipping wifi scheduler: location source unavailable",
            )

    async def shutdown(self) -> None:
        scheduler_service = getattr(self._context.scheduler, "scheduler_service", None)
        if scheduler_service is None:
            self._contribs = []
            return
        for contrib in self._contribs:
            try:
                await contrib.unregister_schedules(scheduler_service)
            except Exception as exc:
                logger_schedulers.warning(
                    "Failed to unregister contrib %s: %s", type(contrib).__name__, exc
                )
        self._contribs = []


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
        writer = KnowledgeGraphWriteQueue(unified_memory=unified_memory)
        self._subscriber = KGSubscriber(event_bus=bus, kg_writer=writer)
        await self._subscriber.start()
        logger.info("KGSubscriber started")

    async def shutdown(self) -> None:
        if self._subscriber is not None:
            await self._subscriber.stop()
            self._subscriber = None
