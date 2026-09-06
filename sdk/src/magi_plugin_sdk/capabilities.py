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
    async def broadcast_event(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
        delegation_id: str,
        event: Any,
    ) -> None: ...

    async def broadcast_state(
        self,
        *,
        user_id: str,
        session_id: str,
        turn_id: str,
        delegation_id: str,
        state: Any,
        summary: Optional[dict[str, Any]] = None,
    ) -> None: ...


class DelegationArtifactPort(Protocol):
    async def register(
        self,
        *,
        session_id: str,
        turn_id: str,
        delegation_id: str,
        workspace_path: str,
    ) -> None: ...


class BackgroundPort(Protocol):
    async def suspend_waiting_user(self, task_id: str, *, reason: str = "awaiting_user_answer") -> bool: ...
    async def resume_from_wait(self, task_id: str) -> bool: ...


class MemoryQueryPort(Protocol):
    """Port for hybrid memory retrieval operations.

    The host adapter wraps the memory layer; plugins and tools call through
    this port so they never import host internals directly.
    """

    def build_query(self, **kwargs: Any) -> Any: ...
    async def query(self, request: Any) -> Any: ...
    async def get_canonical_names(self, entity_ids: set[str]) -> dict[str, str]: ...
    def project_historical_recall(
        self,
        *,
        payload: Any,
        request: Any,
        plugin_projection_service: Any = None,
        canonical_names: Any = None,
    ) -> Any: ...
    def make_conversation_turn(self, **kwargs: Any) -> Any: ...
    async def get_tool_advisory(self, *, tool_names: list[str], task_context: str) -> list[dict[str, Any]]:
        """Return advisory data without exposing a writable memory store."""
        ...


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

    async def prepare_runtime_attachment(
        self,
        *,
        session_id: str,
        turn_id: str,
        attachment: dict[str, Any],
    ) -> dict[str, Any]: ...

    async def ingest_local_file(
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
class AskOutcome:
    """Result of an ``InteractionPort.ask`` call.

    A single value object the tool maps straight onto its ``ToolResult``:

    * ``answered`` — True only when the user supplied an answer.
    * ``answer`` — the user's reply text (None unless ``answered``).
    * ``resolution`` — ``"user"`` | ``"cancelled"`` | ``"timeout"``.
    * ``timed_out`` — True iff ``resolution == "timeout"`` (carried explicitly
      so callers don't have to string-match).
    """

    answered: bool
    answer: Optional[str]
    resolution: str
    timed_out: bool


class DetachPort(Protocol):
    """Port for the detach-to-background capability.

    The host adapter wraps the DetachSignal ContextVar; tools and plugins call
    through this port so they never import host run-control internals directly.
    """

    def is_available(self) -> bool:
        """True iff there is a current detach signal (a detachable run in context)."""
        ...

    def is_requested(self) -> bool:
        """True iff a detach has already been requested in the current run."""
        ...

    def request(self, *, reason: str, requested_by: str = "llm", note: str = "") -> None:
        """Record a detach request; no-op if no signal is available."""
        ...


class InteractionPort(Protocol):
    """Port for the ask-user capability.

    The host adapter owns the entire control-protocol orchestration — opening
    the ask in the session store, emitting transcript + UI events, suspending
    the waiter on the interaction broker, and resolving on answer / cancel /
    timeout — and returns an :class:`AskOutcome`. Plugins and tools call this
    instead of importing any host control internals.

    Background suspend/resume of the *calling* task is driven by the optional
    :class:`BackgroundPort` handed in via ``background_port`` (the host
    interleaves the suspend/resume transitions into the ask flow at the exact
    points the protocol requires); pass ``None`` for a foreground call.
    """

    async def ask(
        self,
        *,
        session_id: str,
        user_id: Optional[str],
        turn_id: Optional[str],
        question: str,
        options: list[str],
        allow_free_text: bool,
        timeout_seconds: Optional[float],
        background: bool = False,
        background_task_id: Optional[str] = None,
        background_port: Optional["BackgroundPort"] = None,
        cancellation: Any = None,
    ) -> "AskOutcome": ...


@dataclass(slots=True)
class ToolCapabilities:
    """Bundle of host capability ports injected into tool execution.

    Optional services are absent when the host does not provide that capability.
    Required service admission happens before a plugin operation starts.
    """

    trace: Optional[TracePort] = None
    delegation_events: Optional[DelegationEventPort] = None
    delegation_artifacts: Optional[DelegationArtifactPort] = None
    background: Optional[BackgroundPort] = None
    chat: Optional[ChatPort] = None
    memory_query: Optional[MemoryQueryPort] = None
    image_gen: Optional[ImageGenPort] = None
    interaction: Optional[InteractionPort] = None
    detach: Optional[DetachPort] = None


__all__ = [
    "ToolCapabilities",
    "TracePort",
    "DelegationEventPort",
    "DelegationArtifactPort",
    "BackgroundPort",
    "MemoryQueryPort",
    "ChatPort",
    "ImageGenPort",
    "InteractionPort",
    "AskOutcome",
    "DetachPort",
]
