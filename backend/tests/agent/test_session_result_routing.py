from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from magi.agent.task_agents.chat.contracts import ChatRuntimeContext, IntentDecision
from magi.agent.task_agents.chat.handlers import ChatHandlerDependencies, _start_explore_task_agent
from magi.agent.task_agents.chat.planning_service import ChatPlanningService
from magi.agent.task_agents.common import (
    ExecutionMode,
    ExecutionRequest,
    ExecutionResult,
    IncomingFactKind,
    OrchestrationPlan,
    ToolSelection,
    UserMessagePayload,
)
from magi.agent.task_agents.explore.contracts import ExploreRuntimeContext
from magi.agent.task_agents.explore.postprocess_service import ExplorePostProcessService
from magi.agent.task_orchestrator import TaskOrchestrator
from magi.agent.runtime.contracts import FactRecord
from magi.agent.workers.worker_manager import WORKER_AGENT_COMPLETED, WorkerAgentManager, WorkerRunState
from magi.tools.registry import ToolRegistry


async def _fake_plan_subtasks(*args, **kwargs):  # type: ignore[no-untyped-def]
    _ = (args, kwargs)
    raise AssertionError("plan_subtasks should not be called in this test")


async def _fake_aggregate(*args, **kwargs):  # type: ignore[no-untyped-def]
    _ = (args, kwargs)
    raise AssertionError("aggregate_orchestration should not be called in this test")


def _fake_register_user_message(*args, **kwargs) -> None:  # type: ignore[no-untyped-def]
    _ = (args, kwargs)


class _FakePromptService:
    def filter_history_for_aggregation(self, history):  # type: ignore[no-untyped-def]
        return list(history)


class _FakeHistoryService:
    def append_user_message(self, history_key: str, content: str) -> None:
        _ = (history_key, content)


class _RecordingTaskAgentManager:
    def __init__(self) -> None:
        self.calls: list[tuple[object, str, FactRecord]] = []

    async def add_fact_to_agent(self, agent_type, agent_id, fact):  # type: ignore[no-untyped-def]
        self.calls.append((agent_type, agent_id, fact))
        return True


def test_task_orchestrator_chat_context_targets_session_chat_agent() -> None:
    orchestrator = TaskOrchestrator(
        runtime_key="chat:user-1",
        tool_registry=ToolRegistry(),
        plan_subtasks=_fake_plan_subtasks,
        aggregate_orchestration=_fake_aggregate,
        register_user_message=_fake_register_user_message,
        parent_task_agent_type="chat",
    )

    context = orchestrator._build_agent_tool_context("user-1", "session-1")

    assert context.env_vars["target_task_agent_type"] == "chat"
    assert context.env_vars["target_task_agent_id"] == "session-1"
    assert context.env_vars["parent_task_agent_type"] == "chat"
    assert context.env_vars["parent_task_agent_id"] == "session-1"


def test_chat_planning_service_context_targets_session_chat_agent() -> None:
    service = ChatPlanningService(
        agent_id="user-1",
        runtime_key="chat:user-1",
        context_service=SimpleNamespace(),
        prompt_service=SimpleNamespace(),
        history_service=SimpleNamespace(),
        tool_registry=ToolRegistry(),
        parent_task_agent_type="chat",
    )

    context = service._build_agent_tool_context("user-1", "session-1")

    assert context.env_vars["target_task_agent_type"] == "chat"
    assert context.env_vars["target_task_agent_id"] == "session-1"
    assert context.env_vars["parent_task_agent_type"] == "chat"
    assert context.env_vars["parent_task_agent_id"] == "session-1"


