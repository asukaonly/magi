"""Composition-root assembly of tool capability ports.

Lives in bootstrap/ (outside the numbered layer stack) because it wires
adapters over services from many layers — that is composition, not domain
logic. Each adapter stays thin and delegates lifecycle-heavy behavior back to
the owning layer.
"""
from __future__ import annotations

from typing import Any

from magi_plugin_sdk.capabilities import AskOutcome, ToolCapabilities

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
    async def broadcast_event(
        self,
        *,
        user_id,
        session_id,
        turn_id,
        delegation_id,
        event,
    ):
        from magi.transport.code_agent_events import broadcast_delegation_event
        await broadcast_delegation_event(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            delegation_id=delegation_id,
            event=event,
        )

    async def broadcast_state(
        self,
        *,
        user_id,
        session_id,
        turn_id,
        delegation_id,
        state,
        summary=None,
    ):
        from magi.transport.code_agent_events import broadcast_delegation_state
        await broadcast_delegation_state(
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            delegation_id=delegation_id,
            state=state,
            summary=summary or {},
        )


class _HostDelegationArtifactPort:
    _registry = None

    def _get_registry(self):
        if self._registry is None:
            from magi.chat.code_delegation_artifacts import (
                ChatCodeDelegationArtifactRegistry,
            )

            self._registry = ChatCodeDelegationArtifactRegistry()
        return self._registry

    async def register(
        self,
        *,
        session_id,
        turn_id,
        delegation_id,
        workspace_path,
    ):
        await self._get_registry().register(
            session_id=session_id,
            turn_id=turn_id,
            delegation_id=delegation_id,
            workspace_path=workspace_path,
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

    async def query(self, request):
        return await self._get_service().query(request)

    async def get_canonical_names(self, entity_ids):
        from magi.memory.l2.entities.catalog.lookup import get_canonical_names
        return await get_canonical_names(self._get_service().memory_db_path, entity_ids)

    def project_historical_recall(
        self,
        *,
        payload,
        request,
        plugin_projection_service=None,
        canonical_names=None,
    ):
        from magi.memory.retrieval_projection import project_historical_recall
        return project_historical_recall(
            payload=payload,
            request=request,
            plugin_projection_service=plugin_projection_service,
            canonical_names=canonical_names,
        )

    def make_conversation_turn(self, **kwargs):
        from magi.memory.hybrid_retrieval.models import ConversationTurn
        return ConversationTurn(**kwargs)

    async def get_tool_advisory(self, *, tool_names, task_context):
        """Read advisory data while keeping memory persistence host-owned."""
        try:
            from magi.memory.provider import get_unified_memory
            unified_memory = get_unified_memory()
        except Exception:
            return []
        store = getattr(unified_memory, "l4", None)
        if store is None:
            return []
        return await store.get_tool_advisory(tool_names=tool_names, task_context=task_context)


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

    async def prepare_runtime_attachment(self, *, session_id, turn_id, attachment):
        from magi.core.chat_assets.mutations import run_chat_asset_mutation

        return await run_chat_asset_mutation(
            self._get_ingestion().prepare_runtime_attachment,
            session_id=session_id,
            turn_id=turn_id,
            attachment=attachment,
        )

    async def ingest_local_file(self, *, session_id, turn_id, file_path, original_name=None, mime_type=None):
        from magi.core.chat_assets.mutations import run_chat_asset_mutation

        return await run_chat_asset_mutation(
            self._get_ingestion().ingest_local_file,
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
    """Adapter implementing the SDK ask-user capability over the control plane."""

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
        from magi.control.ask_service import ControlAskRequest, ControlAskService

        outcome = await ControlAskService.from_runtime().ask(
            ControlAskRequest(
                session_id=session_id,
                user_id=user_id,
                turn_id=turn_id,
                question=question,
                options=options,
                allow_free_text=allow_free_text,
                timeout_seconds=timeout_seconds,
                background=background,
                background_task_id=background_task_id,
                background_port=background_port,
                cancellation=cancellation,
            )
        )
        return AskOutcome(
            answered=outcome.answered,
            answer=outcome.answer,
            resolution=outcome.resolution,
            timed_out=outcome.timed_out,
        )


def build_tool_capabilities() -> ToolCapabilities:
    """Return the process-wide tool-capabilities bundle (built once)."""
    global _capabilities
    if _capabilities is None:
        _capabilities = ToolCapabilities(
            trace=_HostTracePort(),
            delegation_events=_HostDelegationEventPort(),
            delegation_artifacts=_HostDelegationArtifactPort(),
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
