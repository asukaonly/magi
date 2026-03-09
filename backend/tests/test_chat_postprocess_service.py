from __future__ import annotations

from pathlib import Path

import pytest

from magi.agent.task_agents.chat.postprocess_service import ChatPostProcessService


class _FakeSessionService:
    def resolve_session_id(self, user_id: str, session_id: str | None = None) -> str:
        return session_id or "generated-session"

    def history_key(self, user_id: str, session_id: str) -> str:
        return f"{user_id}::{session_id}"

    def store_tool_interaction(self, history_key: str, record: dict) -> None:
        _ = (history_key, record)


class _FakeActionExecutor:
    def __init__(self) -> None:
        self.action_events: list[tuple[object, bool, str | None]] = []
        self.runtime_events: list[dict] = []

    async def emit_action_event(self, fact, success: bool, error: str | None = None) -> None:
        self.action_events.append((fact, success, error))

    async def emit_runtime_event(
        self,
        *,
        event_type: str,
        payload: dict[str, object],
        correlation_id: str | None = None,
        success: bool = True,
    ) -> None:
        self.runtime_events.append(
            {
                "event_type": event_type,
                "payload": payload,
                "correlation_id": correlation_id,
                "success": success,
            }
        )


@pytest.mark.asyncio
async def test_record_tool_interaction_preserves_trace_identity() -> None:
    action_executor = _FakeActionExecutor()
    service = ChatPostProcessService(
        agent_id="chat:web_user",
        session_service=_FakeSessionService(),  # type: ignore[arg-type]
        get_action_executor=lambda: action_executor,
        max_fact_memory=10,
    )

    await service.record_tool_interaction(
        {
            "user_id": "web_user",
            "session_id": "session-1",
            "turn_id": "turn-1",
            "orchestration_id": "orch-1",
            "tool_call_id": "call-1",
            "iteration": 3,
            "tool_name": "web-search",
            "arguments": {"query": "Hangzhou news"},
            "execution_time": 0.25,
            "success": True,
            "error": None,
            "error_code": None,
            "data": {"provider": "duckduckgo"},
            "intent": "news_query",
        }
    )

    assert len(action_executor.action_events) == 1
    fact, success, error = action_executor.action_events[0]
    assert success is True
    assert error is None
    assert fact.payload["turn_id"] == "turn-1"
    assert fact.payload["orchestration_id"] == "orch-1"
    assert fact.payload["tool_call_id"] == "call-1"
    assert fact.payload["iteration"] == 3

    assert len(action_executor.runtime_events) == 1
    runtime_payload = action_executor.runtime_events[0]["payload"]
    assert runtime_payload["turn_id"] == "turn-1"
    assert runtime_payload["iteration"] == 3
