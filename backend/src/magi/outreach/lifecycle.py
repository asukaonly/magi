"""Bootstrap module that assembles the outreach layer and registers the
background-completion producer + outbox-drain schedule."""
from __future__ import annotations

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

    async def init(self) -> None:
        ctx = self._context
        chat_store = require_initialized(ctx.chat.store, "chat store")
        scheduler = require_initialized(ctx.scheduler.scheduler_service, "scheduler service")
        manager = require_initialized(
            ctx.agent_runtime.background_task_manager, "background task manager"
        )

        channels_module = getattr(getattr(ctx, "channels", None), "module", None)
        registry = getattr(channels_module, "_registry", None)
        # receipts_store is OPTIONAL: ExternalChannelExecutor handles a None
        # store gracefully (delivery still happens, receipts just aren't
        # persisted). Only registry + session_mapper are hard requirements,
        # so receipts_store is deliberately NOT part of the disable guard.
        receipts_store = getattr(channels_module, "_receipts_store", None)
        session_mapper = getattr(channels_module, "_session_mapper", None)
        if registry is None or session_mapper is None:
            logger.warning(
                "outreach DISABLED — channels registry/session_mapper unavailable; "
                "no proactive task-completion delivery will occur"
            )
            return

        channels_db = str(get_runtime_paths().channels_db_path)
        delivery_log = OutreachDeliveryLogStore(db_path=channels_db)
        outbox = OutreachOutboxStore(db_path=channels_db)

        async def _compose(intent: OutreachIntent) -> str:
            return await compose_outreach_line(
                kind=intent.kind.value,
                title=intent.title,
                facts=intent.facts,
                persona_name=None,
            )

        service = OutreachService(
            compose=_compose,
            target_resolver=TargetResolver(
                read_service_factory=get_chat_read_service, session_mapper=session_mapper
            ),
            governor=Governor(delivery_log=delivery_log),
            desktop_executor=DesktopTranscriptExecutor(chat_store=chat_store),
            external_executor=ExternalChannelExecutor(
                delivery_router=DeliveryRouter(channel_registry=registry),
                receipts_store=receipts_store,
            ),
            outbox=outbox,
            delivery_log=delivery_log,
        )

        # Register the completion producer as a background-task listener.
        # NOTE: AgentRuntimeModule has already called manager.start() by the
        # time this module inits, so a task that completes in the brief boot
        # window before this line would miss the producer (the Tasks-page
        # broadcast listener, registered earlier, still fires). This is an
        # accepted v1 edge case for recovered-pending tasks; see spec section 11.
        self._producer = build_background_completion_producer(service)
        manager.add_listener(self._producer)

        # One-way-door note: if register_handler/schedule_interval below raise,
        # the producer listener stays added (shutdown() still removes it), but
        # the drain schedule would be absent — a restart re-runs this init.
        scheduler.register_handler(
            ScheduledTargetType.OUTREACH_OUTBOX_DRAIN,
            build_outbox_drain_handler(service),
        )
        await scheduler.schedule_interval(
            schedule_id=OUTBOX_DRAIN_SCHEDULE_ID,
            target_type=ScheduledTargetType.OUTREACH_OUTBOX_DRAIN,
            target_key=OUTBOX_DRAIN_TARGET_KEY,
            seconds=OUTBOX_DRAIN_INTERVAL_SECONDS,
            target_payload={},
        )
        logger.info("OutreachModule started (background-completion producer + outbox drain)")

    async def shutdown(self) -> None:
        manager = getattr(self._context.agent_runtime, "background_task_manager", None)
        if manager is not None and self._producer is not None:
            manager.remove_listener(self._producer)
        self._producer = None
