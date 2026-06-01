"""Capability ports injected into tools via ToolExecutionContext.capabilities.

Each port is a Protocol the HOST implements and the SDK/plugins depend on.
Plugins must never import host internals; they call ctx.capabilities.<port>.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol


class TracePort(Protocol):
    def get_trace_snapshot(self, *, user_id: str, session_id: str, turn_id: str) -> Optional[dict[str, Any]]: ...
    def get_turn_activity_map(self, *, user_id: str, session_id: str) -> dict[str, dict[str, Any]]: ...


class DelegationEventPort(Protocol):
    async def broadcast_event(self, *, user_id: str, session_id: str, delegation_id: str, event: Any) -> None: ...
    async def broadcast_state(self, *, user_id: str, session_id: str, delegation_id: str, state: Any, summary: Optional[dict[str, Any]] = None) -> None: ...


class BackgroundPort(Protocol):
    async def suspend_waiting_user(self, task_id: str, *, reason: str = "awaiting_user_answer") -> bool: ...
    async def resume_from_wait(self, task_id: str) -> bool: ...


class MemoryQueryPort(Protocol):
    """Port for hybrid memory retrieval operations.

    The host adapter wraps the memory layer; plugins and tools call through
    this port so they never import host internals directly.
    """

    @property
    def memory_db_path(self) -> Optional[str]: ...
    def build_query(self, **kwargs: Any) -> Any: ...
    async def query(self, request: Any) -> Any: ...
    async def get_canonical_names(self, db_path: str, entity_ids: Any) -> dict: ...
    def project_historical_recall(
        self,
        *,
        payload: Any,
        request: Any,
        plugin_manager: Any = None,
        canonical_names: Any = None,
    ) -> Any: ...
    def make_conversation_turn(self, **kwargs: Any) -> Any: ...


class ChatPort(Protocol):
    """Port for chat attachment read/ingestion operations.

    Wraps ChatReadService.get_attachment_payload and
    LocalChatAttachmentIngestionService.prepare_runtime_attachment /
    ingest_local_file. Tools call through this port so they never import
    host chat internals directly.
    """

    def get_attachment_payload(
        self,
        user_id: str,
        session_id: str,
        attachment_id: str,
    ) -> Optional[dict[str, Any]]: ...

    def prepare_runtime_attachment(
        self,
        *,
        session_id: str,
        turn_id: str,
        attachment: dict[str, Any],
    ) -> dict[str, Any]: ...

    def ingest_local_file(
        self,
        *,
        session_id: str,
        turn_id: str,
        file_path: str,
        original_name: Optional[str] = None,
        mime_type: Optional[str] = None,
    ) -> dict[str, Any]: ...


class ImageGenPort(Protocol):
    """Port for image generation adapter creation and usage span publication.

    Wraps create_image_generation_adapter and publish_llm_usage_span.
    Tools call through this port so they never import host llm internals
    directly.
    """

    def create_adapter(
        self,
        *,
        provider_id: str,
        provider_settings: Any,
        model: str,
        registry: Any,
        timeout: int,
        proxy_url: Optional[str] = None,
    ) -> Any: ...

    async def publish_usage_span(self, **kwargs: Any) -> None: ...


@dataclass(slots=True)
class ToolCapabilities:
    """Bundle of host capability ports injected into tool execution.

    Attributes default to None so partial wiring during migration is safe.
    Cluster tasks add typed ports incrementally.
    """

    trace: Optional[TracePort] = None
    delegation_events: Optional[DelegationEventPort] = None
    background: Optional[BackgroundPort] = None
    session_cache: Optional[Any] = None
    chat: Optional[ChatPort] = None
    memory_query: Optional[MemoryQueryPort] = None
    image_gen: Optional[ImageGenPort] = None
    control: Optional[Any] = None
    interaction: Optional[Any] = None
    subagent: Optional[Any] = None


__all__ = [
    "ToolCapabilities",
    "TracePort",
    "DelegationEventPort",
    "BackgroundPort",
    "MemoryQueryPort",
    "ChatPort",
    "ImageGenPort",
]
