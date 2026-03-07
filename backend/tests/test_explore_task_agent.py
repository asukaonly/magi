from __future__ import annotations

from pathlib import Path

import pytest

from magi.agent.orchestration import OrchestrationStore, SubtaskDefinition, TaskOrchestrationState, WorkerResult
from magi.agent.task_agents.common import ExecutionMode, ExecutionResult
from magi.agent.task_agents.explore_task_agent import ExploreTaskAgent, EXPLORE_TASK_COMPLETED
from magi.core.runtime.contracts import FactRecord


class _FakeLLMAdapter:
    model_name = "fake-model"


@pytest.mark.asyncio
async def test_explore_task_agent_uses_canonical_repo_plan() -> None:
    agent = ExploreTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())

    plan = await agent._planning_service.generate_subtask_plan(
        user_message="看下~/code/magi下的代码，分析下代码架构",
        history=[],
        orchestration_plan={"mode": "decompose", "default_leaf_type": "Explore", "allow_parallel": True},
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
    assert all(item.subagent_type == "Explore" for item in plan.subtasks)


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
                subagent_type="Explore",
                prompt="Inspect backend modules",
                status="completed",
                worker_result=WorkerResult.from_dict(
                    {
                        "result_status": "success",
                        "summary": "Backend is initialized through runtime/bootstrap.py.",
                        "findings": [
                            {
                                "title": "Bootstrap entry",
                                "detail": "runtime/bootstrap.py wires the runtime graph.",
                                "path": "/tmp/runtime/bootstrap.py",
                                "why_it_matters": "This is the main backend entry path.",
                            }
                        ],
                        "evidence": [{"path": "/tmp/runtime/bootstrap.py", "detail": "bootstrap entry"}],
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
                subagent_type="Explore",
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

    class _FakeRuntime:
        def get_task_agent_manager(self):  # type: ignore[no-untyped-def]
            return _FakeManager()

    monkeypatch.setattr("magi.runtime.get_agent_runtime", lambda: _FakeRuntime())

    dossier = await agent._aggregation_service.aggregate_orchestration(state)
    assert state.aggregated_markdown == dossier
    assert "## Backend Modules" in dossier
    assert "/tmp/runtime/bootstrap.py" in dossier
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
