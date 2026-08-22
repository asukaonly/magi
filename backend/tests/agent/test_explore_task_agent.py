from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from magi.agent.orchestration import OrchestrationStore, SubtaskDefinition, TaskOrchestrationState, WorkerResult
from magi.agent.orchestration_plan import OrchestrationPlan
from magi.agent.task_agents.common import (
    ExecutionMode,
    ExecutionResult,
    IncomingFactKind,
)
from magi.agent.task_agents.explore_task_agent import ExploreTaskAgent, EXPLORE_TASK_COMPLETED
from magi.config.models import LLMScenario
from magi.agent.runtime.contracts import FactRecord


class _FakeLLMAdapter:
    model_name = "fake-model"
    provider_name = "openai"

    async def chat(self, **kwargs):
        _ = kwargs
        return "ok"


class _RecordingLLMPool:
    def __init__(self, adapter):
        self._adapter = adapter
        self.requested: list[LLMScenario] = []

    def get(self, scenario: LLMScenario):
        self.requested.append(scenario)
        return self._adapter


def test_explore_batch_stops_at_execution_identity_boundary() -> None:
    agent = ExploreTaskAgent(agent_id="user-1", llm_adapter=_FakeLLMAdapter())

    def fact(*, orchestration_id: str, root_turn_id: str) -> FactRecord:
        return FactRecord(
            agent_id="explore:user-1",
            event_type="WORKER_AGENT_COMPLETED",
            payload={
                "user_id": "user-1",
                "session_id": "session-1",
                "orchestration_id": orchestration_id,
                "root_turn_id": root_turn_id,
            },
        )

    first = fact(orchestration_id="orch-1", root_turn_id="turn-1")
    same = fact(orchestration_id="orch-1", root_turn_id="turn-1")
    different = fact(orchestration_id="orch-2", root_turn_id="turn-2")

    assert agent._should_end_batch_before([first], same) is False
    assert agent._should_end_batch_before([first], different) is True

    first_request = FactRecord(
        agent_id="explore:user-1",
        event_type="EXPLORE_TASK_REQUEST",
        payload={
            "user_id": "user-1",
            "session_id": "session-1",
            "root_turn_id": "turn-root",
            "turn_id": "turn-augment-1",
        },
    )
    second_request = FactRecord(
        agent_id="explore:user-1",
        event_type="EXPLORE_TASK_REQUEST",
        payload={
            "user_id": "user-1",
            "session_id": "session-1",
            "root_turn_id": "turn-root",
            "turn_id": "turn-augment-2",
        },
    )
    assert agent._should_end_batch_before([first_request], second_request) is True


@pytest.mark.asyncio
async def test_explore_context_preserves_worker_user_message_generation() -> None:
    agent = ExploreTaskAgent(agent_id="user-1", llm_adapter=_FakeLLMAdapter())
    worker_fact = FactRecord(
        agent_id="explore:user-1",
        event_type="WORKER_AGENT_COMPLETED",
        payload={
            "user_id": "user-1",
            "session_id": "session-1",
            "worker_id": "worker-1",
        },
        agent_type="explore",
        agent_instance_id="user-1",
        user_message_generation=7,
    )

    merged = await agent.merge_facts([worker_fact])
    context = await agent.build_context(merged)

    assert context.user_message_generation == 7


