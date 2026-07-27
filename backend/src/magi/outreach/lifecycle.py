"""Bootstrap module that assembles the outreach layer and registers the
background-completion producer + outbox-drain schedule."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..bootstrap.lifecycle import LifecycleModule
from ..channels.delivery_router import DeliveryRouter
from ..chat import get_chat_read_service
from ..core.logger import get_logger
from ..personality.outreach_compose import compose_outreach_line
from ..scheduler.contracts import ScheduledTargetType
from ..utils.runtime import get_runtime_paths
from .contracts import OutreachIntent
from .executor import DesktopTranscriptExecutor, ExternalChannelExecutor
from .governor import Governor
from .producers.background_completion import build_background_completion_producer
from .schedule import (
    OUTBOX_DRAIN_INTERVAL_SECONDS,
    OUTBOX_DRAIN_SCHEDULE_ID,
    OUTBOX_DRAIN_TARGET_KEY,
    build_outbox_drain_handler,
)
from .service import OutreachService
from .stores import OutreachDeliveryLogStore, OutreachOutboxStore
from .target_resolver import TargetResolver

logger = get_logger(__name__)


@dataclass(frozen=True)
class _OutreachRuntimeDeps:
    chat_store: Any
    scheduler: Any
    manager: Any


@dataclass(frozen=True)
class _OutreachChannelDeps:
    module: Any
    receipts_store: Any


class _LiveChannelRegistry:
    """Resolve channels from the current channel runtime at delivery time."""

    def __init__(self, context: RuntimeBootstrapContext) -> None:
        self._context = context

    def get(self, channel_id: str) -> Any:
        module = getattr(self._context.channels, "module", None)
        registry = getattr(module, "channel_registry", None)
        if registry is None:
            return None
        return registry.get(channel_id)


class _LiveChannelSessionMapper:
    """Resolve mappings from the current channel runtime after restart."""

    def __init__(self, context: RuntimeBootstrapContext) -> None:
        self._context = context

    async def lookup_by_session(self, session_id: str) -> Any:
        module = getattr(self._context.channels, "module", None)
        mapper = getattr(module, "session_mapper", None)
        if mapper is None:
            return None
        return await mapper.lookup_by_session(session_id)


class OutreachModule(LifecycleModule):
    def __init__(self, context: RuntimeBootstrapContext) -> None:
        super().__init__(
            name="runtime_outreach",
            dependencies=(
                "runtime_agent_core",
                "runtime_channels",
                "runtime_scheduler",
                "runtime_chat_store",
                "runtime_personality",
            ),
        )
        self._context = context
        self._producer = None
        self._service = None

    async def init(self) -> None:
        ctx = self._context
        runtime_deps = self._runtime_deps(ctx)
        channel_deps = self._channel_deps(ctx)
        if channel_deps is None:
            logger.warning(
                "outreach DISABLED — channels registry/session_mapper unavailable; "
                "no proactive task-completion delivery will occur"
            )
            return

        service = self._build_service(runtime_deps.chat_store, channel_deps)
        self._service = service
        ctx.outreach.service = service
        await self._register_background_completion(runtime_deps.manager, service)
        await self._register_outbox_drain(
            runtime_deps.scheduler,
            service,
            self._producer,
        )
        logger.info("OutreachModule started (background-completion producer + outbox drain)")

    @staticmethod
    def _runtime_deps(ctx: RuntimeBootstrapContext) -> _OutreachRuntimeDeps:
        return _OutreachRuntimeDeps(
            chat_store=require_initialized(ctx.chat.store, "chat store"),
            scheduler=require_initialized(ctx.scheduler.scheduler_service, "scheduler service"),
            manager=require_initialized(
                ctx.agent_runtime.background_task_manager, "background task manager"
            ),
        )

    @staticmethod
    def _channel_deps(ctx: RuntimeBootstrapContext) -> _OutreachChannelDeps | None:
        channels_module = getattr(getattr(ctx, "channels", None), "module", None)
        registry = getattr(channels_module, "channel_registry", None)
        session_mapper = getattr(channels_module, "session_mapper", None)
        if registry is None or session_mapper is None:
            return None
        # receipts_store is optional: delivery still happens when receipts
        # persistence is unavailable.
        return _OutreachChannelDeps(
            module=channels_module,
            receipts_store=getattr(channels_module, "receipts_store", None),
        )

    def _build_service(
        self,
        chat_store: Any,
        channel_deps: _OutreachChannelDeps,
    ) -> OutreachService:
        channels_db = str(get_runtime_paths().channels_db_path)
        delivery_log = OutreachDeliveryLogStore(db_path=channels_db)
        outbox = OutreachOutboxStore(db_path=channels_db)
        return OutreachService(
            compose=self._compose,
            target_resolver=TargetResolver(
                read_service_factory=get_chat_read_service,
                session_mapper=_LiveChannelSessionMapper(self._context),
            ),
            governor=Governor(delivery_log=delivery_log),
            desktop_executor=DesktopTranscriptExecutor(chat_store=chat_store),
            external_executor=ExternalChannelExecutor(
                delivery_router=DeliveryRouter(
                    channel_registry=_LiveChannelRegistry(self._context)
                ),
                receipts_store=channel_deps.receipts_store,
                delivery_boundary=channel_deps.module.external_delivery_boundary,
            ),
            outbox=outbox,
            delivery_log=delivery_log,
            post_turn_understanding_service=require_initialized(
                self._context.agent_runtime.post_turn_understanding_service,
                "post-turn understanding service",
            ),
        )

    @staticmethod
    async def _compose(intent: OutreachIntent) -> str:
        return await compose_outreach_line(
            kind=intent.kind.value,
            title=intent.title,
            facts=intent.facts,
            persona_name=None,
        )

    async def _register_background_completion(
        self,
        manager: Any,
        service: OutreachService,
    ) -> None:
        recovered_claims = (
            await manager.store.recover_interrupted_completion_claims()
        )
        if recovered_claims:
            logger.info(
                "Recovered interrupted background completion deliveries",
                count=recovered_claims,
            )
        # Attach first so completions racing startup are serialized with the
        # durable catch-up drain owned by the same producer.
        self._producer = build_background_completion_producer(
            service,
            completion_store=manager.store,
        )
        manager.add_listener(self._producer)
        recovered = await self._producer.drain_pending()
        if recovered:
            logger.info(
                "Recovered pending background completion intents",
                count=recovered,
            )

    async def _register_outbox_drain(
        self,
        scheduler: Any,
        service: OutreachService,
        producer: Any,
    ) -> None:
        # One-way-door note: if register_handler/schedule_interval below raise,
        # the producer listener stays added (shutdown() still removes it), but
        # the drain schedule would be absent — a restart re-runs this init.
        scheduler.register_handler(
            ScheduledTargetType.OUTREACH_OUTBOX_DRAIN,
            build_outbox_drain_handler(service, producer),
        )
        await scheduler.schedule_interval(
            schedule_id=OUTBOX_DRAIN_SCHEDULE_ID,
            target_type=ScheduledTargetType.OUTREACH_OUTBOX_DRAIN,
            target_key=OUTBOX_DRAIN_TARGET_KEY,
            seconds=OUTBOX_DRAIN_INTERVAL_SECONDS,
            target_payload={},
        )

    async def shutdown(self) -> None:
        manager = getattr(self._context.agent_runtime, "background_task_manager", None)
        if manager is not None and self._producer is not None:
            manager.remove_listener(self._producer)
        self._producer = None
        self._service = None
        self._context.outreach.service = None
