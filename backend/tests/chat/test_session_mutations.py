"""Tests for process-local chat session mutation serialization."""

from __future__ import annotations

import asyncio

import pytest

from magi.chat import session_mutations
from magi.chat.session_mutations import chat_session_mutation


@pytest.mark.asyncio
async def test_cancelled_waiter_releases_session_lock_registration() -> None:
    """A cancelled waiter must not leave a permanently referenced lock."""

    session_id = "session-cancelled-waiter"
    holder_entered = asyncio.Event()
    release_holder = asyncio.Event()

    async def hold_session() -> None:
        async with chat_session_mutation(session_id):
            holder_entered.set()
            await release_holder.wait()

    holder = asyncio.create_task(hold_session())
    await holder_entered.wait()

    waiter = asyncio.create_task(_enter_session_once(session_id))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    release_holder.set()
    await holder

    assert session_id not in session_mutations._SESSION_LOCKS
    await _enter_session_once(session_id)
    assert session_id not in session_mutations._SESSION_LOCKS


async def _enter_session_once(session_id: str) -> None:
    async with chat_session_mutation(session_id):
        await asyncio.sleep(0)
