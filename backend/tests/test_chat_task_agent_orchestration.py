from __future__ import annotations

from pathlib import Path

import pytest

from magi.agent.orchestration import (
    OrchestrationStore,
    PlannedSubtask,
    SubtaskDefinition,
    SubtaskPlan,
    TaskOrchestrationState,
    WorkerResult,
)
from magi.agent.task_agents.chat import ExecutionMode, ExecutionRequest, IntentDecision, OrchestrationPlan, ToolSelection
from magi.agent.task_agents.chat import planning_service as planning_service_module
from magi.agent.task_agents.chat_task_agent import ChatTaskAgent
from magi.agent.task_agents.explore_task_agent import EXPLORE_TASK_COMPLETED
from magi.core.runtime.contracts import FactRecord
from magi.core.runtime.types import TaskAgentType
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
        return SubtaskPlan(
            summary="planned",
            subtasks=[
                PlannedSubtask(
                    description="scan backend",
                    subagent_type="Explore",
                    prompt="Inspect backend layout",
                    parallel_group="group_a",
                )
            ],
        )

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
    merged = await agent.merge_facts([user_fact])
    context = await agent.build_context(merged)
    request = ExecutionRequest(
        mode=ExecutionMode.ORCHESTRATION_LAUNCH,
        context=context,
        intent=IntentDecision(
            intent="repo_analysis",
            difficulty="normal",
            execution_mode=ExecutionMode.ORCHESTRATION_LAUNCH,
            orchestration_plan=OrchestrationPlan(
                mode="decompose",
                planner="task_agent",
                default_leaf_type="general-purpose",
                allow_parallel=True,
            ),
        ),
        tool_selection=ToolSelection(),
    )
    request = await agent._handler_registry.get(ExecutionMode.ORCHESTRATION_LAUNCH).build_request(request)
    launch_result = await agent._handler_registry.get(ExecutionMode.ORCHESTRATION_LAUNCH).execute(request)
    assert launch_result.skip_emit is True

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
                "result_status": "success",
                "summary": "backend analyzed",
                "findings": [{"title": "backend", "detail": "runtime path"}],
                "evidence": [{"path": "/tmp/backend.py", "detail": "entrypoint"}],
                "gaps": [],
                "next_steps": ["aggregate"],
                "failure_reason": None,
            },
            "user_id": "u-chat",
            "session_id": "s-chat",
        },
        agent_type="chat",
        agent_instance_id="u-chat",
        correlation_id="worker_1",
    )

    merged_update = await agent.merge_facts([completed_fact])
    update_context = await agent.build_context(merged_update)
    update_request = ExecutionRequest(
        mode=ExecutionMode.ORCHESTRATION_UPDATE,
        context=update_context,
        intent=IntentDecision(
            intent="worker_orchestration_update",
            difficulty="normal",
            execution_mode=ExecutionMode.ORCHESTRATION_UPDATE,
        ),
        tool_selection=ToolSelection(),
    )
    update_result = await agent._handler_registry.get(ExecutionMode.ORCHESTRATION_UPDATE).execute(update_request)
    assert update_result.response_text == "aggregated answer"
    assert update_result.orchestration_id == state.orchestration_id

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

    async def _fake_build_system_prompt(*, user_id=None, task_category="chat", scenario="chat"):  # type: ignore[no-untyped-def]
        calls["build_system_prompt"] = {
            "user_id": user_id,
            "task_category": task_category,
            "scenario": scenario,
        }
        return "persona-system-prompt"

    async def _fake_call_llm(*, system_prompt, messages, disable_thinking=True):  # type: ignore[no-untyped-def]
        calls["call_llm"] = {
            "system_prompt": system_prompt,
            "messages": messages,
            "disable_thinking": disable_thinking,
        }
        return "这是面向用户的最终回答"

    monkeypatch.setattr(agent._prompt_service, "build_system_prompt", _fake_build_system_prompt)
    monkeypatch.setattr(agent._prompt_service, "call_llm", _fake_call_llm)

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
                worker_result=WorkerResult.from_dict(
                    {
                        "result_status": "success",
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
                        "failure_reason": None,
                        "subtasks": [],
                    }
                ),
                failure_reason=None,
                attempt_count=1,
            ),
        ],
    )

    response = await agent._planning_service.aggregate_orchestration(state)
    assert response == "这是面向用户的最终回答"
    assert calls["build_system_prompt"] == {"user_id": "u-chat", "task_category": "chat", "scenario": "chat"}

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


