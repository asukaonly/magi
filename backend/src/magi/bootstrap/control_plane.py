"""Bootstrap composition for the agent control plane.

Owns the lifetime of the process-wide control-plane singletons:

* :class:`~magi.control.session_store.ControlSessionStore`
* :class:`~magi.control.settings_manager.ControlSettingsManager`
* :class:`~magi.control.common.InteractionBroker`
* :class:`~magi.control.permission.rules.PermissionRuleStore`
* :class:`~magi.control.permission.gateway.PermissionGateway`

Wiring order:

1. Build rule store (sqlite-backed when a runtime path is available,
   in-memory otherwise for tests).
2. Build settings manager seeded from defaults (L0 preference
   persistence is orthogonal and loads later).
3. Build broker + session store and hydrate durable run plans.
4. Wire the gateway, pointing its ``plan_mode_guard`` at the session
   store's ``plan_allows`` method.
5. Override the DI container providers so every consumer — API
   router, ask_user tool, FunctionCallingOrchestrator — resolves the
   same instances.

The prompter installed here is a
:class:`BrokeredPermissionPrompter` that records every pending
prompt in the :class:`PendingPermissionRegistry` (so the frontend
can poll ``GET /api/control/sessions/{sid}/permissions``) and then
awaits ``broker.wait(kind='permission')`` until
``POST /api/control/permission/{request_id}/respond`` resolves it.
A transport-layer event hook (``notify_callback``) is intentionally
left unset — polling-plus-broker already closes the loop end-to-end
and IPC event emission can be layered on later.
"""

from __future__ import annotations


from dependency_injector import providers

from ..control.common import InteractionBroker
from ..control.common.events import publish_control_event
from ..control.permission.brokered_prompter import (
    BrokeredPermissionPrompter,
    PendingPermissionRegistry,
)
from ..control.permission.classifier import RiskClassifier
from ..control.permission.gateway import PermissionGateway
from ..control.permission.rules import PermissionRuleStore
from ..control.session_store import ControlSessionStore
from ..control.settings import ControlSettings
from ..control.settings_manager import ControlSettingsManager
from ..control.user_content_clear import ControlUserContentClearCoordinator
from ..core.container import get_container
from ..core.logger import get_logger
from .context import RuntimeBootstrapContext
from .lifecycle import LifecycleModule

logger = get_logger(__name__)


__all__ = [
    "ControlPlaneModule",
    "ControlPlaneWiring",
]


class ControlPlaneWiring:
    """Bundle of singletons built by :class:`ControlPlaneModule`."""

    __slots__ = (
        "settings_manager",
        "rule_store",
        "broker",
        "session_store",
        "gateway",
        "pending_permissions",
        "prompter",
        "user_content_clear",
    )

    def __init__(
        self,
        *,
        settings_manager: ControlSettingsManager,
        rule_store: PermissionRuleStore,
        broker: InteractionBroker,
        session_store: ControlSessionStore,
        gateway: PermissionGateway,
        pending_permissions: PendingPermissionRegistry,
        prompter: BrokeredPermissionPrompter,
        user_content_clear: ControlUserContentClearCoordinator,
    ) -> None:
        self.settings_manager = settings_manager
        self.rule_store = rule_store
        self.broker = broker
        self.session_store = session_store
        self.gateway = gateway
        self.pending_permissions = pending_permissions
        self.user_content_clear = user_content_clear
        #: The constructed prompter — exposed so ChannelsModule (which
        #: initializes later) can bind a control-fanout callback via
        #: ``prompter.bind_fanout_callback`` once the channel registry
        #: is built.
        self.prompter = prompter


