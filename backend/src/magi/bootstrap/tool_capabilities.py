"""Composition-root assembly of tool capability ports.

Lives in bootstrap/ (outside the numbered layer stack) because it wires
adapters over services from many layers — that is composition, not domain
logic. Per-cluster adapters are added in later tasks; until then the bundle
is empty (all ports None).
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import suppress
from typing import Any

from magi_plugin_sdk.capabilities import AskOutcome, ToolCapabilities

from magi.core.logger import get_logger

logger = get_logger(__name__)

_capabilities: ToolCapabilities | None = None


class _HostTracePort:
    def get_trace_snapshot(self, *, user_id, session_id, turn_id):
        from magi.api.services import get_chat_trace_read_service
        return get_chat_trace_read_service().get_trace_snapshot(
            user_id=user_id, session_id=session_id, turn_id=turn_id
        )

    def get_turn_activity_map(self, *, user_id, session_id):
        from magi.api.services import get_chat_trace_read_service
        return get_chat_trace_read_service().get_turn_activity_map(
            user_id=user_id, session_id=session_id
        )


class _HostDelegationEventPort:
    async def broadcast_event(self, *, user_id, session_id, delegation_id, event):
        from magi.transport.code_agent_events import broadcast_delegation_event
        await broadcast_delegation_event(
            user_id=user_id,
            session_id=session_id,
            delegation_id=delegation_id,
            event=event,
        )

    async def broadcast_state(self, *, user_id, session_id, delegation_id, state, summary=None):
        from magi.transport.code_agent_events import broadcast_delegation_state
        await broadcast_delegation_state(
            user_id=user_id,
            session_id=session_id,
            delegation_id=delegation_id,
            state=state,
            summary=summary or {},
        )


class _HostBackgroundPort:
    async def suspend_waiting_user(self, task_id: str, *, reason: str = "awaiting_user_answer") -> bool:
        from magi.agent.background.provider import resolve_background_task_manager
        return await resolve_background_task_manager().suspend_waiting_user(
            task_id, reason=reason
        )

    async def resume_from_wait(self, task_id: str) -> bool:
        from magi.agent.background.provider import resolve_background_task_manager
        return await resolve_background_task_manager().resume_from_wait(task_id)


class _HostMemoryQueryPort:
    """Adapter that routes MemoryQueryPort calls to the host memory layer.

    All imports are lazy (inside methods) so this adapter never causes
    a top-level import of host memory internals from bootstrap.
    """

    _service = None

    def build_query(self, **kwargs):
        from magi.memory.hybrid_retrieval import build_query
        return build_query(**kwargs)

    def _get_service(self):
        """Return (and lazily initialise) the shared HybridRetrievalService."""
        if self._service is None:
            from magi.memory.provider import get_hybrid_retrieval_service
            self._service = get_hybrid_retrieval_service()
        return self._service

    @property
    def memory_db_path(self):
        """Delegate to HybridRetrievalService.memory_db_path.

        This is the path that memory_query_tool reads when resolving canonical
        entity names (Phase 5 canonical-names resolution).  The old code
        reached this path via HybridRetrievalService directly; after the Phase 2
        cluster-G port indirection the tool must obtain it through the adapter,
        not from the service object it no longer holds a reference to.
        """
        return self._get_service().memory_db_path

    async def query(self, request):
        return await self._get_service().query(request)

    async def get_canonical_names(self, db_path, entity_ids):
        from magi.memory.l2.entities.catalog.lookup import get_canonical_names
        return await get_canonical_names(db_path, entity_ids)

    def project_historical_recall(self, *, payload, request, plugin_manager=None, canonical_names=None):
        from magi.memory.retrieval_projection import project_historical_recall
        return project_historical_recall(
            payload=payload,
            request=request,
            plugin_manager=plugin_manager,
            canonical_names=canonical_names,
        )

    def make_conversation_turn(self, **kwargs):
        from magi.memory.hybrid_retrieval.models import ConversationTurn
        return ConversationTurn(**kwargs)

    def get_l4_store(self):
        """Return UnifiedMemoryStore.l4, or None if memory is unavailable.

        Lazy import of get_unified_memory keeps this adapter free of top-level
        host-memory imports.  The tool receives None on any failure and must
        handle that gracefully.
        """
        try:
            from magi.memory.provider import get_unified_memory
            unified_memory = get_unified_memory()
        except Exception:
            return None
        return getattr(unified_memory, "l4", None)


class _HostChatPort:
    """Adapter routing ChatPort calls to host chat layer (lazy imports)."""

    _ingestion_service = None

    def _get_ingestion(self):
        if self._ingestion_service is None:
            from magi.chat.attachment_ingestion import LocalChatAttachmentIngestionService
            self._ingestion_service = LocalChatAttachmentIngestionService()
        return self._ingestion_service

    def get_attachment_payload(self, user_id, session_id, attachment_id):
        from magi.chat.read_service import get_chat_read_service
        return get_chat_read_service().get_attachment_payload(user_id, session_id, attachment_id)

    def prepare_runtime_attachment(self, *, session_id, turn_id, attachment):
        return self._get_ingestion().prepare_runtime_attachment(
            session_id=session_id,
            turn_id=turn_id,
            attachment=attachment,
        )

    def ingest_local_file(self, *, session_id, turn_id, file_path, original_name=None, mime_type=None):
        return self._get_ingestion().ingest_local_file(
            session_id=session_id,
            turn_id=turn_id,
            file_path=file_path,
            original_name=original_name,
            mime_type=mime_type,
        )


class _HostImageGenPort:
    """Adapter routing ImageGenPort calls to host llm layer (lazy imports)."""

    def create_adapter(self, *, provider_id, provider_settings, model, registry, timeout, proxy_url=None):
        from magi.llm.image_generation.factory import create_image_generation_adapter
        return create_image_generation_adapter(
            provider_id=provider_id,
            provider_settings=provider_settings,
            model=model,
            registry=registry,
            timeout=timeout,
            proxy_url=proxy_url,
        )

    async def publish_usage_span(self, **kwargs):
        from magi.llm.usage_tracing import publish_llm_usage_span
        await publish_llm_usage_span(**kwargs)


class _HostDetachPort:
    """Adapter routing DetachPort calls to the host run-control layer (lazy imports)."""

    def _signal(self):
        from magi.control.run_control import current_detach_signal
        return current_detach_signal()

    def is_available(self) -> bool:
        return self._signal() is not None

    def is_requested(self) -> bool:
        s = self._signal()
        return bool(s and s.is_requested())

    def request(self, *, reason: str, requested_by: str = "llm", note: str = "") -> None:
        from magi.control.run_control import DetachRequested
        s = self._signal()
        if s is not None:
            s.request(DetachRequested(reason=reason, requested_by=requested_by, note=note))


class _HostInteractionPort:
    """Adapter implementing the ask-user capability over the control plane.

    Owns the *entire* ask orchestration that previously lived inline in
    ``ask_user_question_tool``: opening the ask in the control session store,
    emitting the Phase-1 transcript events (``publish_control_ask_requested`` /
    ``publish_control_ask_answered``), the background suspend/resume transitions
    (driven by the caller-supplied :class:`BackgroundPort`), the broker wait
    with cancellation race, all three resolution paths (answer / cancel /
    timeout) including the re-emit of the closed ask, and the
    ``publish_control_event`` UI notifications. Returns an :class:`AskOutcome`.

    All host imports are lazy (inside ``ask``) so this adapter never causes a
    top-level import of control internals from bootstrap.
    """

    async def ask(
        self,
        *,
        session_id: str,
        user_id: str | None,
        turn_id: str | None,
        question: str,
        options: list[str],
        allow_free_text: bool,
        timeout_seconds: float | None,
        background: bool = False,
        background_task_id: str | None = None,
        background_port: Any = None,
        cancellation: Any = None,
    ) -> AskOutcome:
        from magi.control.common import InteractionTimeoutError
        from magi.control.common.events import (
            publish_control_ask_answered,
            publish_control_ask_requested,
        )
        from magi.control.provider import (
            resolve_control_interaction_broker,
            resolve_control_session_store,
        )

        sid = session_id
        is_background = bool(background)
        bg_task_id = background_task_id or None
        manager = background_port if bg_task_id is not None else None
        timeout_value = (
            float(timeout_seconds) if timeout_seconds is not None else None
        )

        store = resolve_control_session_store()
        broker = resolve_control_interaction_broker()

        request_id = uuid.uuid4().hex
        answer_task = asyncio.create_task(
            broker.wait(
                interaction_id=request_id,
                kind="ask",
                timeout_seconds=timeout_value,
            ),
            name=f"ask-user-question-{request_id}",
        )
        cancel_task: asyncio.Task[None] | None = None
        if cancellation is not None:
            cancel_task = asyncio.create_task(
                cancellation.wait(),
                name=f"ask-user-question-cancel-{request_id}",
            )
        # Let the waiter enter the broker before the ask becomes externally visible.
        await asyncio.sleep(0)
        if cancellation is not None and await cancellation.is_cancelled():
            answer_task.cancel()
            if cancel_task is not None:
                cancel_task.cancel()
            with suppress(asyncio.CancelledError):
                await answer_task
            if cancel_task is not None:
                with suppress(asyncio.CancelledError):
                    await cancel_task
            return AskOutcome(
                answered=False,
                answer=None,
                resolution="cancelled",
                timed_out=False,
            )

        try:
            ask = await store.open_ask(
                sid,
                question=question,
                options=options,
                allow_free_text=allow_free_text,
                timeout_seconds=timeout_value,
                request_id=request_id,
            )
        except Exception:
            answer_task.cancel()
            if cancel_task is not None:
                cancel_task.cancel()
            with suppress(asyncio.CancelledError):
                await answer_task
            if cancel_task is not None:
                with suppress(asyncio.CancelledError):
                    await cancel_task
            raise

        try:
            await publish_control_ask_requested(
                session_id=sid,
                user_id=user_id,
                turn_id=turn_id,
                ask=ask,
                background=is_background,
            )
        except Exception:
            logger.debug("ask_user_question.persist_request_failed", exc_info=True)

        logger.info(
            "ask_user_question.opened",
            session_id=sid,
            request_id=ask.request_id,
            background=is_background,
            bg_task_id=bg_task_id,
        )
        if bg_task_id is not None and manager is not None:
            try:
                await manager.suspend_waiting_user(
                    bg_task_id, reason="awaiting_user_answer"
                )
            except Exception:  # pragma: no cover - defensive
                logger.debug(
                    "ask_user_question.manager_suspend_failed",
                    exc_info=True,
                )
        try:
            from magi.control.common.events import publish_control_event

            await publish_control_event(
                "control.ask.requested",
                {
                    "request_id": ask.request_id,
                    "session_id": sid,
                    "question": question,
                    "options": list(options or []),
                    "allow_free_text": allow_free_text,
                    "timeout_seconds": timeout_value,
                    "created_at_ms": int(ask.asked_at * 1000),
                    "expires_at_ms": int(ask.expires_at * 1000) if ask.expires_at else None,
                    "background": is_background,
                },
                session_id=sid,
                turn_id=turn_id,
            )
            if is_background:
                await publish_control_event(
                    "control.background.suspended",
                    {
                        "session_id": sid,
                        "request_id": ask.request_id,
                        "reason": "awaiting_user_answer",
                        "timeout_seconds": timeout_value,
                    },
                    session_id=sid,
                    turn_id=turn_id,
                )
        except Exception:  # pragma: no cover - defensive
            logger.debug("ask_user_question.event_failed", exc_info=True)

        # Lightweight external-channel egress (no-op on desktop-only sessions).
        # A channel-originated turn's question otherwise never reaches the
        # channel the user is chatting from — only the desktop gets the chips +
        # transcript card. Fire it after the ask is open and the desktop events
        # are emitted; a failure here must never block or fail the ask. The
        # inbound answer round-trips via chat ingress (a text reply
        # on the session resolves the broker), so this is egress-only.
        try:
            from magi.control.common.ask_fanout import get_ask_fanout_callback

            _channel_fanout = get_ask_fanout_callback()
            if _channel_fanout is not None:
                await _channel_fanout(
                    session_id=sid,
                    user_id=user_id,
                    request_id=ask.request_id,
                    question=question,
                    options=list(options or []),
                    expires_at_ms=(
                        int(ask.expires_at * 1000) if ask.expires_at else None
                    ),
                )
        except Exception:  # pragma: no cover - defensive
            logger.debug("ask_user_question.channel_fanout_failed", exc_info=True)

        pending_tasks: set[asyncio.Task[Any]] = {answer_task}
        if cancel_task is not None:
            pending_tasks.add(cancel_task)

        try:
            done, pending = await asyncio.wait(
                pending_tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if (
                cancel_task is not None
                and cancel_task in done
                and await cancellation.is_cancelled()
            ):
                answer_task.cancel()
                with suppress(asyncio.CancelledError):
                    await answer_task
                closed_ask = await store.close_ask(sid, answer=None, resolution="cancelled")
                if closed_ask is not None:
                    try:
                        await publish_control_ask_requested(
                            session_id=sid,
                            user_id=user_id,
                            turn_id=turn_id,
                            ask=closed_ask,
                            background=is_background,
                        )
                    except Exception:
                        logger.debug("ask_user_question.persist_cancelled_failed", exc_info=True)
                if bg_task_id is not None and manager is not None:
                    try:
                        await manager.resume_from_wait(bg_task_id)
                    except Exception:  # pragma: no cover - defensive
                        logger.debug(
                            "ask_user_question.manager_resume_failed",
                            exc_info=True,
                        )
                logger.info(
                    "ask_user_question.cancelled",
                    session_id=sid,
                    request_id=ask.request_id,
                    reason=getattr(cancellation, "reason", None),
                )
                return AskOutcome(
                    answered=False,
                    answer=None,
                    resolution="cancelled",
                    timed_out=False,
                )
            for task in pending:
                task.cancel()
            for task in pending:
                with suppress(asyncio.CancelledError):
                    await task
            answer = await answer_task
        except InteractionTimeoutError:
            closed_ask = await store.close_ask(sid, answer=None, resolution="timeout")
            if closed_ask is not None:
                try:
                    await publish_control_ask_requested(
                        session_id=sid,
                        user_id=user_id,
                        turn_id=turn_id,
                        ask=closed_ask,
                        background=is_background,
                    )
                except Exception:
                    logger.debug("ask_user_question.persist_timeout_failed", exc_info=True)
            if bg_task_id is not None and manager is not None:
                try:
                    await manager.resume_from_wait(bg_task_id)
                except Exception:  # pragma: no cover - defensive
                    logger.debug(
                        "ask_user_question.manager_resume_failed",
                        exc_info=True,
                    )
            return AskOutcome(
                answered=False,
                answer=None,
                resolution="timeout",
                timed_out=True,
            )

        answer_text = str(answer) if answer is not None else ""
        closed_ask = await store.close_ask(sid, answer=answer_text, resolution="user")
        if closed_ask is not None:
            try:
                await publish_control_ask_answered(
                    session_id=sid,
                    user_id=user_id,
                    turn_id=turn_id,
                    ask=closed_ask,
                    answer=answer_text,
                    background=is_background,
                )
            except Exception:
                logger.debug("ask_user_question.persist_response_failed", exc_info=True)
        if bg_task_id is not None and manager is not None:
            try:
                await manager.resume_from_wait(bg_task_id)
            except Exception:  # pragma: no cover - defensive
                logger.debug(
                    "ask_user_question.manager_resume_failed",
                    exc_info=True,
                )
        logger.info(
            "ask_user_question.answered",
            session_id=sid,
            request_id=ask.request_id,
            length=len(answer_text),
        )
        if is_background:
            try:
                from magi.control.common.events import publish_control_event

                await publish_control_event(
                    "control.background.resumed",
                    {
                        "session_id": sid,
                        "request_id": ask.request_id,
                    },
                    session_id=sid,
                    turn_id=turn_id,
                )
            except Exception:  # pragma: no cover - defensive
                logger.debug("ask_user_question.resume_event_failed", exc_info=True)
        return AskOutcome(
            answered=True,
            answer=answer_text,
            resolution="user",
            timed_out=False,
        )


def build_tool_capabilities() -> ToolCapabilities:
    """Return the process-wide tool-capabilities bundle (built once)."""
    global _capabilities
    if _capabilities is None:
        _capabilities = ToolCapabilities(
            trace=_HostTracePort(),
            delegation_events=_HostDelegationEventPort(),
            background=_HostBackgroundPort(),
            memory_query=_HostMemoryQueryPort(),
            chat=_HostChatPort(),
            image_gen=_HostImageGenPort(),
            interaction=_HostInteractionPort(),
            detach=_HostDetachPort(),
        )
    return _capabilities


def reset_tool_capabilities() -> None:
    """Drop the cached bundle so the next build re-assembles it (tests only)."""
    global _capabilities
    _capabilities = None
