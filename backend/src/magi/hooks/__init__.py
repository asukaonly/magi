"""Claude Code-style hooks subsystem.

Provides a decision-collecting gateway for runtime events (PreToolUse,
PreSkillUse, UserPromptSubmit, ...) that runs in parallel to the
fire-and-forget EventBus and the PermissionGateway.

Architectural distinction:

- ``magi.events.MessageBusBackend`` — fan-out observation events
  (PostToolUse, SpanCompleted, ...). Subscribers run side effects, no
  return value is collected.
- ``magi.control.permission`` — user-facing tool authorization
  (kill list, cached rules, mode policy, interactive prompts).
- ``magi.hooks`` (this package) — programmatic policy: registered handlers
  return ``HookDecision`` instances that can ``CONTINUE``, ``DENY`` or
  ``MODIFY`` the in-flight call.
"""

from __future__ import annotations

from .contracts import (
    HookContext,
    HookDecision,
    HookEventType,
    HookHandler,
    HookOutcome,
)
from .gateway import HookGateway
from .registry import HookRegistry

__all__ = [
    "HookContext",
    "HookDecision",
    "HookEventType",
    "HookGateway",
    "HookHandler",
    "HookOutcome",
    "HookRegistry",
]