class ControlPlaneModule(LifecycleModule):
    """Lifecycle module that owns the control-plane singletons."""

    def __init__(self, context: RuntimeBootstrapContext) -> None:
        super().__init__(
            name="runtime_control_plane",
            # init() reads runtime_paths.runtime_dir AND the alembic-managed
            # permission_rules table, so it MUST run after schema migrations.
            # ``runtime_database_migrations`` transitively requires
            # ``runtime_core_dependencies`` (which sets runtime_paths), so this
            # single edge guarantees both. Without it this module is
            # dependency-free and the orchestrator's FIFO topo-sort schedules
            # it ahead of DatabaseMigrationModule (which must wait for
            # core-deps), so on a fresh DB it read permission_rules before the
            # table existed.
            dependencies=("runtime_database_migrations",),
        )
        self._context = context
        self._wiring: ControlPlaneWiring | None = None

    @property
    def wiring(self) -> ControlPlaneWiring | None:
        return self._wiring

    async def init(self) -> None:
        runtime_paths = self._context.core.runtime_paths
        db_path: str | None = None
        if runtime_paths is not None:
            base = runtime_paths.runtime_dir
            base.mkdir(parents=True, exist_ok=True)
            db_path = str(base / "permission_rules.db")

        rule_store = PermissionRuleStore(db_path=db_path)
        await rule_store.initialize()

        settings_manager = ControlSettingsManager(ControlSettings())
        broker = InteractionBroker()
        session_store = ControlSessionStore(
            db_path=(
                runtime_paths.runtime_trace_db_path
                if runtime_paths is not None
                else None
            )
        )
        await session_store.initialize()
        pending_permissions = PendingPermissionRegistry()
        user_content_clear = ControlUserContentClearCoordinator(
            session_store=session_store,
            pending_permissions=pending_permissions,
            interaction_broker=broker,
        )

        async def _publish_permission_event(
            channel: str, payload: dict
        ) -> None:
            await publish_control_event(
                channel,
                payload,
                session_id=payload.get("session_id"),
                user_id=payload.get("user_id"),
                turn_id=payload.get("turn_id"),
            )

        prompter = BrokeredPermissionPrompter(
            broker=broker,
            registry=pending_permissions,
            notify_callback=_publish_permission_event,
        )
        gateway = PermissionGateway(
            classifier=RiskClassifier(),
            rules=rule_store,
            broker=broker,
            settings_provider=settings_manager.settings_provider,
            session_override_provider=settings_manager.session_override_provider,
            prompter=prompter,
            plan_mode_guard=session_store.plan_allows,
        )

        container = get_container()
        container.control_session_store.override(providers.Object(session_store))
        container.control_settings_manager.override(providers.Object(settings_manager))
        container.control_interaction_broker.override(providers.Object(broker))
        container.permission_rule_store.override(providers.Object(rule_store))
        container.permission_gateway.override(providers.Object(gateway))
        container.pending_permission_registry.override(
            providers.Object(pending_permissions)
        )

        self._wiring = ControlPlaneWiring(
            settings_manager=settings_manager,
            rule_store=rule_store,
            broker=broker,
            session_store=session_store,
            gateway=gateway,
            pending_permissions=pending_permissions,
            prompter=prompter,
            user_content_clear=user_content_clear,
        )
        # Park the module on context so ChannelsModule (Phase H+2) can
        # reach the prompter to bind a control-fanout callback. See
        # ``ChannelsModule.init`` for the late-binding code.
        self._context.control_plane.module = self
        logger.info(
            "control_plane.initialized",
            permission_rules_db=db_path,
            initial_permission_mode=settings_manager.get().permission_mode.value,
        )

    async def shutdown(self) -> None:
        container = get_container()
        container.control_session_store.reset_override()
        container.control_settings_manager.reset_override()
        container.control_interaction_broker.reset_override()
        container.permission_rule_store.reset_override()
        container.permission_gateway.reset_override()
        container.pending_permission_registry.reset_override()

        if self._wiring is not None:
            await self._wiring.session_store.shutdown()
            try:
                await self._wiring.broker.close(reason="shutdown")
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning("control_plane.broker_close_failed", error=str(exc))
        self._wiring = None
