"""Standalone scheduled-execution handlers for agent tasks and action dispatch."""
from __future__ import annotations

import uuid
from typing import Any

from ..core.runtime.contracts import FactRecord
from ..plugins.actions import ActionExecutionContext, ActionRegistry
from .contracts import ScheduledExecutionContext, ScheduledExecutionResult


async def handle_agent_task(
    task_agent_manager: Any,
    context: ScheduledExecutionContext,
) -> ScheduledExecutionResult:
    """Enqueue a FactRecord to the appropriate task agent."""
    payload = dict(context.schedule.target_payload)
    agent_type = str(payload.pop("agent_type"))
    agent_id = str(payload.pop("agent_id"))
    event_type = str(payload.pop("event_type", "ScheduledAgentTask"))
    fact = FactRecord(
        agent_id=f"{agent_type}:{agent_id}",
        event_type=event_type,
        payload=payload,
        agent_type=agent_type,
        agent_instance_id=agent_id,
        correlation_id=str(payload.get("correlation_id") or uuid.uuid4()),
    )
    added = await task_agent_manager.add_fact_to_agent(agent_type, agent_id, fact)
    if not added:
        raise RuntimeError("Failed to enqueue scheduled agent task")
    return ScheduledExecutionResult(success=True, message="agent_task_enqueued")


async def handle_action_dispatch(
    action_registry: ActionRegistry,
    action_emitter: Any,
    context: ScheduledExecutionContext,
) -> ScheduledExecutionResult:
    """Resolve and execute a scheduled action, then emit an event."""
    payload = dict(context.schedule.target_payload)
    action_id = str(payload.get("action_id") or "")
    parameters = payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {}
    action = action_registry.get_action(action_id)
    if action is None:
        raise RuntimeError(f"Unknown action: {action_id}")
    result = await action.execute(
        parameters,
        ActionExecutionContext(
            user_id=str(payload.get("user_id") or "") or None,
            session_id=str(payload.get("session_id") or "") or None,
            runtime_key=context.schedule.schedule_id,
            metadata={"scheduled": True, "manual": context.manual},
        ),
    )
    await action_emitter.emit_action_event(
        fact=FactRecord(
            agent_id=str(payload.get("user_id") or "scheduler"),
            event_type="ScheduledActionDispatch",
            payload={
                "action_type": action_id,
                "params": parameters,
                "response": str(result),
                "execution_time": 0.0,
                "user_id": payload.get("user_id"),
                "session_id": payload.get("session_id"),
            },
            correlation_id=str(payload.get("correlation_id") or uuid.uuid4()),
        ),
        success=True,
        error=None,
    )
    return ScheduledExecutionResult(
        success=True,
        message="action_dispatched",
        stats={"result": result},
    )
