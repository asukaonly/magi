"""Capability ports for the agent run engine.

These ports let the run engine resolve runtime dependencies without
importing higher layers. They are deliberately leaf modules: only
stdlib / typing imports are allowed here so any engine module
(``message_utils``, ``attachment_context``, the orchestrator) can import
the port without creating an import cycle.

``AttachmentResolverPort`` severs the one chat coupling in the engine:
attachment-payload resolution. Chat injects a chat-backed resolver (see
``LazyAttachmentResolver``); non-chat callers inject
``NullAttachmentResolver`` and resolve no managed payloads.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable


@runtime_checkable
class AttachmentResolverPort(Protocol):
    """Resolve a managed attachment payload by id within a session.

    This is the exact, minimal surface the engine calls on the chat read
    service today (``message_utils._build_latest_user_message_content`` and
    ``attachment_context.resolve_effective_turn_attachments``). The chat
    read service's ``get_attachment_payload`` already matches this signature,
    so the chat-backed adapter is thin.
    """

    def get_attachment_payload(
        self,
        user_id: str,
        session_id: str,
        attachment_id: str,
    ) -> dict[str, Any] | None:
        """Return the stored attachment payload, or ``None`` if not found."""
        ...


class NullAttachmentResolver:
    """No-op resolver: resolves no managed attachment payloads.

    Injected by non-chat factories (workers, sub-agents, batch runs) where
    there is no chat read service. Always returns ``None`` so callers fall
    back to whatever attachment fields they already hold, without touching
    chat.
    """

    def get_attachment_payload(
        self,
        user_id: str,
        session_id: str,
        attachment_id: str,
    ) -> dict[str, Any] | None:
        return None


class LazyAttachmentResolver:
    """Resolver that delegates to a read service fetched lazily per call.

    Preserves the engine's current lazy-singleton semantics: the read
    service is fetched via ``factory`` only at resolve time, not at
    construction. ``factory`` is the chat read-service factory
    (``get_chat_read_service``), so this adapter is source-agnostic and
    imports nothing from chat.
    """

    def __init__(self, factory: Callable[[], Any]) -> None:
        self._factory = factory

    def get_attachment_payload(
        self,
        user_id: str,
        session_id: str,
        attachment_id: str,
    ) -> dict[str, Any] | None:
        return self._factory().get_attachment_payload(user_id, session_id, attachment_id)


__all__ = [
    "AttachmentResolverPort",
    "NullAttachmentResolver",
    "LazyAttachmentResolver",
]
