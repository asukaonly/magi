"""Exercise contextual admission with real tool schemas and scoped runtime stores."""

from types import SimpleNamespace

import pytest

from agent.agent_run_helpers import run_agent
from agent.permission_helpers import AllowAllPermissionGateway
from magi.agent.background import (
    BackgroundTask,
    BackgroundTaskSpec,
    BackgroundTaskStatus,
    BackgroundTaskStore,
)
from magi.agent.execution.capability_resolver import CapabilityResolver
from magi.agent.execution.completion_policy import CompletionPolicy
from magi.agent.execution.function_calling import FunctionCallingOrchestrator, ToolCall
from magi.agent.execution.function_calling.run_input import AgentRunRequest
from magi.agent.execution.function_calling.step_models import FunctionCallingStepState
from magi.agent.execution.function_calling.tool_exposure import refresh_contextual_tools
from magi.agent.execution.function_calling.tools import build_tools_parameter
from magi.agent.execution.model_capabilities import ModelCapabilityProfile
from magi.agent.execution.reasoning import ReasoningState
from magi.agent.turn_input import UserTurnInput
from magi.config.models import ThinkingDepth
from magi.control.session_store import ControlSessionStore
from magi.tools.core_tools import CORE_TOOL_CLASSES
from magi.tools.registry import ToolRegistry
from magi.tools.schema import ToolExecutionContext


@pytest.fixture
def runtime(monkeypatch, runtime_paths_with_schema):
    registry = ToolRegistry()
    for tool_class in CORE_TOOL_CLASSES:
        registry.register(tool_class)
    control_store = ControlSessionStore()
    task_store = BackgroundTaskStore(
        db_path=str(runtime_paths_with_schema.background_tasks_db_path)
    )
    monkeypatch.setattr(
        "magi.agent.execution.function_calling.tool_exposure.resolve_control_session_store",
        lambda: control_store,
    )
    monkeypatch.setattr(
        "magi.control.tools.plan_mode_tool.resolve_control_session_store",
        lambda: control_store,
    )
    monkeypatch.setattr(
        "magi.agent.execution.function_calling.tool_exposure.resolve_background_task_manager",
        lambda: SimpleNamespace(store=task_store),
    )
    host = SimpleNamespace(
        tool_registry=registry,
        _build_tools_parameter=lambda names: build_tools_parameter(registry, names),
        provider_bridge=SimpleNamespace(resolve_effective_reasoning_depth=lambda depth: depth),
    )
    return host, control_store, task_store


def _request(**kwargs):
    return AgentRunRequest.headless(
        turn=UserTurnInput(text="Continue the task"),
        selected_tools=[],
        user_id="alice",
        session_id="session-a",
        execution_preset="chat",
        model_context_port=None,
        **kwargs,
    )


def _state(host, request, selected=None):
    names = (
        selected
        if selected is not None
        else list(CapabilityResolver(host.tool_registry).resolve().initial_exposed_tools)
    )
    return FunctionCallingStepState(
        messages=[],
        effective_system_prompt=request.system_prompt,
        selected_tool_names=names,
        tools=host._build_tools_parameter(names),
        reasoning_policy=request.reasoning_policy,
        reasoning_state=ReasoningState.start(request.reasoning_policy),
    )


async def _task(store, *, user="alice", session="session-a", status=BackgroundTaskStatus.RUNNING):
    task = BackgroundTask.new(
        BackgroundTaskSpec(
            user_id=user,
            session_id=session,
            origin_turn_id="turn-a",
            title="Research",
            goal="Prepare a report",
        )
    )
    task.status = status
    await store.create_task(task)
    return task


@pytest.mark.asyncio
async def test_plan_exit_follows_live_session_state(runtime):
    host, store, _ = runtime
    request = _request()
    state = _state(host, request)
    await store.enter_plan_mode("session-b")
    await refresh_contextual_tools(host, state=state, run_input=request)
    assert "exit_plan_mode" not in state.selected_tool_names
    await store.enter_plan_mode("session-a")
    await refresh_contextual_tools(host, state=state, run_input=request)
    assert "exit_plan_mode" in state.contextual_resident_tools
    assert "exit_plan_mode" in {item["function"]["name"] for item in state.tools}
    await store.exit_plan_mode("session-a")
    await refresh_contextual_tools(host, state=state, run_input=request)
    assert "exit_plan_mode" not in state.selected_tool_names


