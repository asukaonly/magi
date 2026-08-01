"""Worker fact and event publication helpers."""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional, Protocol, cast

from ...agent.trace import now_wall_ms
from ...core.logger import get_logger
from ...events.events import Event, EventLevel
from ...runtime_trace import RuntimeNotificationRecord
from .worker_state import WorkerRunState

logger = get_logger(__name__)


class _WorkerPublicationHostProtocol(Protocol):
    _message_bus: Any
    _runtime_trace_store: Any
    _task_agent_manager: Any


class WorkerPublicationMixin:
    """Publish worker facts, bus events, and trace notifications."""

    async def _publish_worker_fact(
        self,
        run_state: WorkerRunState,
        event_type: str,
        internal_payload: Dict[str, Any],
        public_payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        host = cast(_WorkerPublicationHostProtocol, self)
        manager = _resolve_task_agent_manager(host, run_state)
        if manager is None:
            return

        now = time.time()
        await _add_worker_fact_to_target(
            manager,
            run_state,
            event_type=event_type,
            payload=_build_internal_worker_payload(run_state, internal_payload, now),
            timestamp=now,
        )
        external_data = _build_external_worker_payload(
            run_state,
            public_payload or internal_payload,
            now,
        )
        await self._publish_worker_bus_event(
            event_type=event_type,
            payload=external_data,
            correlation_id=run_state.worker_id,
        )

    async def _publish_worker_bus_event(
        self,
        event_type: str,
        payload: Dict[str, Any],
        correlation_id: str,
    ) -> None:
        host = cast(_WorkerPublicationHostProtocol, self)
        try:
            message_bus = host._message_bus
            if message_bus is None:
                return
            await message_bus.publish(
                Event(
                    type=event_type,
                    data=payload,
                    source="agent_tool",
                    level=EventLevel.INFO,
                    correlation_id=correlation_id,
                )
            )
        except Exception as exc:
            logger.debug(
                f"Failed to publish worker bus event | event_type={event_type} error={exc}"
            )
        await self._publish_trace_update_notification(payload)

    async def _publish_trace_update_notification(self, payload: Dict[str, Any]) -> None:
        host = cast(_WorkerPublicationHostProtocol, self)
        if host._runtime_trace_store is None:
            return
        user_id = str(payload.get("user_id") or "").strip()
        session_id = str(payload.get("session_id") or "").strip()
        turn_id = str(payload.get("turn_id") or "").strip() or None
        if not user_id or not session_id or not turn_id:
            return
        notification_payload = {
            "user_id": user_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "refresh_trace": True,
        }
        await host._runtime_trace_store.append_notification(
            RuntimeNotificationRecord(
                notification_id=0,
                channel="trace_update",
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
                payload_json=json.dumps(notification_payload, ensure_ascii=False),
                created_at_ms=now_wall_ms(),
            )
        )


def _resolve_task_agent_manager(
    host: _WorkerPublicationHostProtocol,
    run_state: WorkerRunState,
) -> Any | None:
    try:
        manager = host._task_agent_manager
        if manager is None:
            raise RuntimeError("task agent manager unavailable")
        return manager
    except Exception as exc:
        logger.debug(
            "Worker fact publish skipped (runtime unavailable) | worker_id=%s error=%s",
            run_state.worker_id,
            exc,
        )
        return None


async def _add_worker_fact_to_target(
    manager: Any,
    run_state: WorkerRunState,
    *,
    event_type: str,
    payload: Dict[str, Any],
    timestamp: float,
) -> None:
    from ...agent.runtime.contracts import FactRecord

    fact = FactRecord(
        agent_id=f"{run_state.target_task_agent_type}:{run_state.target_task_agent_id}",
        event_type=event_type,
        payload=payload,
        agent_type=run_state.target_task_agent_type,
        agent_instance_id=run_state.target_task_agent_id,
        timestamp=timestamp,
        correlation_id=run_state.worker_id,
        user_message_generation=run_state.user_message_generation,
    )
    await manager.add_fact_to_agent(
        run_state.target_task_agent_type,
        run_state.target_task_agent_id,
        fact,
    )


def _build_internal_worker_payload(
    run_state: WorkerRunState,
    payload: Dict[str, Any],
    timestamp: float,
) -> Dict[str, Any]:
    return {
        **_base_worker_payload(run_state, timestamp),
        "parent_task_agent_type": run_state.parent_task_agent_type,
        "parent_task_agent_id": run_state.parent_task_agent_id,
        **payload,
    }


def _build_external_worker_payload(
    run_state: WorkerRunState,
    payload: Dict[str, Any],
    timestamp: float,
) -> Dict[str, Any]:
    return {
        **_base_worker_payload(run_state, timestamp),
        **payload,
    }


def _base_worker_payload(
    run_state: WorkerRunState,
    timestamp: float,
) -> Dict[str, Any]:
    return {
        "worker_id": run_state.worker_id,
        "worker_status": run_state.status,
        "worker_subagent_type": run_state.subagent_type,
        "worker_description": run_state.description,
        "failure_reason": run_state.failure_reason,
        "orchestration_id": run_state.orchestration_id,
        "subtask_id": run_state.subtask_id,
        "target_task_agent_type": run_state.target_task_agent_type,
        "target_task_agent_id": run_state.target_task_agent_id,
        "user_id": run_state.user_id,
        "session_id": run_state.session_id,
        "turn_id": run_state.turn_id,
        "run_id": run_state.run_id,
        "run_revision": run_state.run_revision,
        "timestamp": timestamp,
    }
