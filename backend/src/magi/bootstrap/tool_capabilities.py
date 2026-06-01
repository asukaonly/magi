"""Composition-root assembly of tool capability ports.

Lives in bootstrap/ (outside the numbered layer stack) because it wires
adapters over services from many layers — that is composition, not domain
logic. Per-cluster adapters are added in later tasks; until then the bundle
is empty (all ports None).
"""
from __future__ import annotations

from magi_plugin_sdk.capabilities import ToolCapabilities

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
        )
    return _capabilities


def reset_tool_capabilities() -> None:
    """Drop the cached bundle so the next build re-assembles it (tests only)."""
    global _capabilities
    _capabilities = None
