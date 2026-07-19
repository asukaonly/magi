"""Broadcasters for code_agent delegation events and state transitions.

Writes ``RuntimeNotificationRecord`` entries on two channels that the Rust
event bridge picks up and forwards to the Tauri front-end:

* ``code_agent_delegation_event`` — one record per ``RunEvent``. Rate-limited
  at one push per 100 ms per ``delegation_id`` so a chatty adapter doesn't
  flood the IPC bus.
* ``code_agent_delegation_state`` — one record per lifecycle transition
  (``started`` / ``finished`` / ``failed`` / ``cancelled``). Never rate-limited
  because the front-end uses these to set the card's overall state.
"""
from __future__ import annotations

import json
import time
from typing import Any, Literal

from ..core.logger import get_logger
from ..runtime_trace import RuntimeNotificationRecord
from ..runtime_trace.provider import resolve_runtime_trace_store
from ..tools.code_agent.contracts import RunEvent

logger = get_logger(__name__)

DelegationLifecycle = Literal["started", "running", "finished", "failed", "cancelled"]

_RATE_LIMIT_MS = 100
_LAST_EMIT_MS: dict[str, int] = {}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _allow_event_emit(delegation_id: str) -> bool:
    now = _now_ms()
    last = _LAST_EMIT_MS.get(delegation_id, 0)
    if now - last < _RATE_LIMIT_MS:
        return False
    _LAST_EMIT_MS[delegation_id] = now
    return True


def _clear_rate_limit(delegation_id: str) -> None:
    _LAST_EMIT_MS.pop(delegation_id, None)


async def broadcast_delegation_event(
    *,
    user_id: str,
    session_id: str,
    turn_id: str,
    delegation_id: str,
    event: RunEvent,
) -> None:
    """Push one ``RunEvent`` for live UI updates. Rate-limited per delegation."""
    user = (user_id or "").strip()
    sid = (session_id or "").strip()
    tid = (turn_id or "").strip()
    did = (delegation_id or "").strip()
    if not user or not sid or not tid or not did:
        return
    if not _allow_event_emit(did):
        return
    payload_data: dict[str, Any] = {
        "user_id": user,
        "session_id": sid,
        "turn_id": tid,
        "delegation_id": did,
        "event": event.model_dump(),
    }
    try:
        store = resolve_runtime_trace_store()
        await store.append_notification(RuntimeNotificationRecord(
            notification_id=0,
            channel="code_agent_delegation_event",
            user_id=user,
            session_id=sid,
            payload_json=json.dumps(payload_data, default=str),
        ))
    except Exception as exc:
        logger.debug("Failed to broadcast delegation event", error=str(exc))


async def broadcast_delegation_state(
    *,
    user_id: str,
    session_id: str,
    turn_id: str,
    delegation_id: str,
    state: DelegationLifecycle,
    summary: dict[str, Any] | None = None,
) -> None:
    """Push a lifecycle transition. Never rate-limited."""
    user = (user_id or "").strip()
    sid = (session_id or "").strip()
    tid = (turn_id or "").strip()
    did = (delegation_id or "").strip()
    if not user or not sid or not tid or not did:
        return
    if state in ("finished", "failed", "cancelled"):
        _clear_rate_limit(did)
    payload_data: dict[str, Any] = {
        "user_id": user,
        "session_id": sid,
        "turn_id": tid,
        "delegation_id": did,
        "state": state,
        "summary": summary or {},
    }
    try:
        store = resolve_runtime_trace_store()
        await store.append_notification(RuntimeNotificationRecord(
            notification_id=0,
            channel="code_agent_delegation_state",
            user_id=user,
            session_id=sid,
            payload_json=json.dumps(payload_data, default=str),
        ))
    except Exception as exc:
        logger.debug("Failed to broadcast delegation state", error=str(exc))


__all__ = ["broadcast_delegation_event", "broadcast_delegation_state"]
