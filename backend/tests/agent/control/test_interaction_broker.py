"""InteractionBroker happy-path + edge cases."""

from __future__ import annotations

import asyncio

import pytest

from magi.agent.control.common import (
    InteractionBroker,
    InteractionClosedError,
    InteractionTimeoutError,
)


@pytest.mark.asyncio
async def test_resolve_delivers_response() -> None:
    broker = InteractionBroker()

    async def resolver() -> None:
        await asyncio.sleep(0.01)
        delivered = await broker.resolve(
            interaction_id="x", kind="permission", response={"ok": True}
        )
        assert delivered is True

    result, _ = await asyncio.gather(
        broker.wait(interaction_id="x", kind="permission", timeout_seconds=1.0),
        resolver(),
    )
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_timeout_raises_interaction_timeout() -> None:
    broker = InteractionBroker()
    with pytest.raises(InteractionTimeoutError) as exc:
        await broker.wait(
            interaction_id="x", kind="permission", timeout_seconds=0.05
        )
    assert exc.value.interaction_id == "x"
    assert exc.value.kind == "permission"
    assert broker.pending_count() == 0


@pytest.mark.asyncio
async def test_resolve_miss_returns_false() -> None:
    broker = InteractionBroker()
    delivered = await broker.resolve(
        interaction_id="none", kind="permission", response="x"
    )
    assert delivered is False


@pytest.mark.asyncio
async def test_close_cancels_pending_waiters() -> None:
    broker = InteractionBroker()

    async def closer() -> None:
        await asyncio.sleep(0.01)
        await broker.close(reason="shutdown")

    with pytest.raises(InteractionClosedError):
        await asyncio.gather(
            broker.wait(
                interaction_id="x", kind="permission", timeout_seconds=1.0
            ),
            closer(),
        )


@pytest.mark.asyncio
async def test_duplicate_wait_same_key_errors() -> None:
    broker = InteractionBroker()

    async def _wait() -> object:
        return await broker.wait(
            interaction_id="x", kind="permission", timeout_seconds=1.0
        )

    task = asyncio.create_task(_wait())
    await asyncio.sleep(0)  # let the task claim the key
    with pytest.raises(RuntimeError, match="already pending"):
        await broker.wait(
            interaction_id="x", kind="permission", timeout_seconds=1.0
        )
    await broker.resolve(interaction_id="x", kind="permission", response="done")
    assert await task == "done"


@pytest.mark.asyncio
async def test_different_kinds_share_id() -> None:
    broker = InteractionBroker()

    async def _wait(kind: str) -> object:
        return await broker.wait(
            interaction_id="x", kind=kind, timeout_seconds=1.0
        )

    perm_task = asyncio.create_task(_wait("permission"))
    ask_task = asyncio.create_task(_wait("ask"))
    await asyncio.sleep(0)
    await broker.resolve(interaction_id="x", kind="permission", response="p")
    await broker.resolve(interaction_id="x", kind="ask", response="a")
    assert await perm_task == "p"
    assert await ask_task == "a"