@pytest.mark.asyncio
async def test_reasoning_control_requires_reachable_provider_change(runtime):
    host, _, _ = runtime
    request = _request()
    state = _state(host, request)
    host.provider_bridge.resolve_effective_reasoning_depth = lambda depth: ThinkingDepth.NONE
    await refresh_contextual_tools(host, state=state, run_input=request)
    assert "request_reasoning_depth" not in state.selected_tool_names
    # Adjacent settings may collapse, but MAX is reachable within the budget.
    host.provider_bridge.resolve_effective_reasoning_depth = lambda depth: (
        ThinkingDepth.MAX if depth is ThinkingDepth.MAX else ThinkingDepth.HIGH
    )
    await refresh_contextual_tools(host, state=state, run_input=request)
    assert "request_reasoning_depth" in state.selected_tool_names
    assert state.reasoning_state.escalation_count == 0
    while state.reasoning_state.escalate(request.reasoning_policy, reason="test"):
        pass
    await refresh_contextual_tools(host, state=state, run_input=request)
    assert "request_reasoning_depth" not in state.selected_tool_names


@pytest.mark.asyncio
async def test_task_admission_uses_owner_session_and_nonterminal_status(runtime):
    host, _, store = runtime
    request = _request()
    state = _state(host, request)
    await _task(store, user="bob")
    await _task(store, session="session-b")
    await _task(store, status=BackgroundTaskStatus.SUCCEEDED)
    await refresh_contextual_tools(host, state=state, run_input=request)
    assert "task_query" not in state.selected_tool_names
    own = await _task(store, status=BackgroundTaskStatus.SUSPENDED_WAITING_USER)
    await refresh_contextual_tools(host, state=state, run_input=request)
    assert "task_query" in state.selected_tool_names
    own.status = BackgroundTaskStatus.SUCCEEDED
    await store.update_task(own)
    await refresh_contextual_tools(host, state=state, run_input=request)
    assert "task_query" in state.selected_tool_names
    fresh_state = _state(host, request)
    await refresh_contextual_tools(host, state=fresh_state, run_input=request)
    assert "task_query" not in fresh_state.selected_tool_names


@pytest.mark.asyncio
async def test_child_and_toolless_models_do_not_gain_chat_controls(runtime):
    host, store, tasks = runtime
    await store.enter_plan_mode("session-a")
    await _task(tasks)
    child = _request(parent_run_id="parent")
    state = _state(host, child, selected=["file_read"])
    await refresh_contextual_tools(host, state=state, run_input=child)
    assert state.selected_tool_names == ["file_read"]
    toolless = _request(model_capabilities=ModelCapabilityProfile(supports_tool_calls=False))
    state = _state(host, toolless, selected=[])
    await refresh_contextual_tools(host, state=state, run_input=toolless)
    assert state.tools == []


@pytest.mark.asyncio
async def test_plan_mode_allows_discovery_and_queries_but_blocks_writes(runtime):
    _, store, _ = runtime
    await store.enter_plan_mode("session-a")
    for name in (
        "web-search",
        "web-fetch",
        "find-relevant-tools",
        "current_time",
        "environment_query",
        "task_query",
        "trace_query",
    ):
        assert store.plan_allows("session-a", name)
    for name in ("file_write", "bash", "batch_create", "schedule"):
        assert not store.plan_allows("session-a", name)


@pytest.mark.asyncio
async def test_plan_tools_update_actual_next_model_catalog(runtime, monkeypatch):
    host, store, _ = runtime
    orchestrator = FunctionCallingOrchestrator(
        tool_registry=host.tool_registry,
        llm_adapter=SimpleNamespace(model_name="fake-model", provider_name="fake-provider"),
        permission_gateway=AllowAllPermissionGateway(),
    )
    snapshots = []

    async def model_call(**kwargs):
        snapshots.append({tool["function"]["name"] for tool in kwargs["tools"]})
        if len(snapshots) == 3:
            return {"content": "Plan is ready."}
        name = "enter_plan_mode" if len(snapshots) == 1 else "exit_plan_mode"
        arguments = {} if len(snapshots) == 1 else {"plan": "Inspect, then implement."}
        call = ToolCall(id=f"call-{len(snapshots)}", name=name, arguments=arguments)
        return {
            "assistant_message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": name, "arguments": "{}"},
                    }
                ],
            },
            "tool_calls": [call],
        }

    monkeypatch.setattr(orchestrator, "_call_llm_with_tools", model_call)
    outcome = await run_agent(
        orchestrator,
        turn=UserTurnInput(text="Plan the task"),
        system_prompt="Help plan the task.",
        selected_tools=["enter_plan_mode"],
        user_id="alice",
        session_id="session-a",
        max_iterations=4,
        completion_policy=CompletionPolicy(require_unknown_effect_validation=False),
    )
    assert outcome.status == "completed"
    assert len(snapshots) == 3
    assert "exit_plan_mode" not in snapshots[0]
    assert "exit_plan_mode" in snapshots[1]
    assert "exit_plan_mode" not in snapshots[2]
    assert not store.plan_state("session-a").active


