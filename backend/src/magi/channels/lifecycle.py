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

from ..bootstrap.context import RuntimeBootstrapContext, require_initialized
from ..bootstrap.lifecycle import LifecycleModule
from ..core.logger import get_logger

logger = get_logger(__name__)


class ChannelsModule(LifecycleModule):
    """Initialize channel plugins and the in-process chat SSE channel."""

    def __init__(self, context: RuntimeBootstrapContext) -> None:
        super().__init__(
            name="runtime_channels",
            dependencies=(
                "runtime_chat_store",
                "runtime_trace",
                "runtime_configuration",
                "runtime_core_dependencies",
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
        self._binding_settings_store = None

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

    async def restart(self) -> None:
        """Tear down running channels and re-initialize from current plugin state."""
        logger.info("Restarting channels module")
        await self._stop_channels()
        await self._start_channels()

    async def shutdown(self) -> None:
        await self._stop_channels()
        self._context.channels.module = None

    async def _start_channels(self) -> None:
        from .attachments import ChannelAttachmentStore
        from .chat_sse_channel import ChatSseChannel
        from .dispatcher import ChannelMessageDispatcher
        from .registry import ChannelRegistry
        from .session_mapper import ChannelSessionMapper

        plugin_manager = require_initialized(self._context.plugins.plugin_manager, "plugin manager")
        runtime_paths = require_initialized(self._context.core.runtime_paths, "runtime paths")
        chat_store = require_initialized(self._context.chat.store, "chat store")
        trace_store = require_initialized(self._context.runtime_trace.store, "runtime trace store")

        # Collect channel instances from loaded plugins.
        channel_instances = []
        for plugin in plugin_manager.iter_loaded_plugins():
            channel = plugin.get_channel()
            if channel is not None:
                channel_instances.append(channel)

        # Phase G+1: chat_sse must register even in solo deployments
        # (no plugin channels) — the chat UI depends on the runtime_trace
        # rows that ``ChatSseChannel.deliver`` writes. So we proceed
        # unconditionally and only set up the plugin-binding facades when
        # there are plugin channels that need them.
        channels_db_path = str(runtime_paths.data_dir / "channels" / "channels.db")
        from pathlib import Path
        Path(channels_db_path).parent.mkdir(parents=True, exist_ok=True)

        # Identity layer (L1): pull the active resolver off the bootstrap
        # context. IdentityModule initialized earlier in the lifecycle
        # (infrastructure phase) so it's always present in production;
        # tests / partial bootstraps may omit it, in which case the
        # mapper falls back to CANONICAL_LOCAL_USER (single-user default).
        identity_resolver = getattr(self._context.identity, "resolver", None)
        session_mapper = ChannelSessionMapper(
            db_path=channels_db_path,
            chat_store=chat_store,
            identity_resolver=identity_resolver,
        )
        await session_mapper.initialize()

        from .receipts_store import DeliveryReceiptsStore
        self._receipts_store = DeliveryReceiptsStore(db_path=channels_db_path)
        await self._receipts_store.initialize()

        # Phase H+2: per-binding settings store (backs the "外部渠道
        # 免审批" toggle). Initialized here so CF-8's auto-approve
        # bypass below can attach it to the gateway.
        from .binding_settings_store import ChannelBindingSettingsStore
        binding_settings_store = ChannelBindingSettingsStore(
            db_path=channels_db_path
        )
        await binding_settings_store.initialize()
        self._binding_settings_store = binding_settings_store

        # Phase H+2: pull the control-plane prompter / registry / broker
        # so the dispatcher can short-circuit /approve|/deny slash
        # commands AND so the prompter can fanout permission prompts
        # to external channels (closures below). Defensive None checks
        # because partial bootstraps (some tests) may skip the
        # control_plane dependency.
        cp_module = getattr(self._context.control_plane, "module", None)
        cp_wiring = getattr(cp_module, "wiring", None) if cp_module else None
        message_dispatcher = ChannelMessageDispatcher(
            permission_registry=(
                cp_wiring.pending_permissions if cp_wiring else None
            ),
            interaction_broker=(
                cp_wiring.broker if cp_wiring else None
            ),
            session_mapper=session_mapper,
        )
        from .control_commands import HostControlPort

        # Unified control-command port (permission + session + /help). Bound to
        # every channel so plugins can invoke control commands explicitly via the
        # typed ChannelControlPortProtocol. Runs IN PARALLEL with the dispatcher's
        # legacy inline command handling during migration — a command is handled by
        # whichever path the plugin takes, never both.
        control_port = HostControlPort(
            session_mapper=session_mapper,
            permission_registry=(cp_wiring.pending_permissions if cp_wiring else None),
            interaction_broker=(cp_wiring.broker if cp_wiring else None),
        )
        attachment_store = ChannelAttachmentStore(runtime_paths=runtime_paths)

        registry = ChannelRegistry()
        for channel in channel_instances:
            channel.bind_session_mapper(session_mapper)
            channel.bind_message_dispatcher(message_dispatcher)
            channel.bind_attachment_store(attachment_store)
            channel.bind_control_port(control_port)
            try:
                registry.register(channel)
            except ValueError:
                logger.warning("Duplicate channel type skipped", channel_type=channel.channel_type)

        # Always register the in-process chat SSE channel. It writes
        # directly to runtime_trace_store, which the chat UI polls — so the
        # NotificationRelay polling fan-out is no longer required for chat.
        chat_sse_channel = ChatSseChannel(trace_store=trace_store)
        try:
            registry.register(chat_sse_channel)
        except ValueError:
            logger.warning("chat_sse channel already registered, skipping duplicate")

        await registry.start_all()

        self._registry = registry
        self._session_mapper = session_mapper

        # Phase H+2: close the late-binding loop for control fanout.
        # Three hooks established by CF-5/6/8 get wired here:
        #   1) prompter.bind_fanout_callback — outbound side; fans
        #      out the permission prompt to every channel that opted
        #      in (supports_control_requests=True) via
        #      DeliveryRouter.fanout_control_request.
        #   2) gateway.bind_auto_approve — bypass side; supplies the
        #      binding settings store + the origin resolver (which
        #      walks session_mapper.lookup_by_session to get
        #      channel_type + external_user_id from the session).
        #   3) message_dispatcher already wired above with broker +
        #      pending_permissions so /approve|/deny short-circuits.
        # Defensive: cp_wiring may be None in test bootstraps that
        # skip control_plane — every hook silently no-ops in that
        # case.
        if cp_wiring is not None:
            await self._wire_control_fanout(
                registry=registry,
                session_mapper=session_mapper,
                binding_settings_store=binding_settings_store,
                cp_wiring=cp_wiring,
            )

        logger.info(
            "Channels module started",
            plugin_channel_count=len(channel_instances),
            chat_sse_registered=True,
            control_fanout_wired=cp_wiring is not None,
        )

    async def _wire_control_fanout(
        self,
        *,
        registry,
        session_mapper,
        binding_settings_store,
        cp_wiring,
    ) -> None:
        """Hook up CF-5 (prompter fanout) + CF-8 (gateway auto-approve)
        late bindings now that channel registry + session_mapper exist.

        Kept as a small helper so ``_start_channels`` stays readable
        and the closure surface is explicit. Defensive throughout —
        any failure in here is logged and swallowed; the host's
        existing desktop-only approval path is unaffected.
        """
        import json
        from magi_plugin_sdk import ControlRequest
        from magi_plugin_sdk.channels import ChannelTarget
        from ..runtime_defaults import DEFAULT_USER_ID
        from .delivery_router import DeliveryRouter

        try:
            delivery_router = DeliveryRouter(channel_registry=registry)

            # === Origin resolver for CF-8 auto-approve bypass ===
            # session_id -> (channel_type, external_user_id) | None
            # Reads the channel_session_mappings row and parses
            # external_user_id out of metadata_json.
            async def _binding_origin_resolver(
                session_id: str | None,
            ) -> tuple[str, str] | None:
                if not session_id:
                    return None
                mapping = await session_mapper.lookup_by_session(
                    session_id
                )
                if mapping is None:
                    return None
                try:
                    meta = (
                        json.loads(mapping.metadata_json)
                        if mapping.metadata_json
                        else {}
                    )
                except (json.JSONDecodeError, TypeError):
                    return None
                ext_user_id = meta.get("external_user_id")
                if not ext_user_id:
                    return None
                return (mapping.channel_type, str(ext_user_id))

            cp_wiring.gateway.bind_auto_approve(
                binding_settings_store=binding_settings_store,
                binding_origin_resolver=_binding_origin_resolver,
            )

            # === CF-5 fanout_callback ===
            # On every permission prompt, enumerate channels that
            # opted in (supports_control_requests=True) and fanout
            # via DeliveryRouter.fanout_control_request.
            async def _fanout_callback(request) -> None:
                from ..control.permission.contracts import PermissionRequest
                if not isinstance(request, PermissionRequest):
                    return
                # Build the SDK payload. Truncate preview to keep
                # plugin-side rendering predictable (Telegram callback
                # text caps, WeChat text caps).
                control_req = ControlRequest(
                    request_id=request.request_id,
                    short_id=request.short_id,
                    kind="permission",
                    tool_name=request.tool_name,
                    preview=(request.preview or "")[:200],
                    risk_level=request.risk_level.value,
                    expires_at_ms=(
                        int(request.expires_at * 1000)
                        if request.expires_at
                        else None
                    ),
                    payload={},
                )
                targets: list[ChannelTarget] = []
                magi_user_id = DEFAULT_USER_ID  # single-user mode
                for ch in registry.all_channels():
                    if not getattr(
                        ch, "supports_control_requests", False
                    ):
                        continue
                    targets.append(
                        ChannelTarget(
                            channel_type=ch.channel_type,
                            external_chat_id="",
                            magi_session_id=request.session_id or "",
                            magi_user_id=str(magi_user_id),
                        )
                    )
                if not targets:
                    return
                await delivery_router.fanout_control_request(
                    request=control_req, targets=targets,
                )

            cp_wiring.prompter.bind_fanout_callback(_fanout_callback)
            logger.info(
                "Channels module: control fanout wired",
                opted_in_channel_count=sum(
                    1
                    for c in registry.all_channels()
                    if getattr(c, "supports_control_requests", False)
                ),
            )

            # === ask fanout (lightweight external egress) ===
            # A channel-originated turn can pause mid-execution to ask the user
            # a question. Desktop gets quick-reply chips + a transcript card;
            # external channels had NO ask egress at all, so the channel user
            # could neither see the question nor answer it (the turn blocked
            # until timeout). Bind a callback that delivers the question as a
            # plain-text message to the channel the session is bound to. The
            # inbound answer already routes back via
            # message_dispatch_service._resolve_pending_ask_response (a text
            # reply on the session resolves the broker), so no inbound code is
            # needed here.
            from ..control.common.ask_fanout import (
                bind_ask_fanout_callback,
                deliver_ask_to_channel,
            )

            async def _ask_fanout_callback(
                *,
                session_id: str,
                user_id: str | None,
                request_id: str,
                question: str,
                options: list[str],
                expires_at_ms: int | None,
            ) -> None:
                await deliver_ask_to_channel(
                    session_id=session_id,
                    user_id=user_id,
                    question=question,
                    options=options,
                    session_mapper=session_mapper,
                    delivery_router=delivery_router,
                    default_user_id=DEFAULT_USER_ID,
                )

            bind_ask_fanout_callback(_ask_fanout_callback)
            logger.info("Channels module: ask fanout wired")
        except Exception:
            # Bind failures must not abort channels init — the desktop
            # approval path stays working, fanout / auto-approve just
            # don't fire. Logged for diagnosis.
            logger.exception(
                "Channels module: control fanout wiring failed"
            )

    async def _stop_channels(self) -> None:
        if self._registry is not None:
            await self._registry.stop_all()
        self._registry = None
        self._session_mapper = None
        logger.info("Channels module stopped")
