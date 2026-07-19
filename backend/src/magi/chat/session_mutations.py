"""Process-local serialization for one chat session's transcript mutations."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass(slots=True)
class _SessionLockState:
    lock: asyncio.Lock
    users: int = 0


_SESSION_LOCKS: dict[str, _SessionLockState] = {}


@asynccontextmanager
async def chat_session_mutation(session_id: str) -> AsyncIterator[None]:
    """Serialize ingress and destructive operations for one session only."""
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise ValueError("session_id must not be empty")
    state = _SESSION_LOCKS.get(normalized_session_id)
    if state is None:
        state = _SessionLockState(lock=asyncio.Lock())
        _SESSION_LOCKS[normalized_session_id] = state
    state.users += 1
    acquired = False
    try:
        await state.lock.acquire()
        acquired = True
        yield
    finally:
        if acquired:
            state.lock.release()
        state.users -= 1
        if state.users == 0 and _SESSION_LOCKS.get(normalized_session_id) is state:
            _SESSION_LOCKS.pop(normalized_session_id, None)


__all__ = ["chat_session_mutation"]
