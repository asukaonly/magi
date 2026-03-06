from __future__ import annotations

from pathlib import Path

import pytest

from magi.agent.orchestration import OrchestrationStore, SubtaskDefinition, TaskOrchestrationState
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


@pytest.mark.asyncio
async def test_aggregate_orchestration_uses_standard_chat_prompt(monkeypatch) -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    history_key = "u-chat::s-chat"
    agent._conversation_history[history_key] = [
        {"role": "user", "content": "看下代码架构"},
        {"role": "assistant", "content": "[Worker:abc] Started (Explore)"},
    ]

    calls: dict[str, object] = {}

    async def _fake_build_system_prompt(*, user_id=None, task_category="chat"):  # type: ignore[no-untyped-def]
        calls["build_system_prompt"] = {
            "user_id": user_id,
            "task_category": task_category,
        }
        return "persona-system-prompt"

    async def _fake_call_llm(system_prompt, messages, disable_thinking=True):  # type: ignore[no-untyped-def]
        calls["call_llm"] = {
            "system_prompt": system_prompt,
            "messages": messages,
            "disable_thinking": disable_thinking,
        }
        return "这是面向用户的最终回答"

    monkeypatch.setattr(agent, "_build_system_prompt", _fake_build_system_prompt)
    monkeypatch.setattr(agent, "_call_llm", _fake_call_llm)

    state = TaskOrchestrationState(
        orchestration_id="orch_test",
        user_id="u-chat",
        session_id="s-chat",
        root_user_message="看下~/code/magi下的代码，分析下代码架构",
        planner="task_agent",
        subtasks=[
            SubtaskDefinition(
                subtask_id="subtask_1",
                description="Analyze backend modules",
                subagent_type="Explore",
                prompt="Inspect backend",
                status="completed",
                worker_result={
                    "summary": "后端采用分层多 agent 架构。",
                    "findings": [
                        {
                            "title": "runtime",
                            "detail": "runtime/bootstrap.py 负责初始化",
                            "path": "/tmp/runtime/bootstrap.py",
                            "why_it_matters": "这是主入口",
                        }
                    ],
                    "evidence": [{"path": "/tmp/runtime/bootstrap.py", "detail": "bootstrap entry"}],
                    "gaps": [],
                    "next_steps": [],
                    "subtasks": [],
                },
                failure_reason=None,
                attempt_count=1,
            ),
        ],
    )

    response = await agent._aggregate_orchestration(state)
    assert response == "这是面向用户的最终回答"
    assert calls["build_system_prompt"] == {"user_id": "u-chat", "task_category": "chat"}

    llm_call = calls["call_llm"]
    assert isinstance(llm_call, dict)
    assert llm_call["system_prompt"] == "persona-system-prompt"
    assert llm_call["disable_thinking"] is False
    messages = llm_call["messages"]
    assert isinstance(messages, list)
    assert messages[0] == {"role": "user", "content": "看下代码架构"}
    final_message = messages[-1]
    assert "直接面向用户回答原始请求" in final_message["content"]
    assert "不要暴露子任务、worker、编排、JSON" in final_message["content"]
    assert '"completed_subtasks"' in final_message["content"]
