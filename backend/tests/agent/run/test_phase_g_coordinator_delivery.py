"""Phase G coordinator + DeliveryRouter integration tests."""
from __future__ import annotations

import inspect


def test_coordinator_constructs_delivery_router_in_init() -> None:
    """ChatExecutionCoordinator.__init__ must construct a DeliveryRouter
    if channel_registry is supplied."""
    from magi.chat.task_agent.coordinator import ChatExecutionCoordinator

    src = inspect.getsource(ChatExecutionCoordinator.__init__)
    assert "DeliveryRouter" in src, (
        "ChatExecutionCoordinator.__init__ must construct a DeliveryRouter"
    )


def test_coordinator_execute_calls_fanout_deliver_on_completion() -> None:
    """ChatExecutionCoordinator.execute must call delivery_router.fanout_deliver
    after the node sequence completes and store receipts."""
    from magi.chat.task_agent.coordinator import ChatExecutionCoordinator

    src = inspect.getsource(ChatExecutionCoordinator.execute)
    # Delivery was refactored into the ``_fanout_to_origin_channels`` helper,
    # which constructs targets and calls ``self._delivery_router.fanout_deliver``;
    # execute() invokes that helper after the node sequence completes.
    assert (
        "fanout_deliver" in src
        or "_delivery_router" in src
        or "_fanout_to_origin_channels" in src
    ), "execute() must invoke the delivery router after run completes"


def test_session_run_coordinator_request_retract_calls_fanout_retract() -> None:
    """When retract is fired, the coordinator must read receipts from the
    DeliveryReceiptsStore (Phase G+3 — no longer the snapshot) and call
    DeliveryRouter.fanout_retract."""
    import inspect
    from magi.chat.task_agent.session_run_coordinator import (
        SessionRunCoordinator,
    )

    src = inspect.getsource(SessionRunCoordinator.request_retract)
    assert "fanout_retract" in src or "_delivery_router" in src, (
        "request_retract must call DeliveryRouter.fanout_retract when receipts exist"
    )
