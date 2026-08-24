"""Ports for resolving managed attachments at the agent runtime boundary."""

from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable


@runtime_checkable
class AttachmentResolverPort(Protocol):
    """Resolve a managed attachment payload within a user session."""

    def get_attachment_payload(
        self,
        user_id: str,
        session_id: str,
        attachment_id: str,
    ) -> dict[str, Any] | None: ...


class NullAttachmentResolver:
    """No-op resolver for runs without a chat attachment service."""

    def get_attachment_payload(
        self,
        user_id: str,
        session_id: str,
        attachment_id: str,
    ) -> dict[str, Any] | None:
        return None


class LazyAttachmentResolver:
    """Resolve through a lazily constructed chat read service."""

    def __init__(self, factory: Callable[[], Any]) -> None:
        self._factory = factory

    def get_attachment_payload(
        self,
        user_id: str,
        session_id: str,
        attachment_id: str,
    ) -> dict[str, Any] | None:
        return self._factory().get_attachment_payload(user_id, session_id, attachment_id)


__all__ = ["AttachmentResolverPort", "LazyAttachmentResolver", "NullAttachmentResolver"]