@pytest.mark.asyncio
async def test_explore_worker_update_restores_persisted_root_turn_id(
    tmp_path: Path,
) -> None:
    agent = ExploreTaskAgent(agent_id="user-1", llm_adapter=_FakeLLMAdapter())
    agent._orchestration_store = OrchestrationStore(tmp_path / "orchestrations.json")
    await agent._orchestration_store.save_orchestration(
        TaskOrchestrationState(
            orchestration_id="orch-root",
            user_id="user-1",
            session_id="session-1",
            root_user_message="Analyze the repository",
            planner="task_agent",
            turn_id="turn-anchor",
            metadata={
                "root_turn_id": "turn-root",
                "upstream_task_agent_type": "chat",
                "upstream_task_agent_id": "session-upstream",
            },
        )
    )
    worker_fact = FactRecord(
        agent_id="explore:user-1",
        event_type="WORKER_AGENT_COMPLETED",
        payload={
            "user_id": "user-1",
            "session_id": "session-1",
            "worker_id": "worker-1",
            "orchestration_id": "orch-root",
            "turn_id": "turn-anchor",
        },
        agent_type="explore",
        agent_instance_id="user-1",
    )

    context = await agent.build_context(await agent.merge_facts([worker_fact]))

    assert context.root_turn_id == "turn-root"
    assert context.upstream_task_agent_type == "chat"
    assert context.upstream_task_agent_id == "session-upstream"


@pytest.mark.asyncio
async def test_explore_budget_failure_emits_terminal_upstream_fact() -> None:
    from magi.agent.execution.task_budget import TaskBudgetExceeded
    from magi.agent.task_agents.explore.constants import EXPLORE_TASK_FAILED
    from magi.i18n import language_context

    agent = ExploreTaskAgent(agent_id="user-1", llm_adapter=_FakeLLMAdapter())
    captured: list[FactRecord] = []

    class _Manager:
        async def add_fact_to_agent(self, _agent_type, _agent_id, fact):  # type: ignore[no-untyped-def]
            captured.append(fact)
            return True

    agent._task_agent_manager = _Manager()
    request = FactRecord(
        agent_id="explore:user-1",
        event_type="EXPLORE_TASK_REQUEST",
        payload={
            "user_id": "user-1",
            "session_id": "session-1",
            "content": "Analyze the repository",
            "upstream_task_agent_type": "chat",
            "upstream_task_agent_id": "session-1",
            "turn_id": "turn-anchor",
            "root_turn_id": "turn-root",
        },
        correlation_id="corr-root",
    )
    context = await agent.build_context(await agent.merge_facts([request]))

    with language_context("en"):
        await agent.handle_batch_failure(
            [request],
            error=TaskBudgetExceeded(
                resource="llm_calls",
                limit=30,
                used=30,
                requested=1,
            ),
            stage="call_llm",
            context=context,
        )

    assert len(captured) == 1
    terminal = captured[0]
    assert terminal.event_type == EXPLORE_TASK_FAILED
    assert terminal.payload["root_turn_id"] == "turn-root"
    assert "execution limit" in terminal.payload["markdown_dossier"]


def test_chat_classifier_treats_explore_failure_as_terminal_result() -> None:
    from magi.agent.task_agents.explore.constants import EXPLORE_TASK_FAILED
    from magi.chat.task_agent.fact_classifier import ChatFactClassifier

    fact = FactRecord(
        agent_id="chat:session-1",
        event_type=EXPLORE_TASK_FAILED,
        payload={
            "user_id": "user-1",
            "session_id": "session-1",
            "root_user_message": "Analyze the repository",
            "markdown_dossier": "The exploration reached its execution limit.",
            "root_turn_id": "turn-root",
        },
    )

    classified = ChatFactClassifier().classify(
        agent_id="session-1",
        latest_fact=fact,
        batch_facts=[fact],
    )

    assert classified.kind == IncomingFactKind.EXPLORE_TASK_FAILED
    assert getattr(classified.latest_payload, "root_turn_id", None) == "turn-root"


