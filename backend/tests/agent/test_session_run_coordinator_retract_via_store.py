"""Phase G+3: SessionRunCoordinator delegates delivered-message retract."""

from __future__ import annotations

import asyncio

import pytest

from magi.control.run_control import null_run_control
from magi.chat.task_agent.run_store import SessionRunStore
from magi.chat.task_agent.session_run_coordinator import (
    SessionRunCoordinator,
)
class _StubDeliveryDispatcher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.completed = asyncio.Event()

    async def retract_run_deliveries(self, *, session_id: str, run_id: str) -> None:
        self.calls.append((session_id, run_id))
        self.completed.set()


def _build_coord_with_active_run(
    *, session_id: str, delivery_dispatcher,
):
    store = SessionRunStore()
    active = store.create_active_run(session_id, root_turn_id="t1", root_user_message="hi")
    store.register_active_run_control(session_id, active.run_id, null_run_control())
    coord = SessionRunCoordinator(
        run_store=store,
        delivery_dispatcher=delivery_dispatcher,
    )
    return coord, active


@pytest.mark.asyncio
@pytest.mark.parametrize("with_dispatcher", [False, True])
async def test_request_retract_signals_control_and_cleans_delivered_messages(with_dispatcher):
    dispatcher = _StubDeliveryDispatcher()

    coord, active = _build_coord_with_active_run(
        session_id="s1",
        delivery_dispatcher=dispatcher if with_dispatcher else None,
    )

    from magi.control.run_control import RetractRequested

    payload = RetractRequested(reason="user_retract", note="withdraw answer")
    control = coord._run_store.get_active_run_control("s1", active.run_id)
    assert control is not None
    assert not control.retract_signal.is_requested()
    assert coord.request_retract(session_id="s1", payload=payload) is True
    assert control.retract_signal.is_requested()
    assert control.retract_signal.payload == payload
    if with_dispatcher:
        await asyncio.wait_for(dispatcher.completed.wait(), timeout=1)
        assert dispatcher.calls == [("s1", active.run_id)]
    else:
        await asyncio.sleep(0)
        assert dispatcher.calls == []
