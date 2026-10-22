"""Idempotency lookup helpers for L1 event retrieval."""

from __future__ import annotations

from typing import Optional, cast

from .common import L1EventQueryHostProtocol


class L1EventIdempotencyMixin:
    """Resolve existing event IDs by event ID or business idempotency tuple."""

    async def find_event_id_by_idempotency(
        self,
        *,
        source: str,
        event_type: str,
        idempotency_key: str | None,
    ) -> Optional[str]:
        """Find an existing event id by business idempotency tuple."""
        host = cast(L1EventQueryHostProtocol, self)
        normalized_key = str(idempotency_key or "").strip()
        if not normalized_key:
            return None
        await host.initialize()
        return await host.event_repository.find_by_idempotency(
            source=source, event_type=event_type, idempotency_key=normalized_key,
        )


__all__ = ["L1EventIdempotencyMixin"]