@pytest.mark.asyncio
async def test_metadata_read_failure_keeps_terminal_failure_route_available() -> None:
    from magi.agent.task_agents.explore.constants import EXPLORE_TASK_FAILED

    agent = ExploreTaskAgent(
        agent_id="user-1",
        llm_adapter=_FakeLLMAdapter(),
        chat_store=object(),
    )

    class _FailingStore:
        async def get_orchestration(self, _orchestration_id):  # type: ignore[no-untyped-def]
            raise OSError("orchestration store unavailable")

    captured: list[FactRecord] = []

    class _Manager:
        async def add_fact_to_agent(self, _agent_type, _agent_id, fact):  # type: ignore[no-untyped-def]
            captured.append(fact)
            return True

    agent._orchestration_store = _FailingStore()
    manager = _Manager()
    update = FactRecord(
        agent_id="explore:user-1",
        event_type="WORKER_AGENT_COMPLETED",
        payload={
            "user_id": "user-1",
            "session_id": "session-1",
            "orchestration_id": "orch-unavailable",
            "turn_id": "turn-anchor",
        },
    )

    await agent.start(event_emitter=None, task_agent_manager=manager)
    try:
        assert await agent.add_fact(update)
        for _ in range(100):
            if captured:
                break
            await asyncio.sleep(0.01)
    finally:
        await agent.stop()

    assert len(captured) == 1
    assert captured[0].event_type == EXPLORE_TASK_FAILED


@pytest.mark.asyncio
async def test_explore_task_agent_repo_plan_falls_back_to_canonical_when_planner_unavailable() -> None:
    agent = ExploreTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())

    plan = await agent._planning_service.generate_subtask_plan(
        user_message="看下~/code/magi下的代码，分析下代码架构",
        history=[],
        orchestration_plan=OrchestrationPlan(
            mode="decompose", default_leaf_type="CodeExplore", allow_parallel=True
        ),
        user_id="u-chat",
        session_id="s-chat",
    )

    descriptions = [item.description for item in plan.subtasks]
    assert descriptions == [
        "Map repository layout",
        "Identify technology stack",
        "Analyze frontend structure",
        "Analyze backend modules",
        "Inspect project progress",
    ]
    assert all(item.subagent_type == "CodeExplore" for item in plan.subtasks)


@pytest.mark.asyncio
async def test_explore_task_agent_uses_core_scenario_from_pool() -> None:
    pool = _RecordingLLMPool(_FakeLLMAdapter())
    agent = ExploreTaskAgent(agent_id="u-chat", llm_pool=pool)

    response = await agent._prompt_service.call_llm(
        system_prompt="You are helpful.",
        messages=[{"role": "user", "content": "Analyze the repo"}],
        disable_thinking=True,
    )

    assert response == "ok"
    assert pool.requested == [LLMScenario.CORE]


@pytest.mark.asyncio
async def test_explore_planning_service_prefers_llm_plan_for_scoped_request() -> None:
    captured: dict[str, object] = {}

    class _FakePromptService:
        async def call_llm(self, **kwargs):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return (
                '{"summary":"Scoped backend analysis plan","subtasks":['
                '{"description":"Map agent scope","subagent_type":"CodeExplore","prompt":"Inspect backend/src/magi/agent boundaries","parallel_group":"g1"},'
                '{"description":"Trace task orchestration flow","subagent_type":"CodeExplore","prompt":"Trace task agent and worker orchestration in backend/src/magi/agent","parallel_group":"g1"},'
                '{"description":"Summarize orchestration risks","subagent_type":"CodeExplore","prompt":"Summarize risks and open questions inside backend/src/magi/agent","parallel_group":"g2"}'
                ']}'
            )

    from magi.agent.task_agents.explore.planning_service import ExplorePlanningService
    from magi.tools.builtin.file_read_tool import FileReadTool
    from magi.tools.builtin.glob_tool import GlobTool
    from magi.tools.builtin.grep_tool import GrepTool
    from magi.tools.registry import ToolRegistry
    from magi.tools.tool_hint_resolver import ToolHintResolver

    hint_registry = ToolRegistry()
    for tool_class in (GlobTool, GrepTool, FileReadTool):
        hint_registry.register(tool_class)
    service = ExplorePlanningService(
        prompt_service=_FakePromptService(),
        tool_hint_resolver=ToolHintResolver(hint_registry),
    )
    plan = await service.generate_subtask_plan(
        user_message="看下 backend/src/magi/agent 的代码结构和任务编排",
        history=[],
        orchestration_plan=OrchestrationPlan(
            mode="decompose", default_leaf_type="CodeExplore", allow_parallel=True
        ),
        user_id="u-chat",
        session_id="s-chat",
    )

    descriptions = [item.description for item in plan.subtasks]
    planning_payload = json.loads(str(captured["messages"][0]["content"]))
    assert descriptions == [
        "Map agent scope",
        "Trace task orchestration flow",
        "Summarize orchestration risks",
    ]
    assert planning_payload["task_hints"]["task_intent"] == "trace_implementation"
    assert planning_payload["task_hints"]["domain"] == "codebase"
    assert planning_payload["task_hints"]["operation"] == "discover"
    assert planning_payload["task_hints"]["tool_hints"][0]["tool"] in {"glob", "grep"}
    assert captured["json_mode"] is True
    assert captured["timeout_seconds"] == 180.0
    assert all(item.subagent_type == "CodeExplore" for item in plan.subtasks)
    assert all("Parent user request:" in item.prompt for item in plan.subtasks)
    assert all("# Tool Guidance" in item.prompt for item in plan.subtasks)


