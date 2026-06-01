"""Backward-compatibility shim for cancellation primitives.

The cancellation protocol moved to :mod:`magi.control.cancel` as part of
the control-plane extraction (Phase 3). Cancellation is a control-plane
primitive; ``agent/*`` modules import it from here, and ``agent`` is a
downward (allowed) dependency of ``control``.

All names below are re-exported from :mod:`magi.control.cancel` so that
existing ``magi.agent.cancel`` imports keep working unchanged. Identity
is preserved: ``magi.agent.cancel.CancelToken is
magi.control.cancel.CancelToken``.
"""

from __future__ import annotations

from magi.control.cancel import *  # noqa: F401,F403
from magi.control.cancel import (
    CancelReason,
    CancelToken,
    EventCancelToken,
    NullCancelToken,
    SessionRunCancelToken,
    null_cancel_token,
)

__all__ = [
    "CancelToken",
    "CancelReason",
    "NullCancelToken",
    "EventCancelToken",
    "SessionRunCancelToken",
    "null_cancel_token",
]
