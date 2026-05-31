"""Phase G+3: SessionRunCoordinator.request_retract reads receipts from
DeliveryReceiptsStore, not from snapshot.node_states."""

from __future__ import annotations

import asyncio

import pytest

from magi.agent.run_control import null_run_control
from magi.agent.task_agents.chat.run_store import SessionRunStore
from magi.agent.task_agents.chat.session_run_coordinator import (
    SessionRunCoordinator,
)
from magi_plugin_sdk.delivery import DeliveryReceipt


class _StubReceiptsStore:
    def __init__(self, receipts) -> None:
        self._receipts = list(receipts)
        self.list_calls: list[tuple[str, str]] = []

    async def list_receipts(self, *, session_id, run_id, revision=None):
        self.list_calls.append((session_id, run_id))
        return list(self._receipts)

    async def clear_receipts(self, **kw):
        return None

    async def save_receipts(self, **kw):
        return None


class _StubRouter:
    def __init__(self) -> None:
        self.captured: list = []

    async def fanout_retract(self, *, receipts):
        self.captured.extend(receipts)


def _build_coord_with_active_run(
    *, session_id: str, receipts_store, delivery_router,
):
    store = SessionRunStore()
    active = store.create_active_run(session_id, root_turn_id="t1", root_user_message="hi")
    store.register_active_run_control(session_id, active.run_id, null_run_control())
    coord = SessionRunCoordinator(
        run_store=store,
        delivery_router=delivery_router,
        receipts_store=receipts_store,
    )
    return coord, active


@pytest.mark.asyncio
async def test_request_retract_reads_receipts_from_store_and_calls_fanout_retract():
    receipts_in_store = [
        DeliveryReceipt(
            channel_id="chat_sse",
            external_message_id=None,
            delivered_at_ms=100,
            magi_session_id="s1",
        ),
        DeliveryReceipt(
            channel_id="telegram",
            external_message_id="tg:1",
            delivered_at_ms=101,
            magi_session_id="s1",
        ),
    ]
    store_stub = _StubReceiptsStore(receipts_in_store)
    router_stub = _StubRouter()

    coord, active = _build_coord_with_active_run(
        session_id="s1",
        receipts_store=store_stub,
        delivery_router=router_stub,
    )

    result = coord.request_retract(session_id="s1")
    assert result is True

    # Give the asyncio.create_task a chance to run.
    for _ in range(10):
        if router_stub.captured:
            break
        await asyncio.sleep(0)

    assert len(router_stub.captured) == 2
    channel_ids = {r.channel_id for r in router_stub.captured}
    assert channel_ids == {"chat_sse", "telegram"}

    # Store was queried for this active run.
    assert store_stub.list_calls == [("s1", active.run_id)]


@pytest.mark.asyncio
async def test_request_retract_with_no_receipts_is_a_noop_on_router():
    """When the store returns [], fanout_retract is not invoked."""
    store_stub = _StubReceiptsStore([])
    router_stub = _StubRouter()
    coord, _ = _build_coord_with_active_run(
        session_id="s1", receipts_store=store_stub, delivery_router=router_stub,
    )

    coord.request_retract(session_id="s1")
    for _ in range(5):
        await asyncio.sleep(0)

    assert router_stub.captured == []


def test_snapshot_walking_helpers_are_deleted():
    from magi.agent.task_agents.chat import session_run_coordinator as src_mod

    assert not hasattr(src_mod, "_extract_receipts_from_snapshot")
    assert not hasattr(src_mod, "_collect_receipts_from_snapshot")