@pytest.mark.asyncio
async def test_chat_task_agent_routes_large_explore_to_explore_task_agent(monkeypatch) -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
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

    user_fact = FactRecord(
        agent_id="chat:u-chat",
        event_type=EventTypes.USER_MESSAGE,
        payload={"message": "看下~/code/magi下的代码，分析下代码架构", "user_id": "u-chat", "session_id": "s-chat"},
        agent_type="chat",
        agent_instance_id="u-chat",
        correlation_id="corr_x",
    )
    merged = await agent.merge_facts([user_fact])
    context = await agent.build_context(merged)
    agent._conversation_history["u-chat::s-chat"] = [{"role": "user", "content": "看下代码架构"}]
    request = ExecutionRequest(
        mode=ExecutionMode.ORCHESTRATION_LAUNCH,
        context=context,
        intent=IntentDecision(
            intent="repo_analysis",
            difficulty="normal",
            execution_mode=ExecutionMode.ORCHESTRATION_LAUNCH,
            orchestration_plan=OrchestrationPlan(
                mode="decompose",
                planner="task_agent",
                default_leaf_type="Explore",
                allow_parallel=True,
                route_to_explore_task_agent=True,
            ),
        ),
        tool_selection=ToolSelection(),
    )
    request = await agent._handler_registry.get(ExecutionMode.ORCHESTRATION_LAUNCH).build_request(request)
    result = await agent._handler_registry.get(ExecutionMode.ORCHESTRATION_LAUNCH).execute(request)

    assert result.skip_emit is True
    assert captured["agent_type"] == TaskAgentType.EXPLORE
    assert captured["agent_id"] == "u-chat"
    fact = captured["fact"]
    assert isinstance(fact, FactRecord)
    assert fact.event_type == "EXPLORE_TASK_REQUEST"
    assert fact.payload["upstream_task_agent_type"] == "chat"


