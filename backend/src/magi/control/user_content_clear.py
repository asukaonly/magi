"""One full-clear boundary for transient control-plane user content."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from .common.interaction_broker import InteractionBroker
from .permission.brokered_prompter import PendingPermissionRegistry
from .session_store import ControlSessionStore


class ControlUserContentClearCoordinator:
    """Seal and clear every transient control-plane user-content owner."""

    def __init__(
        self,
        *,
        session_store: ControlSessionStore,
        pending_permissions: PendingPermissionRegistry,
        interaction_broker: InteractionBroker,
    ) -> None:
        self._session_store = session_store
        self._pending_permissions = pending_permissions
        self._interaction_broker = interaction_broker
        self._transcript_subscriber: Any | None = None

    def bind_transcript_subscriber(self, subscriber: Any | None) -> None:
        """Bind the chat-owned projection boundary after chat initializes."""
        if subscriber is not None and not callable(
            getattr(subscriber, "user_content_clear_boundary", None)
        ):
            raise TypeError("control transcript subscriber must expose a clear boundary")
        self._transcript_subscriber = subscriber

    @property
    def transcript_subscriber(self) -> Any | None:
        return self._transcript_subscriber

    @asynccontextmanager
    async def user_content_clear_boundary(self) -> AsyncIterator[None]:
        """Clear state, reject old waiters, and hold all writers until exit.

        Admission and release order are deliberate. Transcript projection is
        sealed first so control operations draining behind it cannot recreate
        chat rows. It is reopened first on exit while the state stores remain
        sealed, so the first post-clear control event cannot be dropped.
        """
        subscriber = self._transcript_subscriber
        if subscriber is None:
            raise RuntimeError("control transcript subscriber is not initialized")

        transcript_boundary = subscriber.user_content_clear_boundary()
        broker_boundary = self._interaction_broker.user_content_clear_boundary()
        permission_boundary = self._pending_permissions.user_content_clear_boundary()
        session_boundary = self._session_store.user_content_clear_boundary()
        entered: set[Any] = set()
        body_failed = False
        try:
            await transcript_boundary.__aenter__()
            entered.add(transcript_boundary)
            await broker_boundary.__aenter__()
            entered.add(broker_boundary)
            await permission_boundary.__aenter__()
            entered.add(permission_boundary)
            await session_boundary.__aenter__()
            entered.add(session_boundary)
            yield
        except BaseException:
            body_failed = True
            raise
        finally:
            cleanup_error: BaseException | None = None
            for boundary in (
                transcript_boundary,
                session_boundary,
                permission_boundary,
                broker_boundary,
            ):
                if boundary not in entered:
                    continue
                try:
                    await boundary.__aexit__(None, None, None)
                except BaseException as exc:  # pragma: no cover - defensive
                    if cleanup_error is None:
                        cleanup_error = exc
            if cleanup_error is not None and not body_failed:
                raise cleanup_error


__all__ = ["ControlUserContentClearCoordinator"]
