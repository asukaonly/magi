from __future__ import annotations

import json
from pathlib import Path

import pytest

from magi.agent.orchestration import OrchestrationStore, SubtaskDefinition, TaskOrchestrationState, WorkerResult
from magi.agent.orchestration_plan import OrchestrationPlan
from magi.agent.task_agents.common import ExecutionMode, ExecutionResult
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
    assert captured["agent_id"] == "u-chat"
    assert isinstance(fact, FactRecord)
    assert fact.event_type == EXPLORE_TASK_COMPLETED
    assert fact.payload["markdown_dossier"] == dossier