@pytest.mark.asyncio
async def test_chat_task_agent_renders_explore_dossier_with_analysis_prompt(monkeypatch) -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    agent._conversation_history["u-chat::s-chat"] = [
        {"role": "user", "content": "看下代码架构"},
        {"role": "assistant", "content": "好的，我先拆分下。"},
    ]
    calls = {}

    async def _fake_build_system_prompt(*, scenario="chat", user_id=None, task_category="chat"):  # type: ignore[no-untyped-def]
        calls["build_system_prompt"] = {
            "scenario": scenario,
            "user_id": user_id,
            "task_category": task_category,
        }
        return "analysis-system-prompt"

    async def _fake_call_llm(*, system_prompt, messages, disable_thinking=True):  # type: ignore[no-untyped-def]
        calls["call_llm"] = {
            "system_prompt": system_prompt,
            "messages": messages,
            "disable_thinking": disable_thinking,
        }
        return "这是最终分析回答"

    monkeypatch.setattr(agent._prompt_service, "build_system_prompt", _fake_build_system_prompt)
    monkeypatch.setattr(agent._prompt_service, "call_llm", _fake_call_llm)

    latest_fact = FactRecord(
        agent_id="chat:u-chat",
        event_type=EXPLORE_TASK_COMPLETED,
        payload={
            "user_id": "u-chat",
            "session_id": "s-chat",
            "root_user_message": "看下~/code/magi下的代码，分析下代码架构",
            "markdown_dossier": "# Request\n看下~/code/magi下的代码，分析下代码架构\n\n## Backend Modules\n- runtime/bootstrap.py",
            "orchestration_id": "orch_x",
        },
        agent_type="chat",
        agent_instance_id="u-chat",
        correlation_id="corr_dossier",
    )

    merged = await agent.merge_facts([latest_fact])
    context = await agent.build_context(merged)
    request = ExecutionRequest(
        mode=ExecutionMode.EXPLORE_TASK_RENDER,
        context=context,
        intent=IntentDecision(
            intent="explore_task_completed",
            difficulty="normal",
            execution_mode=ExecutionMode.EXPLORE_TASK_RENDER,
        ),
        tool_selection=ToolSelection(),
    )
    request = await agent._handler_registry.get(ExecutionMode.EXPLORE_TASK_RENDER).build_request(request)
    result = await agent._handler_registry.get(ExecutionMode.EXPLORE_TASK_RENDER).execute(request)

    assert result.response_text == "这是最终分析回答"
    assert calls["build_system_prompt"] == {
        "scenario": "analysis",
        "user_id": "u-chat",
        "task_category": "analysis",
    }
    call_llm = calls["call_llm"]
    assert call_llm["system_prompt"] == "analysis-system-prompt"
    assert call_llm["disable_thinking"] is True
    assert "探索报告" in call_llm["messages"][-1]["content"]
    assert "# Request" in call_llm["messages"][-1]["content"]


def test_chat_prompt_service_formats_dense_explore_render_text() -> None:
    from magi.agent.task_agents.chat.prompt_service import ChatPromptService

    service = ChatPromptService(
        agent_id="u-chat",
        agent_type="chat",
        llm_adapter=_FakeLLMAdapter(),
        prompt_context_assembler=None,  # type: ignore[arg-type]
        prompt_context_renderer=None,  # type: ignore[arg-type]
    )

    raw = "第一段总览。1. 项目概况与布局整体说明2. 技术栈说明- FastAPI- React3. 总结"
    formatted = service.format_explore_render_response(raw)

    assert "\n\n1. 项目概况与布局" in formatted
    assert "\n- FastAPI" in formatted
    assert "\n- React" in formatted


@pytest.mark.asyncio
async def test_plan_with_task_agent_logs_empty_response(monkeypatch) -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    warnings: list[str] = []

    async def _fake_call_llm(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return ""

    def _fake_warning(message, *args):  # type: ignore[no-untyped-def]
        warnings.append(message % args)

    monkeypatch.setattr(agent._prompt_service, "call_llm", _fake_call_llm)
    monkeypatch.setattr(planning_service_module.logger, "warning", _fake_warning)

    result = await agent._planning_service._plan_with_task_agent(
        user_message="Analyze repo architecture",
        history=[],
        orchestration_plan=OrchestrationPlan(
            default_leaf_type="Explore",
            allow_parallel=True,
        ),
    )

    assert result is None
    assert any("Task-agent planning returned empty response" in item for item in warnings)


@pytest.mark.asyncio
async def test_plan_with_task_agent_logs_non_executable_plan(monkeypatch) -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    warnings: list[str] = []

    async def _fake_call_llm(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return '{"summary":"planned","subtasks":[]}'

    def _fake_warning(message, *args):  # type: ignore[no-untyped-def]
        warnings.append(message % args)

    monkeypatch.setattr(agent._prompt_service, "call_llm", _fake_call_llm)
    monkeypatch.setattr(planning_service_module.logger, "warning", _fake_warning)

    result = await agent._planning_service._plan_with_task_agent(
        user_message="Analyze repo architecture",
        history=[],
        orchestration_plan=OrchestrationPlan(
            default_leaf_type="Explore",
            allow_parallel=True,
        ),
    )

    assert result is None
    assert any("Task-agent planning returned non-executable plan" in item for item in warnings)
