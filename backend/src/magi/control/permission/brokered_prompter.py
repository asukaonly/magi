"""Broker-backed :class:`PermissionPrompter`.

This prompter is the production implementation used by the gateway
once the control plane is bootstrapped. It does two things:

1. Records the :class:`PermissionRequest` in an in-memory registry
   keyed by ``request_id`` so that frontends can poll the list via
   ``GET /api/control/sessions/{sid}/permissions`` and discover the
   pending prompt to render.
2. Awaits :func:`InteractionBroker.wait` until either the frontend
   responds (via ``POST /api/control/permission/{id}/respond``) or
   the timeout fires. In either case the registry entry is cleared.

The registry is intentionally **process-local**: permission prompts
are transient (seconds, not minutes) and replaying them across
processes would be a security hazard rather than a feature. If the
backend crashes while awaiting a prompt, the agent step fails and
the user can retry — which is exactly what we want.
"""

from __future__ import annotations

import asyncio
from typing import Any

from magi.core.logger import get_logger

from ..common.interaction_broker import InteractionBroker, InteractionTimeoutError
from .contracts import (
    PermissionRequest,
    PermissionScope,
)
from .gateway import UserPromptResponse

__all__ = [
    "BrokeredPermissionPrompter",
    "PendingPermissionRegistry",
]

logger = get_logger(__name__)


class PendingPermissionRegistry:
    """Process-local registry of currently awaiting permission prompts.

    Thread-safety: the only writers are the prompter (single asyncio
    task per gate() call) and the gateway's timeout resolution. We
    rely on asyncio's single-threaded scheduling and a small
    :class:`asyncio.Lock` for compound read-modify operations.
    """

    def __init__(self) -> None:
        self._pending: dict[str, PermissionRequest] = {}
        self._lock = asyncio.Lock()

    async def add(self, request: PermissionRequest) -> None:
        async with self._lock:
            self._pending[request.request_id] = request

    async def remove(self, request_id: str) -> PermissionRequest | None:
        async with self._lock:
            return self._pending.pop(request_id, None)

    def snapshot(
        self, *, session_id: str | None = None
    ) -> list[PermissionRequest]:
        """Return a stable copy of the currently pending prompts.

        When ``session_id`` is given, filters to requests belonging to
        that session. ``None`` means session-less (orphan) requests
        only; pass a sentinel string like ``"*"`` externally if you
        want unfiltered snapshots.
        """
        items = list(self._pending.values())
        if session_id == "*":
            return items
        return [req for req in items if req.session_id == session_id]

    def get(self, request_id: str) -> PermissionRequest | None:
        return self._pending.get(request_id)

    def find_by_short_id(
        self, short_id: str, *, session_id: str | None = None
    ) -> PermissionRequest | None:
        """Look up a pending request by its human-typeable short_id.

        Used by the channel slash-command parser to resolve
        ``/approve <short_id>`` / ``/deny <short_id>`` back to a
        full :class:`PermissionRequest`. The search is scoped to a
        single session — same session has at most a handful of
        pending requests, so the 24-bit short_id space is
        collision-resistant within scope.

        Returns ``None`` if no match. Returns ``None`` and logs a
        warning if MULTIPLE matches in the same session (shouldn't
        happen in practice, but if it does, the slash-command
        handler will tell the user to respond on desktop instead of
        guessing). Cross-session collisions are tolerated and
        invisible — the caller must always pass the originating
        session_id.

        ``short_id`` is matched case-insensitively to match the
        derivation convention (``derive_short_id`` lowercases) and
        to be forgiving of users who type uppercase.
        """
        needle = short_id.strip().lower()
        if not needle:
            return None
        matches = [
            req
            for req in self._pending.values()
            if req.session_id == session_id and req.short_id == needle
        ]
        if not matches:
            return None
        if len(matches) > 1:
            logger.warning(
                "PendingPermissionRegistry.find_by_short_id ambiguous: "
                "short_id=%s session_id=%s matched %d pending requests",
                needle,
                session_id,
                len(matches),
            )
            return None
        return matches[0]


class BrokeredPermissionPrompter:
    """Prompter that bridges the gateway to the :class:`InteractionBroker`.

    Optionally publishes a ``control.permission.requested`` hook via
    ``notify_callback`` for transports that want to push an event to
    the UI instead of relying on polling. The callback is invoked
    best-effort: exceptions are logged but do not abort the prompt.
    """

    def __init__(
        self,
        *,
        broker: InteractionBroker,
        registry: PendingPermissionRegistry,
        notify_callback: Any | None = None,
    ) -> None:
        self._broker = broker
        self._registry = registry
        self._notify = notify_callback

    async def __call__(
        self,
        request: PermissionRequest,
        *,
        timeout_seconds: float,
    ) -> UserPromptResponse:
        if request.timeout_seconds is None:
            request.timeout_seconds = float(timeout_seconds)
        if request.expires_at is None and timeout_seconds > 0:
            request.expires_at = request.created_at + float(timeout_seconds)
        await self._registry.add(request)
        if self._notify is not None:
            try:
                await _maybe_await(
                    self._notify("control.permission.requested", request.to_dict())
                )
            except Exception:
                logger.warning(
                    "permission_prompter.notify_failed",
                    request_id=request.request_id,
                    exc_info=True,
                )
        try:
            response = await self._broker.wait(
                interaction_id=request.request_id,
                kind="permission",
                timeout_seconds=timeout_seconds,
            )
        except InteractionTimeoutError:
            logger.info(
                "permission_prompter.timeout",
                request_id=request.request_id,
                tool_name=request.tool_name,
            )
            raise
        finally:
            await self._registry.remove(request.request_id)

        return _coerce_response(response)


def _coerce_response(raw: Any) -> UserPromptResponse:
    """Normalise the broker response into :class:`UserPromptResponse`.

    The REST endpoint posts a dict shaped like::

        {"outcome": "allowed"|"denied", "scope": "...",
         "pattern": "...", "reason": "..."}

    but internal callers may already hand in a ``UserPromptResponse``
    (handy for tests). We accept both.
    """
    if isinstance(raw, UserPromptResponse):
        return raw
    if not isinstance(raw, dict):
        raise ValueError(
            f"Permission prompt returned unexpected payload type: {type(raw)!r}"
        )
    allow = str(raw.get("outcome", "denied")).lower() == "allowed"
    scope_raw = raw.get("scope", PermissionScope.ONE_SHOT.value)
    try:
        scope = PermissionScope(scope_raw)
    except ValueError:
        logger.warning(
            "permission_prompter.invalid_scope",
            scope=scope_raw,
            fallback=PermissionScope.ONE_SHOT.value,
        )
        scope = PermissionScope.ONE_SHOT
    matcher = raw.get("matcher")
    pattern = raw.get("pattern")
    if matcher is None and pattern:
        matcher = {"pattern": pattern}
    return UserPromptResponse(
        allow=allow,
        scope=scope,
        matcher=matcher,
        note=raw.get("reason") or raw.get("note"),
    )


async def _maybe_await(result: Any) -> None:
    if asyncio.iscoroutine(result):
        await result
