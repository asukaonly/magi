"""Phase 4: TaskOrchestrator publishes SpanCompleted(node_type='task_lifecycle')
on terminal transitions; TASK_STARTED is dropped."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock

from magi.events.events import Event, EventTypes
from magi.events.domain_payloads import SpanCompleted
from magi.agent.task_orchestrator import TaskOrchestrator


def _build_orchestrator(bus):
    """Build orchestrator with bus injected via _event_bus_cached property."""
    orch = TaskOrchestrator(
        runtime_key="test",
        tool_registry=MagicMock(),
        plan_subtasks=AsyncMock(),
        aggregate_orchestration=AsyncMock(),
        register_user_message=MagicMock(),
        parent_task_agent_type="chat",
    )
    orch._event_bus_cached = bus
    return orch


@pytest.mark.asyncio
async def test_helper_publishes_span_completed_on_completion():
    """The orchestrator's lifecycle publish helper emits SpanCompleted."""
    bus = MagicMock()
    bus.publish = AsyncMock(return_value=True)
    orch = _build_orchestrator(bus)

    state = MagicMock()
    state.orchestration_id = "orch-1"
    state.planner = "chat"
    state.created_at = 1.0
    state.updated_at = 2.5
    state.user_id = "u"
    state.session_id = "s"
    state.turn_id = "t"
    state.final_response = "all good"

    await orch._publish_task_lifecycle(
        state=state,
        status="ok",
        summary="done",
        error=None,
    )

    bus.publish.assert_awaited_once()
    event: Event = bus.publish.await_args.args[0]
    assert event.type == EventTypes.SPAN_COMPLETED
    payload: SpanCompleted = event.data
    assert isinstance(payload, SpanCompleted)
    assert payload.node_type == "task_lifecycle"
    assert payload.status == "ok"
    assert payload.attributes["task_id"] == "orch-1"
    assert payload.attributes["task_type"] == "chat"
    assert payload.attributes["status"] == "ok"
    assert payload.attributes["summary"] == "done"
    assert payload.started_at_ms == 1000
    assert payload.ended_at_ms == 2500
    assert payload.duration_ms == 1500


@pytest.mark.asyncio
async def test_helper_publishes_failure_with_error():
    bus = MagicMock()
    bus.publish = AsyncMock(return_value=True)
    orch = _build_orchestrator(bus)

    state = MagicMock()
    state.orchestration_id = "orch-2"
    state.planner = "explore"
    state.created_at = 10.0
    state.updated_at = 11.0
    state.user_id = "u"
    state.session_id = "s"
    state.turn_id = "t"
    state.final_response = ""

    await orch._publish_task_lifecycle(
        state=state,
        status="error",
        summary=None,
        error_type="LaunchError",
        error_message="workers failed to start",
    )

    bus.publish.assert_awaited_once()
    payload: SpanCompleted = bus.publish.await_args.args[0].data
    assert payload.status == "error"
    assert payload.error is not None
    assert payload.error.type == "LaunchError"
    assert payload.error.message == "workers failed to start"
    assert payload.attributes["status"] == "error"


@pytest.mark.asyncio
async def test_helper_publishes_cancelled_status():
    bus = MagicMock()
    bus.publish = AsyncMock(return_value=True)
    orch = _build_orchestrator(bus)

    state = MagicMock()
    state.orchestration_id = "orch-3"
    state.planner = "chat"
    state.created_at = 5.0
    state.updated_at = 6.0
    state.user_id = "u"
    state.session_id = "s"
    state.turn_id = "t"
    state.final_response = ""

    await orch._publish_task_lifecycle(
        state=state,
        status="cancelled",
        summary=None,
        error_type="Cancelled",
        error_message="user cancel",
    )

    payload: SpanCompleted = bus.publish.await_args.args[0].data
    assert payload.status == "cancelled"
    assert payload.error.type == "Cancelled"


@pytest.mark.asyncio
async def test_publish_failure_does_not_raise():
    bus = MagicMock()
    bus.publish = AsyncMock(side_effect=RuntimeError("bus dead"))
    orch = _build_orchestrator(bus)
    state = MagicMock()
    state.orchestration_id = "x"
    state.planner = "chat"
    state.created_at = 1.0
    state.updated_at = 2.0
    state.user_id = "u"
    state.session_id = "s"
    state.turn_id = "t"
    state.final_response = "x"
    # Must not raise
    await orch._publish_task_lifecycle(
        state=state, status="ok", summary="x", error=None
    )
