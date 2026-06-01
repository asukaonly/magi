"""Convenience helpers for emitting hooks from anywhere in the runtime.

Centralizes the "resolve gateway -> build context -> dispatch" boilerplate so
callers in tool execution, skill execution, chat ingress, etc. stay tidy.

Resolution is best-effort: if the gateway hasn't been initialized (tests,
isolated unit modules) we return a passthrough CONTINUE decision so the
caller never has to special-case "hooks disabled".
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

from .contracts import HookContext, HookDecision, HookEventType

logger = logging.getLogger(__name__)


def _resolve_gateway() -> Optional[Any]:
    try:
        from ..core.container import get_container

        gateway = get_container().hook_gateway()
    except Exception:
        return None
    if gateway is None or type(gateway).__name__ == "object":
        return None
    return gateway


async def dispatch_hook(
    event_type: HookEventType,
    *,
    session_id: Optional[str] = None,
    turn_id: Optional[str] = None,
    user_id: Optional[str] = None,
    workspace: Optional[str] = None,
    tool_name: Optional[str] = None,
    arguments: Optional[Mapping[str, Any]] = None,
    skill_name: Optional[str] = None,
    user_message: Optional[str] = None,
    matcher_key: Optional[str] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> HookDecision:
    """Build a HookContext and run the gateway. Returns CONTINUE when no gateway."""
    gateway = _resolve_gateway()
    if gateway is None:
        return HookDecision.cont()
    if matcher_key is None:
        matcher_key = tool_name or skill_name or event_type.value
    ctx = HookContext(
        event_type=event_type,
        session_id=session_id,
        turn_id=turn_id,
        user_id=user_id,
        workspace=workspace,
        tool_name=tool_name,
        arguments=arguments,
        skill_name=skill_name,
        user_message=user_message,
        matcher_key=matcher_key,
        extra=dict(extra or {}),
    )
    try:
        return await gateway.dispatch(ctx)
    except Exception:
        logger.exception("hook dispatch crashed event=%s", event_type.value)
        return HookDecision.cont()


__all__ = ["dispatch_hook"]