@pytest.mark.asyncio
async def test_explore_planning_service_uses_scope_fallback_for_backend_request() -> None:
    class _FailingPromptService:
        async def call_llm(self, **kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            raise RuntimeError("planner unavailable")

    from magi.agent.task_agents.explore.planning_service import ExplorePlanningService

    service = ExplorePlanningService(prompt_service=_FailingPromptService())
    plan = await service.generate_subtask_plan(
        user_message="分析 backend/src/magi/agent 里的任务编排实现",
        history=[],
        orchestration_plan=OrchestrationPlan(
            mode="decompose", default_leaf_type="CodeExplore", allow_parallel=True
        ),
        user_id="u-chat",
        session_id="s-chat",
    )

    descriptions = [item.description for item in plan.subtasks]
    assert descriptions == [
        "Map backend scope",
        "Trace backend execution flow",
        "Summarize backend gaps",
    ]


@pytest.mark.asyncio
async def test_explore_planning_does_not_fallback_after_task_budget_exhaustion() -> None:
    from magi.agent.execution.task_budget import TaskBudgetExceeded
    from magi.agent.task_agents.explore.planning_service import ExplorePlanningService

    class _ExhaustedPromptService:
        async def call_llm(self, **_kwargs):  # type: ignore[no-untyped-def]
            raise TaskBudgetExceeded(
                resource="llm_calls",
                limit=1,
                used=1,
                requested=1,
            )

    service = ExplorePlanningService(prompt_service=_ExhaustedPromptService())

    with pytest.raises(TaskBudgetExceeded, match="llm_calls"):
        await service.generate_subtask_plan(
            user_message="Analyze backend task orchestration",
            history=[],
            orchestration_plan=OrchestrationPlan(
                mode="decompose",
                default_leaf_type="CodeExplore",
                allow_parallel=True,
            ),
            user_id="u-chat",
            session_id="s-chat",
        )


def test_explore_planning_service_generic_leaf_prompt_emphasizes_anchor_and_validation() -> None:
    from magi.agent.task_agents.explore.planning_service import ExplorePlanningService

    service = ExplorePlanningService(prompt_service=None)
    subtasks = service.generic_fallback_subtasks("分析检索链路")

    assert [item.description for item in subtasks] == [
        "Locate the primary anchor",
        "Trace the owning implementation path",
        "Validate gaps and edge cases",
    ]
    assert "Start from the most concrete anchor available" in subtasks[0].prompt
    assert "verify it exists in the current code before relying on it" in subtasks[0].prompt
    assert "Prefer focused glob/grep/read steps over broad repository scans" in subtasks[0].prompt


def test_explore_planning_service_treats_docs_path_as_scoped_request() -> None:
    from magi.agent.task_agents.explore.planning_service import ExplorePlanningService

    service = ExplorePlanningService(prompt_service=None)

    assert service.is_path_scoped_request("分析 docs/task-agent-runtime-architecture.md 里的任务编排说明")


@pytest.mark.asyncio
async def test_explore_task_agent_builds_markdown_dossier_and_emits_upstream_fact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    agent = ExploreTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    agent._orchestration_store = OrchestrationStore(tmp_path / "orchestrations.json")
    agent._task_orchestrator._orchestration_store = agent._orchestration_store

    state = TaskOrchestrationState(
        orchestration_id="orch_test",
        user_id="u-chat",
        session_id="s-chat",
        root_user_message="Analyze the repository architecture",
        planner="task_agent",
        subtasks=[
            SubtaskDefinition(
                subtask_id="sub_1",
                description="Analyze backend modules",
                subagent_type="CodeExplore",
                prompt="Inspect backend modules",
                status="completed",
                worker_result=WorkerResult.from_dict(
                    {
                        "result_status": "success",
                        "summary": "Backend is initialized through bootstrap/backend.py.",
                        "findings": [
                            {
                                "title": "Bootstrap entry",
                                "detail": "bootstrap/backend.py wires the runtime graph.",
                                "path": "/tmp/bootstrap/backend.py",
                                "why_it_matters": "This is the main backend entry path.",
                            }
                        ],
                        "evidence": [{"path": "/tmp/bootstrap/backend.py", "detail": "bootstrap entry"}],
                        "gaps": [],
                        "next_steps": ["Inspect task agent boundaries"],
                        "failure_reason": None,
                    }
                ),
                attempt_count=1,
            ),
            SubtaskDefinition(
                subtask_id="sub_2",
                description="Analyze frontend structure",
                subagent_type="CodeExplore",
                prompt="Inspect frontend",
                status="failed",
                failure_reason="PATH_NOT_FOUND",
                attempt_count=1,
            ),
        ],
    )

    captured = {}

    class _FakeManager:
        async def add_fact_to_agent(self, agent_type, agent_id, fact):  # type: ignore[no-untyped-def]
            captured["agent_type"] = agent_type
            captured["agent_id"] = agent_id
            captured["fact"] = fact
            return True

    agent._task_agent_manager = _FakeManager()

    dossier = await agent._aggregation_service.aggregate_orchestration(state)
    assert state.aggregated_markdown == dossier
    assert "## Backend Modules" in dossier
    assert "/tmp/bootstrap/backend.py" in dossier
    assert "## Frontend Structure" in dossier
    assert "PATH_NOT_FOUND" in dossier

    fact = FactRecord(
        agent_id="explore:u-chat",
        event_type="WORKER_AGENT_COMPLETED",
        payload={
            "user_id": "u-chat",
            "session_id": "s-chat",
            "upstream_task_agent_type": "chat",
            "upstream_task_agent_id": "u-chat",
        },
        agent_type="explore",
        agent_instance_id="u-chat",
        correlation_id="corr_1",
    )
    merged = await agent.merge_facts([fact])
    context = await agent.build_context(merged)
    await agent.parse_result(
        context,
        ExecutionResult(
            mode=ExecutionMode.ORCHESTRATION_UPDATE,
            response_text=dossier,
            skip_emit=False,
            root_user_message=state.root_user_message,
            orchestration_id=state.orchestration_id,
            correlation_id="corr_1",
        ),
    )

    fact = captured["fact"]
    assert captured["agent_type"] == "chat"
    assert captured["agent_id"] == "s-chat"
    assert isinstance(fact, FactRecord)
    assert fact.event_type == EXPLORE_TASK_COMPLETED
    assert fact.payload["markdown_dossier"] == dossier
