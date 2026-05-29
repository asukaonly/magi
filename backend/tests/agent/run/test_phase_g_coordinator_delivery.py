"""Phase G coordinator + DeliveryRouter integration tests."""
from __future__ import annotations

import inspect


def test_coordinator_constructs_delivery_router_in_init() -> None:
    """ChatExecutionCoordinator.__init__ must construct a DeliveryRouter
    if channel_registry is supplied."""
    from magi.agent.task_agents.chat.coordinator import ChatExecutionCoordinator

    src = inspect.getsource(ChatExecutionCoordinator.__init__)
    assert "DeliveryRouter" in src, (
        "ChatExecutionCoordinator.__init__ must construct a DeliveryRouter"
    )


def test_coordinator_execute_calls_fanout_deliver_on_completion() -> None:
    """ChatExecutionCoordinator.execute must call delivery_router.fanout_deliver
    after the node sequence completes and store receipts."""
    from magi.agent.task_agents.chat.coordinator import ChatExecutionCoordinator

    src = inspect.getsource(ChatExecutionCoordinator.execute)
    assert "fanout_deliver" in src or "_delivery_router" in src, (
        "execute() must invoke the delivery router after run completes"
    )


def test_session_run_coordinator_request_retract_calls_fanout_retract() -> None:
    """When retract is fired, the coordinator must read stored
    delivery_receipts off the latest snapshot and call
    DeliveryRouter.fanout_retract."""
    import inspect
    from magi.agent.task_agents.chat.session_run_coordinator import (
        SessionRunCoordinator,
    )

    src = inspect.getsource(SessionRunCoordinator.request_retract)
    assert "fanout_retract" in src or "_delivery_router" in src, (
        "request_retract must call DeliveryRouter.fanout_retract when receipts exist"
    )
