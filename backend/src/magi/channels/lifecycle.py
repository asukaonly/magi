"""Lifecycle module for external messaging channels.

Phase G+1: the legacy ``NotificationRelay`` polling path is retired —
delivery now flows through ``DeliveryRouter`` on the write path. This
module always registers ``ChatSseChannel`` under the ``"chat_sse"`` key
so the chat UI keeps receiving streaming/final notifications even when
no plugin channels are loaded.

The ``_relay`` / ``_relay_task`` fields are kept as ``None`` for
backward-compat with any external diagnostics that probe them.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..bootstrap.lifecycle import LifecycleModule
from ..core.logger import get_logger
from ..core.runtime_bindings import require_chat_read_service

logger = get_logger(__name__)


@dataclass(frozen=True)
class _ChannelDependencies:
    plugin_manager: Any
    runtime_paths: Any
    runtime_command_queue: Any
    session_provisioner: Any
    attachment_store: Any
    trace_store: Any


@dataclass(frozen=True)
class _ChannelStartup:
    registry: Any
    session_mapper: Any
    ingress_boundary: Any
    binding_settings_store: Any
    cp_wiring: Any
    plugin_channel_count: int


def _plugin_channel_instances(plugin_manager: Any) -> list[Any]:
    channel_instances = []
    for plugin in plugin_manager.iter_loaded_plugins():
        channel = plugin.get_channel()
        if channel is not None:
            channel_instances.append(channel)
    return channel_instances


def _channels_db_path(runtime_paths: Any) -> str:
    db_path = str(runtime_paths.data_dir / "channels" / "channels.db")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return db_path


def _binding_origin_resolver(
    session_mapper: Any,
) -> Callable[[str | None], Awaitable[tuple[str, str] | None]]:
    async def resolve(session_id: str | None) -> tuple[str, str] | None:
        if not session_id:
            return None
        mapping = await session_mapper.lookup_by_session(session_id)
        if mapping is None:
            return None
        try:
            meta = json.loads(mapping.metadata_json) if mapping.metadata_json else {}
        except (json.JSONDecodeError, TypeError):
            return None
        ext_user_id = meta.get("external_user_id")
        if not ext_user_id:
            return None
        return (mapping.channel_type, str(ext_user_id))

    return resolve


def _permission_fanout_callback(
    *,
    registry: Any,
    delivery_router: Any,
) -> Callable[[Any], Awaitable[None]]:
    from magi_plugin_sdk import ControlRequest
    from magi_plugin_sdk.channels import ChannelTarget

    from ..control.permission.contracts import PermissionRequest
    from ..identity import CANONICAL_LOCAL_USER as DEFAULT_USER_ID

    async def fanout(request: Any) -> None:
        if not isinstance(request, PermissionRequest):
            return
        control_req = ControlRequest(
            request_id=request.request_id,
            short_id=request.short_id,
            kind="permission",
            tool_name=request.tool_name,
            preview=(request.preview or "")[:200],
            risk_level=request.risk_level.value,
            expires_at_ms=int(request.expires_at * 1000) if request.expires_at else None,
            payload={},
        )
        targets: list[ChannelTarget] = []
        magi_user_id = DEFAULT_USER_ID
        for channel in registry.all_channels():
            if not getattr(channel, "supports_control_requests", False):
                continue
            targets.append(
                ChannelTarget(
                    channel_type=channel.channel_type,
                    external_chat_id="",
                    magi_session_id=request.session_id or "",
                    magi_user_id=str(magi_user_id),
                )
            )
        if not targets:
            return
        await delivery_router.fanout_control_request(
            request=control_req,
            targets=targets,
        )

    return fanout


def _control_opt_in_channel_count(registry: Any) -> int:
    return sum(
        1
        for channel in registry.all_channels()
        if getattr(channel, "supports_control_requests", False)
    )


class ChannelsModule(LifecycleModule):
    """Initialize channel plugins and the in-process chat SSE channel."""

    def __init__(self, context: RuntimeBootstrapContext) -> None:
        super().__init__(
            name="runtime_channels",
            dependencies=(
                "runtime_chat_store",
                "runtime_trace",
                "runtime_command_queue",
                "runtime_configuration",
                "runtime_core_dependencies",
                "runtime_agent_core",
                "runtime_plugin_system",
                # Phase H+2: ChannelsModule wires the control-fanout
                # late bindings (prompter.bind_fanout_callback,
                # gateway.bind_auto_approve, dispatcher
                # permission_registry+broker). Adding the dependency
                # locks ChannelsModule to initialize AFTER the
                # control plane so context.control_plane.module is
                # always populated.
                "runtime_control_plane",
            ),
        )
        self._context = context
        # Retired in Phase G+1 — kept as None so external diagnostics that
        # probe ``module._relay`` / ``module._relay_task`` don't AttributeError.
        self._relay_task = None
        self._registry = None
        self._relay = None
        self._session_mapper = None
        self._receipts_store = None
        self._chat_delivery_dispatcher = None
        self._binding_settings_store = None
        self._ask_fanout_subscriber = None
        self._channel_operation_lock = asyncio.Lock()

    async def init(self) -> None:
        self._context.channels.module = self
        await self._start_channels()

    # === Public accessors (used by api/routers and tests) ===

    @property
    def binding_settings_store(self):
        """Per-binding settings store (Phase H+2). May be None
        before init() runs. Used by the channels-bindings API
        router to read/write the auto-approve toggle."""
        return self._binding_settings_store

    @property
    def session_mapper(self):
        """Session mapper used by the channels-bindings API to
        list known bindings (joining session mappings with
        settings rows)."""
        return self._session_mapper

    @property
    def channel_registry(self):
        """Currently active registry, replaced atomically across channel restarts."""

        return self._registry

    @property
    def receipts_store(self):
        """Currently active delivery receipt store."""

        return self._receipts_store

    @asynccontextmanager
    async def external_delivery_boundary(self) -> AsyncIterator[None]:
        """Use the current channel runtime without racing restart or clear."""

        async with self._channel_operation_lock:
            if not await self._conversation_delivery_allowed():
                raise RuntimeError(
                    "External conversation delivery is blocked by a pending clear"
                )
            yield

    @asynccontextmanager
    async def conversation_clear_boundary(self) -> AsyncIterator[None]:
        """Block channel restart and ask delivery while conversations clear."""

        async with self._channel_operation_lock:
            subscriber = self._ask_fanout_subscriber
            if subscriber is None:
                yield
                return
            async with subscriber.conversation_clear_boundary():
                yield

    async def restart(self) -> None:
        """Tear down running channels and re-initialize from current plugin state."""
        logger.info("Restarting channels module")
        async with self._channel_operation_lock:
            await self._stop_channels()
            await self._start_channels()

    async def shutdown(self) -> None:
        async with self._channel_operation_lock:
            await self._stop_channels()
            self._context.channels.module = None

    async def _start_channels(self) -> None:
        deps = self._channel_dependencies()
        channel_instances = _plugin_channel_instances(deps.plugin_manager)
        startup = await self._prepare_channel_startup(
            deps=deps,
            channel_instances=channel_instances,
        )
        await self._recover_pending_conversation_clear(startup.session_mapper)
        await startup.registry.start_all()
        self._activate_channel_runtime(startup)
        control_fanout_wired = await self._wire_control_fanout_if_available(startup)

        self._log_channels_started(
            plugin_channel_count=startup.plugin_channel_count,
            control_fanout_wired=control_fanout_wired,
        )

    async def _recover_pending_conversation_clear(self, session_mapper: Any) -> None:
        """Finish cross-store conversation cleanup before channels receive work."""

        from ..agent.orchestration import get_orchestration_store
        chat_read_service = require_chat_read_service()
        pending_count = (
            await chat_read_service.aget_interrupted_global_clear_count()
        )
        if pending_count is None:
            return
        background_task_manager = require_initialized(
            self._context.agent_runtime.background_task_manager,
            "background task manager",
        )
        runtime_command_queue = require_initialized(
            self._context.runtime_commands.runtime_command_queue,
            "runtime command queue",
        )
        async with runtime_command_queue.user_message_global_clear_boundary():
            async with background_task_manager.conversation_scope_boundary(
                reason="recover_global_conversation_clear"
            ):
                await session_mapper.clear_conversation_state()
                await background_task_manager.clear_all_history()
                await get_orchestration_store().clear_all()
                await runtime_command_queue.seal_external_user_message_clear_cutoff()
                completed = await chat_read_service.acomplete_global_clear()
                if not completed:
                    raise RuntimeError(
                        "Pending global conversation clear could not be completed"
                    )
        logger.info(
            "Recovered interrupted cross-store conversation clear",
            cleared_chat_count=pending_count,
        )

    @staticmethod
    async def _conversation_delivery_allowed() -> bool:
        try:
            pending = (
                await require_chat_read_service().aget_interrupted_global_clear_count()
            )
        except Exception:
            logger.exception("Failed to verify conversation clear state")
            return False
        return pending is None

    async def _prepare_channel_startup(
        self,
        *,
        deps: _ChannelDependencies,
        channel_instances: list[Any],
    ) -> _ChannelStartup:
        from .ingress_boundary import ChannelIngressBoundary

        channels_db_path = _channels_db_path(deps.runtime_paths)
        ingress_boundary = ChannelIngressBoundary(
            runtime_command_queue=deps.runtime_command_queue,
        )
        session_mapper = await self._create_session_mapper(
            db_path=channels_db_path,
            session_provisioner=deps.session_provisioner,
            ingress_boundary=ingress_boundary,
        )
        self._receipts_store = await self._create_receipts_store(channels_db_path)
        binding_settings_store = await self._create_binding_settings_store(channels_db_path)
        self._binding_settings_store = binding_settings_store
        cp_wiring = self._control_plane_wiring()
        registry = self._build_channel_registry(
            deps=deps,
            channel_instances=channel_instances,
            session_mapper=session_mapper,
            ingress_boundary=ingress_boundary,
            cp_wiring=cp_wiring,
        )
        return _ChannelStartup(
            registry=registry,
            session_mapper=session_mapper,
            ingress_boundary=ingress_boundary,
            binding_settings_store=binding_settings_store,
            cp_wiring=cp_wiring,
            plugin_channel_count=len(channel_instances),
        )

    def _build_channel_registry(
        self,
        *,
        deps: _ChannelDependencies,
        channel_instances: list[Any],
        session_mapper: Any,
        ingress_boundary: Any,
        cp_wiring: Any,
    ):
        from .registry import ChannelRegistry

        registry = ChannelRegistry()
        self._register_plugin_channels(
            registry=registry,
            channel_instances=channel_instances,
            session_mapper=session_mapper,
            message_dispatcher=self._message_dispatcher(
                cp_wiring=cp_wiring,
                session_mapper=session_mapper,
                ingress_boundary=ingress_boundary,
            ),
            attachment_store=self._guarded_attachment_store(
                attachment_store=deps.attachment_store,
                ingress_boundary=ingress_boundary,
            ),
            control_port=self._control_port(
                cp_wiring=cp_wiring,
                session_mapper=session_mapper,
                ingress_boundary=ingress_boundary,
            ),
        )
        # chat_sse must register even when no plugin channels are loaded.
        self._register_chat_sse(registry=registry, trace_store=deps.trace_store)
        return registry

    def _activate_channel_runtime(self, startup: _ChannelStartup) -> None:
        self._registry = startup.registry
        self._session_mapper = startup.session_mapper
        self._chat_delivery_dispatcher = self._create_chat_delivery_dispatcher(
            startup.registry
        )

    async def _wire_control_fanout_if_available(self, startup: _ChannelStartup) -> bool:
        # Close the late-binding loop for control fanout:
        #   1) prompter.bind_fanout_callback — outbound side; fans
        #      out the permission prompt to every channel that opted
        #      in (supports_control_requests=True) via
        #      DeliveryRouter.fanout_control_request.
        #   2) gateway.bind_auto_approve — bypass side; supplies the
        #      binding settings store + the origin resolver (which
        #      walks session_mapper.lookup_by_session to get
        #      channel_type + external_user_id from the session).
        #   3) AskFanoutSubscriber — outbound ask-user questions;
        #      subscribes to control events and sends pending asks to the
        #      originating external channel.
        #   4) message_dispatcher already wired above with broker +
        #      pending_permissions so /approve|/deny short-circuits.
        # Defensive: cp_wiring may be None in test bootstraps that
        # skip control_plane — every hook silently no-ops in that
        # case.
        if startup.cp_wiring is None:
            return False
        await self._wire_control_fanout(
            registry=startup.registry,
            session_mapper=startup.session_mapper,
            binding_settings_store=startup.binding_settings_store,
            cp_wiring=startup.cp_wiring,
        )
        return True

    def _log_channels_started(
        self,
        *,
        plugin_channel_count: int,
        control_fanout_wired: bool,
    ) -> None:
        logger.info(
            "Channels module started",
            plugin_channel_count=plugin_channel_count,
            chat_sse_registered=True,
            control_fanout_wired=control_fanout_wired,
        )

    def _channel_dependencies(self) -> _ChannelDependencies:
        return _ChannelDependencies(
            plugin_manager=require_initialized(
                self._context.plugins.plugin_manager,
                "plugin manager",
            ),
            runtime_paths=require_initialized(
                self._context.core.runtime_paths,
                "runtime paths",
            ),
            runtime_command_queue=require_initialized(
                self._context.runtime_commands.runtime_command_queue,
                "runtime command queue",
            ),
            session_provisioner=require_initialized(
                self._context.chat.channel_session_provisioner,
                "chat channel session provisioner",
            ),
            attachment_store=require_initialized(
                self._context.chat.channel_attachment_store,
                "chat channel attachment store",
            ),
            trace_store=require_initialized(
                self._context.runtime_trace.store,
                "runtime trace store",
            ),
        )

    async def _create_session_mapper(
        self,
        *,
        db_path: str,
        session_provisioner: Any,
        ingress_boundary: Any,
    ):
        from .session_mapper import ChannelSessionMapper

        identity_resolver = getattr(self._context.identity, "resolver", None)
        session_mapper = ChannelSessionMapper(
            db_path=db_path,
            session_provisioner=session_provisioner,
            ingress_boundary=ingress_boundary,
            identity_resolver=identity_resolver,
        )
        await session_mapper.initialize()
        return session_mapper

    async def _create_receipts_store(self, db_path: str):
        from .receipts_store import DeliveryReceiptsStore

        receipts_store = DeliveryReceiptsStore(db_path=db_path)
        await receipts_store.initialize()
        return receipts_store

    async def _create_binding_settings_store(self, db_path: str):
        from .binding_settings_store import ChannelBindingSettingsStore

        binding_settings_store = ChannelBindingSettingsStore(db_path=db_path)
        await binding_settings_store.initialize()
        return binding_settings_store

    def _control_plane_wiring(self):
        cp_module = getattr(self._context.control_plane, "module", None)
        return getattr(cp_module, "wiring", None) if cp_module else None

    def _message_dispatcher(
        self,
        *,
        cp_wiring: Any,
        session_mapper: Any,
        ingress_boundary: Any,
    ):
        from .dispatcher import ChannelMessageDispatcher

        return ChannelMessageDispatcher(
            ingress_boundary=ingress_boundary,
            permission_registry=(cp_wiring.pending_permissions if cp_wiring else None),
            interaction_broker=(cp_wiring.broker if cp_wiring else None),
            session_mapper=session_mapper,
        )

    def _control_port(
        self,
        *,
        cp_wiring: Any,
        session_mapper: Any,
        ingress_boundary: Any,
    ):
        from .control_commands import HostControlPort

        return HostControlPort(
            ingress_boundary=ingress_boundary,
            session_mapper=session_mapper,
            permission_registry=(cp_wiring.pending_permissions if cp_wiring else None),
            interaction_broker=(cp_wiring.broker if cp_wiring else None),
        )

    @staticmethod
    def _guarded_attachment_store(
        *,
        attachment_store: Any,
        ingress_boundary: Any,
    ):
        from .attachment_store import GuardedChannelAttachmentStore

        return GuardedChannelAttachmentStore(
            delegate=attachment_store,
            ingress_boundary=ingress_boundary,
        )

    def _register_plugin_channels(
        self,
        *,
        registry,
        channel_instances: list[Any],
        session_mapper: Any,
        message_dispatcher: Any,
        attachment_store: Any,
        control_port: Any,
    ) -> None:
        for channel in channel_instances:
            channel.bind_session_mapper(session_mapper)
            channel.bind_message_dispatcher(message_dispatcher)
            channel.bind_attachment_store(attachment_store)
            channel.bind_control_port(control_port)
            try:
                registry.register(channel)
            except ValueError:
                logger.warning(
                    "Duplicate channel type skipped",
                    channel_type=channel.channel_type,
                )

    def _register_chat_sse(self, *, registry, trace_store: Any) -> None:
        from .chat_sse_channel import ChatSseChannel

        chat_sse_channel = ChatSseChannel(trace_store=trace_store)
        try:
            registry.register(chat_sse_channel)
        except ValueError:
            logger.warning("chat_sse channel already registered, skipping duplicate")

    def _create_chat_delivery_dispatcher(self, registry):
        from .chat_delivery_dispatcher import (
            ChatDeliveryDispatcher,
            read_configured_delivery_prefs,
        )

        return ChatDeliveryDispatcher.from_registry(
            channel_registry=registry,
            user_prefs_provider=read_configured_delivery_prefs,
            receipts_store=self._receipts_store,
        )

    async def _wire_control_fanout(
        self,
        *,
        registry,
        session_mapper,
        binding_settings_store,
        cp_wiring,
    ) -> None:
        """Hook up external control egress late bindings.

        Kept as a small helper so ``_start_channels`` stays readable
        and the closure surface is explicit. Defensive throughout —
        any failure in here is logged and swallowed; the host's
        existing desktop-only approval path is unaffected.
        """
        from ..identity import CANONICAL_LOCAL_USER as DEFAULT_USER_ID
        from .delivery_router import DeliveryRouter

        try:
            delivery_router = DeliveryRouter(channel_registry=registry)
            cp_wiring.gateway.bind_auto_approve(
                binding_settings_store=binding_settings_store,
                binding_origin_resolver=_binding_origin_resolver(session_mapper),
            )

            cp_wiring.prompter.bind_fanout_callback(
                _permission_fanout_callback(
                    registry=registry,
                    delivery_router=delivery_router,
                )
            )
            logger.info(
                "Channels module: control fanout wired",
                opted_in_channel_count=_control_opt_in_channel_count(registry),
            )

            await self._start_ask_fanout_subscriber(
                session_mapper=session_mapper,
                delivery_router=delivery_router,
                default_user_id=DEFAULT_USER_ID,
            )
        except Exception:
            # Bind failures must not abort channels init — the desktop
            # approval path stays working, fanout / auto-approve just
            # don't fire. Logged for diagnosis.
            logger.exception("Channels module: control fanout wiring failed")

    async def _start_ask_fanout_subscriber(
        self,
        *,
        session_mapper: Any,
        delivery_router: Any,
        default_user_id: Any,
    ) -> None:
        from .ask_fanout import AskFanoutSubscriber

        event_bus = require_initialized(
            self._context.message_bus.message_bus,
            "message bus",
        )
        self._ask_fanout_subscriber = AskFanoutSubscriber(
            event_bus=event_bus,
            session_mapper=session_mapper,
            delivery_router=delivery_router,
            default_user_id=default_user_id,
            delivery_allowed=self._conversation_delivery_allowed,
        )
        await self._ask_fanout_subscriber.start()
        logger.info("Channels module: ask fanout subscriber started")

    async def _stop_channels(self) -> None:
        if self._ask_fanout_subscriber is not None:
            await self._ask_fanout_subscriber.stop()
            self._ask_fanout_subscriber = None
        if self._registry is not None:
            await self._registry.stop_all()
        self._registry = None
        self._session_mapper = None
        self._chat_delivery_dispatcher = None
        logger.info("Channels module stopped")
