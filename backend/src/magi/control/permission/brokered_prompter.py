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
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from magi.core.operation_barrier import AsyncOperationBarrier
from magi.core.logger import get_logger

from ..common.interaction_broker import InteractionBroker, InteractionTimeoutError
from .contracts import (
    PermissionRequest,
    PermissionScope,
)
from .gateway import UserPromptResponse

__all__ = [
    "BrokeredPermissionPrompter",
    "PendingPermissionClearedError",
    "PendingPermissionRegistry",
]

logger = get_logger(__name__)


class PendingPermissionClearedError(RuntimeError):
    """Raised when a permission request crosses a full data clear."""


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
        self._clear_barrier = AsyncOperationBarrier()
        self._clear_generation = 0
        self._clear_request_count = 0

    @asynccontextmanager
    async def user_content_clear_boundary(self) -> AsyncIterator[None]:
        """Clear pending prompts and reject registrations until clear ends."""
        self._clear_request_count += 1
        self._clear_generation += 1
        try:
            async with self._clear_barrier.exclusive():
                async with self._lock:
                    self._pending.clear()
                yield
        finally:
            self._clear_request_count -= 1

    async def add(self, request: PermissionRequest) -> int:
        generation = self._clear_generation
        if self._clear_request_count > 0:
            raise PendingPermissionClearedError(
                "pending permissions are being cleared"
            )
        async with self._clear_barrier.operation():
            if (
                self._clear_request_count > 0
                or generation != self._clear_generation
            ):
                raise PendingPermissionClearedError(
                    "permission registration crossed a full data clear"
                )
            async with self._lock:
                self._pending[request.request_id] = request
            return generation

    @asynccontextmanager
    async def request_operation(
        self,
        request: PermissionRequest,
        *,
        expected_generation: int,
    ) -> AsyncIterator[None]:
        """Keep one request's pre-wait notification phase inside its generation."""
        if self._clear_request_count > 0:
            raise PendingPermissionClearedError(
                "pending permissions are being cleared"
            )
        async with self._clear_barrier.operation():
            if (
                self._clear_request_count > 0
                or expected_generation != self._clear_generation
            ):
                raise PendingPermissionClearedError(
                    "permission request crossed a full data clear"
                )
            async with self._lock:
                if self._pending.get(request.request_id) is not request:
                    raise PendingPermissionClearedError(
                        "permission request is no longer pending"
                    )
            yield

    async def remove(
        self,
        request_id: str,
        *,
        expected: PermissionRequest | None = None,
    ) -> PermissionRequest | None:
        generation = self._clear_generation
        if self._clear_request_count > 0:
            return None
        async with self._clear_barrier.operation():
            if (
                self._clear_request_count > 0
                or generation != self._clear_generation
            ):
                return None
            async with self._lock:
                current = self._pending.get(request_id)
                if current is None or (expected is not None and current is not expected):
                    return None
                return self._pending.pop(request_id)

    def snapshot(
        self, *, session_id: str | None = None
    ) -> list[PermissionRequest]:
        """Return a stable copy of the currently pending prompts.

        When ``session_id`` is given, filters to requests belonging to
        that session. ``None`` means session-less (orphan) requests
        only; pass a sentinel string like ``"*"`` externally if you
        want unfiltered snapshots.
        """
        if self._clear_request_count > 0:
            return []
        items = list(self._pending.values())
        if session_id == "*":
            return items
        return [req for req in items if req.session_id == session_id]

    def get(self, request_id: str) -> PermissionRequest | None:
        if self._clear_request_count > 0:
            return None
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
        if self._clear_request_count > 0:
            return None
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
        fanout_callback: Any | None = None,
    ) -> None:
        self._broker = broker
        self._registry = registry
        self._notify = notify_callback
        #: Async callable ``(PermissionRequest) -> Awaitable[None]`` that
        #: fans out the prompt to every channel that opted into control
        #: requests (Phase H+2). Optional: when None, only the
        #: ``notify_callback`` path (desktop / runtime_notifications)
        #: fires, which is the pre-H+2 behavior. Late-binding via
        #: :meth:`bind_fanout_callback` lets a later-initializing
        #: bootstrap module (ChannelsModule, which needs the channel
        #: registry that doesn't exist at ControlPlane init time) wire
        #: this in without a hard dependency cycle.
        self._fanout = fanout_callback

    def bind_fanout_callback(self, fanout_callback: Any) -> None:
        """Late-bind the fanout callback after construction.

        Used by ChannelsModule.init() which runs after ControlPlaneModule
        (so the prompter exists) and after the channel registry is built
        (so we can enumerate opted-in channels). Idempotent — overwrites
        any prior binding. Pass ``None`` to disable fanout (used by tests
        that exercise the notify-only path)."""
        self._fanout = fanout_callback

    async def __call__(
        self,
        request: PermissionRequest,
        *,
        timeout_seconds: float,
    ) -> UserPromptResponse:
        self._apply_timeout(request, timeout_seconds)
        broker_generation = self._broker.user_content_generation()
        registry_generation = await self._registry.add(request)
        try:
            async with self._registry.request_operation(
                request,
                expected_generation=registry_generation,
            ):
                await self._notify_permission_requested(request)
                await self._fanout_permission_request(request)
            response = await self._wait_for_permission_response(
                request,
                timeout_seconds,
                expected_generation=broker_generation,
            )
        finally:
            await self._clear_permission_request(request)

        return _coerce_response(response)

    @staticmethod
    def _apply_timeout(request: PermissionRequest, timeout_seconds: float) -> None:
        if request.timeout_seconds is None:
            request.timeout_seconds = float(timeout_seconds)
        if request.expires_at is None and timeout_seconds > 0:
            request.expires_at = request.created_at + float(timeout_seconds)

    async def _notify_permission_requested(self, request: PermissionRequest) -> None:
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

    async def _fanout_permission_request(self, request: PermissionRequest) -> None:
        if self._fanout is not None:
            try:
                await _maybe_await(self._fanout(request))
            except Exception:
                # Same best-effort policy as notify_callback: a fanout
                # failure must not block the broker.wait — the desktop
                # path still works, and a partial fanout is better than
                # a stuck run.
                logger.warning(
                    "permission_prompter.fanout_failed",
                    request_id=request.request_id,
                    exc_info=True,
                )

    async def _wait_for_permission_response(
        self,
        request: PermissionRequest,
        timeout_seconds: float,
        *,
        expected_generation: int,
    ) -> Any:
        try:
            return await self._broker.wait(
                interaction_id=request.request_id,
                kind="permission",
                timeout_seconds=timeout_seconds,
                expected_generation=expected_generation,
            )
        except InteractionTimeoutError:
            logger.info(
                "permission_prompter.timeout",
                request_id=request.request_id,
                tool_name=request.tool_name,
            )
            raise

    async def _clear_permission_request(self, request: PermissionRequest) -> None:
        removed = await self._registry.remove(
            request.request_id,
            expected=request,
        )
        if removed is None:
            return
        # Phase H+2: push a "resolved" event so connected clients
        # (desktop modal, other channels' inline prompts) can immediately
        # clear their UI instead of waiting for poll-based reconciliation.
        if self._notify is None:
            return
        try:
            await _maybe_await(
                self._notify(
                    "control.permission.resolved",
                    {
                        "request_id": request.request_id,
                        "short_id": request.short_id,
                        "session_id": request.session_id,
                        "tool_name": request.tool_name,
                    },
                )
            )
        except Exception:
            logger.warning(
                "permission_prompter.notify_resolved_failed",
                request_id=request.request_id,
                exc_info=True,
            )


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
