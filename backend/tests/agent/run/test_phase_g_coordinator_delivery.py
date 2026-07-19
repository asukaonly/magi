"""Phase G coordinator delivery integration tests."""
from __future__ import annotations

import inspect


def test_coordinator_accepts_injected_delivery_dispatcher() -> None:
    """ChatExecutionCoordinator must accept an injected delivery dispatcher
    instead of constructing channel delivery infrastructure itself."""
    from magi.chat.task_agent.coordinator import ChatExecutionCoordinator

    params = inspect.signature(ChatExecutionCoordinator.__init__).parameters
    assert "delivery_dispatcher" in params
    assert "channel_registry" not in params

    src = inspect.getsource(ChatExecutionCoordinator.__init__)
    assert "DeliveryRouter" not in src


def test_coordinator_execute_defers_final_delivery_to_postprocess() -> None:
    """Execution must not send a final response before chat persistence."""
    from magi.chat.task_agent.coordinator import ChatExecutionCoordinator

    src = inspect.getsource(ChatExecutionCoordinator.execute)
    assert "_fanout_to_origin_channels" not in src

    delivery_src = inspect.getsource(ChatExecutionCoordinator.deliver_final_chat_response)
    assert "_fanout_to_origin_channels" in delivery_src


def test_session_run_coordinator_request_retract_uses_delivery_dispatcher() -> None:
    """When retract is fired, chat must delegate channel cleanup to the
    injected delivery dispatcher."""
    import inspect
    from magi.chat.task_agent.session_run_coordinator import (
        SessionRunCoordinator,
    )

    params = inspect.signature(SessionRunCoordinator.__init__).parameters
    assert "delivery_dispatcher" in params
    assert "delivery_router" not in params
    assert "receipts_store" not in params

    src = inspect.getsource(SessionRunCoordinator.request_retract)
    assert "retract_run_deliveries" in src
    assert "fanout_retract" not in src
