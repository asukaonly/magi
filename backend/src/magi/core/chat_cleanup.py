"""Shared outcome contract for committed chat deletion cleanup."""

from __future__ import annotations

from collections.abc import Iterable


class ChatSurfaceCleanupPendingError(RuntimeError):
    """Report a committed public deletion whose private cleanup must retry."""

    def __init__(
        self,
        message: str,
        *,
        user_id: str,
        session_id: str,
        message_ids: Iterable[str] = (),
        turn_ids: Iterable[str] = (),
    ) -> None:
        super().__init__(message)
        self.user_id = str(user_id or "").strip()
        self.session_id = str(session_id or "").strip()
        self.message_ids = tuple(
            value
            for raw_value in message_ids
            if (value := str(raw_value or "").strip())
        )
        self.turn_ids = tuple(
            value
            for raw_value in turn_ids
            if (value := str(raw_value or "").strip())
        )


__all__ = ["ChatSurfaceCleanupPendingError"]