@pytest.mark.asyncio
async def test_history_query_stays_discoverable_without_active_tasks(runtime):
    host, _, _ = runtime
    discovery = host.tool_registry.get_tool("find-relevant-tools")
    result = await discovery.execute(
        {"query": "task_query background task status result summary", "limit": 1},
        ToolExecutionContext(
            agent_id="chat", env_vars={"user_id": "alice", "session_id": "session-a"}
        ),
    )
    assert result.success
    assert result.data["recommended_tools"] == ["task_query"]
    for name in ("exit_plan_mode", "request_reasoning_depth"):
        result = await discovery.execute(
            {"query": name, "limit": 2},
            ToolExecutionContext(agent_id="chat"),
        )
        assert name not in result.data["recommended_tools"]


@pytest.mark.asyncio
async def test_checkpoint_preserves_discovery_and_refreshes_contextual_controls(
    runtime, monkeypatch
):
    from magi.agent.execution.checkpoint import AgentRunCheckpoint

    host, _, _ = runtime
    request = _request()
    state = _state(
        host, request, selected=["enter_plan_mode", "exit_plan_mode", "trace_query", "task_query"]
    )
    checkpoint = AgentRunCheckpoint(
        run_id="restored-run",
        messages=[],
        effective_system_prompt=request.system_prompt,
        tools=state.tools,
        selected_tool_names=state.selected_tool_names,
        iteration=2,
        reasoning_policy=state.reasoning_policy,
        reasoning_state=state.reasoning_state,
        tool_expansion_count=2,
    )
    orchestrator = FunctionCallingOrchestrator(
        tool_registry=host.tool_registry,
        llm_adapter=SimpleNamespace(model_name="fake-model", provider_name="fake-provider"),
        permission_gateway=AllowAllPermissionGateway(),
    )
    snapshots = []

    async def model_call(**kwargs):
        snapshots.append({tool["function"]["name"] for tool in kwargs["tools"]})
        return {"content": "Restored."}

    monkeypatch.setattr(orchestrator, "_call_llm_with_tools", model_call)
    outcome = await orchestrator.run(_request(checkpoint=checkpoint))
    assert outcome.status == "completed"
    assert outcome.iterations == 3
    assert {"trace_query", "task_query"}.issubset(snapshots[0])
    assert "exit_plan_mode" not in snapshots[0]


@pytest.mark.asyncio
async def test_deferred_tools_can_be_discovered_sequentially_in_one_run(runtime, monkeypatch):
    from magi.agent.batch.tools.batch_create_tool import BatchCreateTool

    host, _, _ = runtime
    host.tool_registry.register(BatchCreateTool)
    orchestrator = FunctionCallingOrchestrator(
        tool_registry=host.tool_registry,
        llm_adapter=SimpleNamespace(model_name="fake-model", provider_name="fake-provider"),
        permission_gateway=AllowAllPermissionGateway(),
    )
    snapshots = []

    async def model_call(**kwargs):
        names = {tool["function"]["name"] for tool in kwargs["tools"]}
        snapshots.append(names)
        if len(snapshots) == 3:
            return {"content": "Capabilities ready."}
        query = (
            "trace_query execution traces tool failures logs"
            if len(snapshots) == 1
            else "batch_create long-running batch job homogeneous items"
        )
        call = ToolCall(
            id=f"discover-{len(snapshots)}",
            name="find-relevant-tools",
            arguments={
                "query": query,
                "current_tools": sorted(names),
                "limit": 1,
            },
        )
        return {
            "assistant_message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": "{}"},
                    }
                ],
            },
            "tool_calls": [call],
        }

    monkeypatch.setattr(orchestrator, "_call_llm_with_tools", model_call)
    resolution = CapabilityResolver(host.tool_registry).resolve()
    outcome = await run_agent(
        orchestrator,
        turn=UserTurnInput(text="Find the tools for reviewing and repeating a job"),
        system_prompt="Help with the task.",
        selected_tools=list(resolution.initial_exposed_tools),
        user_id="alice",
        session_id="session-a",
        max_iterations=4,
    )
    assert outcome.status == "completed"
    assert not {"trace_query", "batch_create"} & snapshots[0]
    assert "trace_query" in snapshots[1]
    assert {"trace_query", "batch_create"}.issubset(snapshots[2])
