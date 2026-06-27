"""Phase G+3: SessionRunCoordinator delegates delivered-message retract."""

from __future__ import annotations

import asyncio

import pytest

from magi.agent.run_control import null_run_control
from magi.chat.task_agent.run_store import SessionRunStore
from magi.chat.task_agent.session_run_coordinator import (
    SessionRunCoordinator,
)
class _StubDeliveryDispatcher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def retract_run_deliveries(self, *, session_id: str, run_id: str) -> None:
        self.calls.append((session_id, run_id))


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
async def test_request_retract_delegates_run_delivery_cleanup():
    dispatcher = _StubDeliveryDispatcher()

    coord, active = _build_coord_with_active_run(
        session_id="s1",
        delivery_dispatcher=dispatcher,
    )

    result = coord.request_retract(session_id="s1")
    assert result is True

    # Give the asyncio.create_task a chance to run.
    for _ in range(10):
        if dispatcher.calls:
            break
        await asyncio.sleep(0)

    assert dispatcher.calls == [("s1", active.run_id)]


@pytest.mark.asyncio
async def test_request_retract_with_no_dispatcher_only_sets_control_signal():
    coord, _ = _build_coord_with_active_run(
        session_id="s1", delivery_dispatcher=None,
    )

    result = coord.request_retract(session_id="s1")
    for _ in range(5):
        await asyncio.sleep(0)

    assert result is True


def test_snapshot_walking_helpers_are_deleted():
    from magi.chat.task_agent import session_run_coordinator as src_mod

    assert not hasattr(src_mod, "_extract_receipts_from_snapshot")
    assert not hasattr(src_mod, "_collect_receipts_from_snapshot")
