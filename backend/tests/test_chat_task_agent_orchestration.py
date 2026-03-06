from __future__ import annotations

from pathlib import Path

import pytest

from magi.agent.orchestration import OrchestrationStore
from magi.agent.task_agents.chat_task_agent import ChatTaskAgent
from magi.core.runtime.contracts import FactRecord
from magi.events.events import EventTypes


class _FakeLLMAdapter:
    model_name = "fake-model"
    supports_embeddings = False


@pytest.mark.asyncio
async def test_chat_task_agent_completes_orchestration_after_worker_fact(tmp_path: Path, monkeypatch) -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    agent._orchestration_store = OrchestrationStore(tmp_path / "orchestrations.json")
    agent._task_orchestrator._orchestration_store = agent._orchestration_store

    async def _fake_generate_subtask_plan(*args, **kwargs):  # type: ignore[no-untyped-def]
        _ = (args, kwargs)
        return {
            "summary": "planned",
            "subtasks": [
                {
                    "description": "scan backend",
                    "subagent_type": "Explore",
                    "prompt": "Inspect backend layout",
                    "parallel_group": "group_a",
                }
            ],
        }

    async def _fake_launch(state):  # type: ignore[no-untyped-def]
        state.subtasks[0].worker_id = "worker_1"
        state.subtasks[0].status = "running"
        await agent._orchestration_store.save_orchestration(state)
        return None

    async def _fake_aggregate(state):  # type: ignore[no-untyped-def]
        assert state.subtasks[0].worker_result is not None
        return "aggregated answer"

    monkeypatch.setattr(agent._task_orchestrator, "_plan_subtasks", _fake_generate_subtask_plan)
    monkeypatch.setattr(agent._task_orchestrator, "_launch_workers", _fake_launch)
    monkeypatch.setattr(agent._task_orchestrator, "_aggregate_orchestration", _fake_aggregate)

    user_fact = FactRecord(
        agent_id="chat:u-chat",
        event_type=EventTypes.USER_MESSAGE,
        payload={"message": "Analyze repo architecture", "user_id": "u-chat", "session_id": "s-chat"},
        agent_type="chat",
        agent_instance_id="u-chat",
        correlation_id="corr_1",
    )
    context = {
        "user_id": "u-chat",
        "session_id": "s-chat",
        "user_message": "Analyze repo architecture",
        "history": [],
        "history_key": "u-chat::s-chat",
        "latest_fact": user_fact,
    }
    llm_params = {
        "user_id": "u-chat",
        "session_id": "s-chat",
        "user_message": "Analyze repo architecture",
        "history": [],
        "orchestration_strategy": {
            "mode": "decompose",
            "planner": "task_agent",
            "default_leaf_type": "Explore",
            "allow_parallel": True,
        },
    }

    launch_result = await agent._start_orchestration(context, llm_params)
    assert launch_result["skip_emit"] is True

    states = await agent._orchestration_store.list_orchestrations(user_id="u-chat", session_id="s-chat")
    assert len(states) == 1
    state = states[0]
    assert state.subtasks[0].worker_id == "worker_1"
    assert state.subtasks[0].status == "running"

    completed_fact = FactRecord(
        agent_id="chat:u-chat",
        event_type="WORKER_AGENT_COMPLETED",
        payload={
            "worker_id": "worker_1",
            "orchestration_id": state.orchestration_id,
            "subtask_id": state.subtasks[0].subtask_id,
            "worker_result": {
                "summary": "backend analyzed",
                "findings": [{"title": "backend", "detail": "runtime path"}],
                "evidence": [{"path": "/tmp/backend.py", "detail": "entrypoint"}],
                "gaps": [],
                "next_steps": ["aggregate"],
            },
            "user_id": "u-chat",
            "session_id": "s-chat",
        },
        agent_type="chat",
        agent_instance_id="u-chat",
        correlation_id="worker_1",
    )

    update_result = await agent._process_worker_updates({}, {"batch_facts": [completed_fact]})
    assert update_result["response"] == "aggregated answer"
    assert update_result["orchestration_id"] == state.orchestration_id

    updated = await agent._orchestration_store.get_orchestration(state.orchestration_id)
    assert updated is not None
    assert updated.status == "completed"
    assert updated.final_response == "aggregated answer"