@pytest.mark.asyncio
async def test_start_explore_task_agent_routes_upstream_to_chat_session() -> None:
    manager = _RecordingTaskAgentManager()
    deps = ChatHandlerDependencies(
        context_service=SimpleNamespace(),
        prompt_service=_FakePromptService(),
        planning_service=SimpleNamespace(),
        function_calling_orchestrator=SimpleNamespace(),
        task_orchestrator=SimpleNamespace(),
        history_service=_FakeHistoryService(),
        agent_id="chat:user-1",
        get_task_agent_manager=lambda: manager,
    )
    request = ExecutionRequest(
        mode=ExecutionMode.ORCHESTRATION_LAUNCH,
        context=ChatRuntimeContext(
            latest_fact=FactRecord(
                agent_id="chat:session-1",
                event_type="USER_MESSAGE",
                payload={"user_id": "user-1", "session_id": "session-1", "content": "analyze repo"},
                agent_type="chat",
                agent_instance_id="session-1",
                correlation_id="corr-1",
            ),
            recent_facts=[],
            batch_facts=[],
            agent_id="user-1",
            agent_type="chat",
            runtime_key="chat:user-1",
            user_id="user-1",
            session_id="session-1",
            history_key="user-1::session-1",
            history=[],
            conversation_history=[],
            active_orchestrations=[],
            recent_tool_errors=[],
            latest_user_message="analyze repo",
            incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
            latest_payload=UserMessagePayload(
                user_id="user-1",
                session_id="session-1",
                content="analyze repo",
                turn_id="turn-1",
            ),
        ),
        intent=IntentDecision(
            intent="repo_analysis",
            difficulty="normal",
            execution_mode=ExecutionMode.ORCHESTRATION_LAUNCH,
            orchestration_plan=OrchestrationPlan(route_to_explore_task_agent=True),
        ),
        tool_selection=ToolSelection(),
    )

    result = await _start_explore_task_agent(deps, request)

    assert result is not None
    assert len(manager.calls) == 1
    _, agent_id, fact = manager.calls[0]
    assert agent_id == "user-1"
    assert fact.payload["upstream_task_agent_type"] == "chat"
    assert fact.payload["upstream_task_agent_id"] == "session-1"


@pytest.mark.asyncio
async def test_explore_completion_payload_targets_chat_session() -> None:
    manager = _RecordingTaskAgentManager()
    service = ExplorePostProcessService(get_task_agent_manager=lambda: manager)
    context = ExploreRuntimeContext(
        latest_fact=FactRecord(
            agent_id="explore:user-1",
            event_type="EXPLORE_TASK_REQUEST",
            payload={"user_id": "user-1", "session_id": "session-1", "content": "analyze repo"},
            agent_type="explore",
            agent_instance_id="user-1",
            correlation_id="corr-1",
        ),
        recent_facts=[],
        batch_facts=[],
        agent_id="user-1",
        agent_type="explore",
        runtime_key="explore:user-1",
        user_id="user-1",
        session_id="session-1",
        history_key="user-1::session-1",
        history=[],
        latest_user_message="analyze repo",
        incoming_fact_kind=IncomingFactKind.EXPLORE_TASK_REQUEST,
        latest_payload=UserMessagePayload(user_id="user-1", session_id="session-1", content="analyze repo"),
        upstream_task_agent_type="chat",
        upstream_task_agent_id="session-1",
    )

    await service.handle(
        context,
        ExecutionResult(
            mode=ExecutionMode.ORCHESTRATION_UPDATE,
            response_text="# Dossier",
            root_user_message="analyze repo",
            correlation_id="corr-1",
            turn_id="turn-1",
        ),
    )

    assert len(manager.calls) == 1
    agent_type, agent_id, fact = manager.calls[0]
    assert agent_type == "chat"
    assert agent_id == "session-1"
    assert fact.agent_id == "chat:session-1"
    assert fact.payload["target_task_agent_type"] == "chat"
    assert fact.payload["target_task_agent_id"] == "session-1"


@pytest.mark.asyncio
async def test_worker_completion_payload_targets_chat_session() -> None:
    manager = _RecordingTaskAgentManager()
    worker_manager = WorkerAgentManager()
    worker_manager._task_agent_manager = manager
    now = time.time()
    run_state = WorkerRunState(
        worker_id="worker-1",
        subagent_type="Explore",
        description="Inspect backend",
        prompt="Inspect backend",
        orchestration_id="orch-1",
        subtask_id="subtask-1",
        parent_task_agent_type="chat",
        parent_task_agent_id="session-1",
        target_task_agent_type="chat",
        target_task_agent_id="session-1",
        user_id="user-1",
        session_id="session-1",
        turn_id="turn-1",
        created_at=now,
        updated_at=now,
        status="completed",
    )

    await worker_manager._publish_worker_fact(
        run_state,
        WORKER_AGENT_COMPLETED,
        {
            "worker_result": {
                "result_status": "success",
                "summary": "Backend analyzed",
                "findings": [],
                "evidence": [],
                "gaps": [],
                "next_steps": [],
                "failure_reason": None,
            }
        },
    )

    assert len(manager.calls) == 1
    agent_type, agent_id, fact = manager.calls[0]
    assert agent_type == "chat"
    assert agent_id == "session-1"
    assert fact.payload["target_task_agent_type"] == "chat"
    assert fact.payload["target_task_agent_id"] == "session-1"
