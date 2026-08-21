import asyncio
from pathlib import Path

try:
    import pytest
except ModuleNotFoundError:  # pragma: no cover

    class _Mark:
        @staticmethod
        def asyncio(func):
            return func

    class _PytestFallback:
        mark = _Mark()

    pytest = _PytestFallback()

from magi.agent.runtime_tools import (
    AgentTool,
    WorkerRunState,
    WORKER_AGENT_COMPLETED,
    WORKER_AGENT_PROGRESS,
)
from magi.agent.execution.function_calling import ExecutionOutcome
from magi.events.in_memory_backend import InMemoryMessageBusBackend
from magi.runtime_trace.store import RuntimeTraceStore
from magi.runtime_trace.subscribers.runtime_trace_subscriber import RuntimeTraceSubscriber
from magi.tools.schema import ToolExecutionContext


async def _flush_trace_bus(bus, subscriber) -> None:
    while True:
        stats = await bus.get_stats()
        if stats["queue_length"] == 0 and stats["active_dispatches"] == 0:
            break
        await asyncio.sleep(0.01)
    await subscriber.drain()


class _FakeLLMAdapter:
    model_name = "fake-model"


class _FakeToolRegistry:
    def list_tools(self):
        return [
            "glob",
            "grep",
            "file_read",
            "bash",
            "web-search",
            "find-relevant-tools",
            "agent",
        ]


class _FakeToolRegistryWithTodo:
    def list_tools(self):
        return [
            "glob",
            "grep",
            "file_read",
            "file_edit",
            "file_write",
            "file_list",
            "file_info",
            "verify",
            "bash",
            "todo_write",
            "agent",
        ]


class _FakeFunctionCallingOrchestrator:
    def __init__(
        self,
        llm_adapter,
        tool_registry,
        skill_runner=None,
        tool_result_callback=None,
        loop_event_callback=None,
        runtime_trace_store=None,
        scenario_llm_pool=None,
        active_model_provider=None,
        permission_gateway_provider=None,
    ):
        _ = (
            llm_adapter,
            tool_registry,
            skill_runner,
            scenario_llm_pool,
            active_model_provider,
            permission_gateway_provider,
        )
        self._tool_result_callback = tool_result_callback
        self._loop_event_callback = loop_event_callback
        self._runtime_trace_store = runtime_trace_store
        self.last_max_iterations = None
        self.last_cancel_token = None

    async def run(self, run_input):  # engine front door (ADR-0004 P4) → forwards
        return await self.execute_with_tools(**run_input.to_execute_kwargs())

    async def execute_with_tools(
        self,
        turn,
        system_prompt,
        selected_tools,
        user_id,
        session_id=None,
        session_run_id=None,
        session_run_revision=0,
        turn_id=None,
        conversation_history=None,
        session_summary=None,
        session_origin=None,
        reply_context=None,
        ephemeral_context=None,
        max_iterations=10,
        disable_thinking=True,
        intent="unknown",
        execution_agent_id="chat_agent",
        execution_workspace=None,
        llm_timeout_seconds=None,
        final_response_json_mode=False,
        thinking_depth=None,
        cancel_token=None,
        steer_inbox=None,
        detach_signal=None,
        control=None,
        route_decision=None,
    ):
        user_message = turn.text
        _ = (
            system_prompt,
            selected_tools,
            user_id,
            session_id,
            session_run_id,
            session_run_revision,
            turn_id,
            conversation_history,
            session_summary,
            session_origin,
            reply_context,
            ephemeral_context,
            disable_thinking,
            intent,
            execution_agent_id,
            execution_workspace,
            llm_timeout_seconds,
            final_response_json_mode,
            thinking_depth,
            steer_inbox,
            detach_signal,
            control,
            route_decision,
        )
        self.last_max_iterations = max_iterations
        self.last_cancel_token = cancel_token
        if self._tool_result_callback:
            await self._tool_result_callback(
                {
                    "tool_name": "glob",
                    "success": True,
                    "execution_time": 0.01,
                    "error": None,
                    "data": {"matches": 3},
                }
            )
        if self._loop_event_callback:
            await self._loop_event_callback(
                {
                    "stage": "final_response",
                    "iteration": 1,
                    "user_id": user_id,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "execution_agent_id": execution_agent_id,
                    "response_preview": user_message[:80],
                    "llm_trace": {
                        "provider": "openai",
                        "model": "fake-model",
                        "input_tokens": 30,
                        "output_tokens": 12,
                        "total_tokens": 42,
                        "thinking_enabled": not disable_thinking,
                        "duration_ms": 510,
                    },
                }
            )
        await asyncio.sleep(0.01)
        is_plan = thinking_depth is not None and getattr(
            thinking_depth, "value", str(thinking_depth)
        ) not in ("none", "")
        if is_plan:
            content = (
                '{"result_status":"success","summary":"plan ready","findings":[{"title":"plan","detail":"created subtasks"}],'
                '"evidence":[{"path":"/tmp/plan.json","detail":"planner output"}],'
                '"gaps":[],"next_steps":["launch subtasks"],"failure_reason":null,'
                '"subtasks":[{"description":"scan module","subagent_type":"CodeExplore","prompt":"Inspect module layout","parallel_group":"g1"}]}'
            )
        else:
            content = (
                '{"result_status":"success","summary":"worker finished","findings":[{"title":"done","detail":"'
                + user_message
                + '","path":"/tmp/example.py","why_it_matters":"confirms the bounded worker scope"}],'
                '"evidence":[{"path":"/tmp/example.py","detail":"validated path"}],'
                '"gaps":[],"next_steps":["report upstream"],"failure_reason":null}'
            )
        return ExecutionOutcome(
            status="completed",
            content=content,
            iterations=1,
        )


@pytest.mark.asyncio
async def test_agent_tool_launch_foreground(monkeypatch):
    from magi.agent.workers import worker_execution as worker_execution_module

    monkeypatch.setattr(
        worker_execution_module, "FunctionCallingOrchestrator", _FakeFunctionCallingOrchestrator
    )
    tool = AgentTool()
    tool.configure(llm_adapter=_FakeLLMAdapter(), tool_registry_instance=_FakeToolRegistry())

    published_events = []

    async def _fake_publish(run_state, event_type, internal_payload, public_payload=None):
        _ = (run_state, internal_payload, public_payload)
        published_events.append(event_type)

    monkeypatch.setattr(tool._manager, "_publish_worker_fact", _fake_publish)

    result = await tool.execute(
        parameters={
            "action": "launch",
            "subagent_type": "CodeExplore",
            "description": "scan auth flow",
            "prompt": "Locate token generation points",
            "run_in_background": False,
        },
        context=ToolExecutionContext(
            agent_id="chat:u-chat",
            workspace="/tmp",
            env_vars={"user_id": "u-chat", "session_id": "s-chat"},
            permissions=["authenticated"],
        ),
    )

    assert result.success is True
    assert result.data["status"] == "completed"
    assert result.data["result"]["summary"] == "worker finished"
    assert WORKER_AGENT_PROGRESS in published_events
    assert WORKER_AGENT_COMPLETED in published_events


@pytest.mark.asyncio
async def test_agent_tool_uses_30_iteration_default_for_workers(monkeypatch):
    from magi.agent.workers import worker_execution as worker_execution_module

    fake_orchestrators = []

    class _RecordingFunctionCallingOrchestrator(_FakeFunctionCallingOrchestrator):
        def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            super().__init__(*args, **kwargs)
            fake_orchestrators.append(self)

    monkeypatch.setattr(
        worker_execution_module,
        "FunctionCallingOrchestrator",
        _RecordingFunctionCallingOrchestrator,
    )
    tool = AgentTool()
    tool.configure(llm_adapter=_FakeLLMAdapter(), tool_registry_instance=_FakeToolRegistry())

    async def _fake_publish(run_state, event_type, internal_payload, public_payload=None):
        _ = (run_state, event_type, internal_payload, public_payload)

    monkeypatch.setattr(tool._manager, "_publish_worker_fact", _fake_publish)

    result = await tool.execute(
        parameters={
            "action": "launch",
            "subagent_type": "CodeExplore",
            "description": "scan auth flow",
            "prompt": "Locate token generation points",
            "run_in_background": False,
        },
        context=ToolExecutionContext(
            agent_id="chat:u-chat",
            workspace="/tmp",
            env_vars={"user_id": "u-chat", "session_id": "s-chat"},
            permissions=["authenticated"],
        ),
    )

    assert result.success is True
    assert fake_orchestrators
    assert fake_orchestrators[0].last_max_iterations == 30
    assert fake_orchestrators[0].last_cancel_token is not None


@pytest.mark.asyncio
async def test_agent_tool_persists_worker_trace_nodes_to_runtime_trace_store(
    monkeypatch,
    runtime_paths_with_schema,
):
    from magi.agent.workers import worker_execution as worker_execution_module

    monkeypatch.setattr(
        worker_execution_module, "FunctionCallingOrchestrator", _FakeFunctionCallingOrchestrator
    )
    tool = AgentTool()
    runtime_trace_store = RuntimeTraceStore(
        db_path=str(runtime_paths_with_schema.runtime_trace_db_path)
    )
    await runtime_trace_store.initialize()
    message_bus = InMemoryMessageBusBackend()
    await message_bus.start()
    trace_subscriber = RuntimeTraceSubscriber(
        event_bus=message_bus,
        trace_store=runtime_trace_store,
    )
    await trace_subscriber.start()

    try:
        tool.configure(
            llm_adapter=_FakeLLMAdapter(),
            tool_registry_instance=_FakeToolRegistry(),
            runtime_trace_store=runtime_trace_store,
            message_bus=message_bus,
        )

        async def _fake_publish(run_state, event_type, internal_payload, public_payload=None):
            _ = (run_state, event_type, internal_payload, public_payload)

        monkeypatch.setattr(tool._manager, "_publish_worker_fact", _fake_publish)

        result = await tool.execute(
            parameters={
                "action": "launch",
                "subagent_type": "CodeExplore",
                "description": "scan auth flow",
                "prompt": "Locate token generation points",
                "run_in_background": False,
                "orchestration_id": "orch-1",
                "subtask_id": "subtask-1",
                "turn_id": "turn-1",
            },
            context=ToolExecutionContext(
                agent_id="chat:u-chat",
                workspace="/tmp",
                env_vars={"user_id": "u-chat", "session_id": "s-chat"},
                permissions=["authenticated"],
            ),
        )
        await _flush_trace_bus(message_bus, trace_subscriber)

        dispatch_span = await runtime_trace_store.get_span("turn-1:worker_dispatch:subtask-1")
        attempt_span = await runtime_trace_store.get_span("turn-1:worker_attempt:subtask-1:1")
        worker_span = await runtime_trace_store.get_span("turn-1:worker:subtask-1:1")
        tool_call = await runtime_trace_store.get_tool_call("turn-1:worker_tool:subtask-1:1:glob")

        assert result.success is True
        assert dispatch_span is not None
        assert attempt_span is not None
        assert worker_span is not None
        assert tool_call is not None
    finally:
        await trace_subscriber.stop()
        await message_bus.stop()
        await runtime_trace_store.shutdown()


@pytest.mark.asyncio
async def test_agent_tool_background_then_await(monkeypatch):
    from magi.agent.workers import worker_execution as worker_execution_module

    monkeypatch.setattr(
        worker_execution_module, "FunctionCallingOrchestrator", _FakeFunctionCallingOrchestrator
    )
    tool = AgentTool()
    tool.configure(llm_adapter=_FakeLLMAdapter(), tool_registry_instance=_FakeToolRegistry())

    async def _fake_publish(run_state, event_type, internal_payload, public_payload=None):
        _ = (run_state, event_type, internal_payload, public_payload)

    monkeypatch.setattr(tool._manager, "_publish_worker_fact", _fake_publish)

    launch_result = await tool.execute(
        parameters={
            "action": "launch",
            "subagent_type": "Plan",
            "description": "design migration plan",
            "prompt": "Create a migration strategy with ordered steps.",
            "run_in_background": True,
        },
        context=ToolExecutionContext(
            agent_id="chat:u-chat",
            workspace="/tmp",
            env_vars={"user_id": "u-chat", "session_id": "s-chat"},
            permissions=["authenticated"],
        ),
    )
    assert launch_result.success is True
    worker_id = launch_result.data["worker_id"]

    status_result = await tool.execute(
        parameters={"action": "status", "worker_id": worker_id},
        context=ToolExecutionContext(
            agent_id="chat:u-chat",
            workspace="/tmp",
            env_vars={"user_id": "u-chat"},
            permissions=["authenticated"],
        ),
    )
    assert status_result.success is True
    assert status_result.data["status"] in {"running", "completed"}

    await_result = await tool.execute(
        parameters={"action": "await", "worker_id": worker_id, "timeout_seconds": 5},
        context=ToolExecutionContext(
            agent_id="chat:u-chat",
            workspace="/tmp",
            env_vars={"user_id": "u-chat"},
            permissions=["authenticated"],
        ),
    )
    assert await_result.success is True
    assert await_result.data["status"] == "completed"


@pytest.mark.asyncio
async def test_agent_tool_batch_workers(monkeypatch):
    from magi.agent.workers import worker_execution as worker_execution_module

    monkeypatch.setattr(
        worker_execution_module, "FunctionCallingOrchestrator", _FakeFunctionCallingOrchestrator
    )
    tool = AgentTool()
    tool.configure(llm_adapter=_FakeLLMAdapter(), tool_registry_instance=_FakeToolRegistry())

    async def _fake_publish(run_state, event_type, internal_payload, public_payload=None):
        _ = (run_state, event_type, internal_payload, public_payload)

    monkeypatch.setattr(tool._manager, "_publish_worker_fact", _fake_publish)

    launch_result = await tool.execute(
        parameters={
            "action": "launch",
            "workers": [
                {
                    "subagent_type": "CodeExplore",
                    "description": "scan API routes",
                    "prompt": "List all API route files and summarize endpoints.",
                },
                {
                    "subagent_type": "Plan",
                    "description": "design rollout plan",
                    "prompt": "Produce rollout steps and risks.",
                },
            ],
            "parallel": True,
            "run_in_background": False,
        },
        context=ToolExecutionContext(
            agent_id="chat:u-chat",
            workspace="/tmp",
            env_vars={"user_id": "u-chat", "session_id": "s-chat"},
            permissions=["authenticated"],
        ),
    )

    assert launch_result.success is True
    assert launch_result.data["worker_count"] == 2
    assert len(launch_result.data["workers"]) == 2
    assert all(item["status"] == "completed" for item in launch_result.data["workers"])

    worker_ids = [item["worker_id"] for item in launch_result.data["workers"]]
    status_result = await tool.execute(
        parameters={"action": "status", "worker_ids": worker_ids},
        context=ToolExecutionContext(
            agent_id="chat:u-chat",
            workspace="/tmp",
            env_vars={"user_id": "u-chat"},
            permissions=["authenticated"],
        ),
    )
    assert status_result.success is True
    assert status_result.data["worker_count"] == 2

    await_result = await tool.execute(
        parameters={"action": "await", "worker_ids": worker_ids, "timeout_seconds": 5},
        context=ToolExecutionContext(
            agent_id="chat:u-chat",
            workspace="/tmp",
            env_vars={"user_id": "u-chat"},
            permissions=["authenticated"],
        ),
    )
    assert await_result.success is True


@pytest.mark.asyncio
async def test_agent_tool_status_not_found():
    tool = AgentTool()
    tool.configure(llm_adapter=_FakeLLMAdapter(), tool_registry_instance=_FakeToolRegistry())

    result = await tool.execute(
        parameters={"action": "status", "worker_id": "missing"},
        context=ToolExecutionContext(
            agent_id="chat:u-chat",
            workspace="/tmp",
            env_vars={"user_id": "u-chat"},
            permissions=["authenticated"],
        ),
    )

    assert result.success is False
    assert result.error_code == "TOOL_NOT_FOUND"


@pytest.mark.asyncio
async def test_agent_tool_explore_uses_structured_tools():
    tool = AgentTool()
    tool.configure(llm_adapter=_FakeLLMAdapter(), tool_registry_instance=_FakeToolRegistry())

    selected_tools = tool._resolve_tools_for_type(tool.TYPE_EXPLORE)
    assert selected_tools == ["glob", "grep", "file_read", "find-relevant-tools"]
    assert "bash" not in selected_tools
    assert tool.schema is not None
    assert tool.schema.timeout == 300


def test_agent_tool_schema_uses_code_explore_worker_type():
    tool = AgentTool()

    assert tool.TYPE_EXPLORE == "CodeExplore"
    subagent_type_param = next(
        param for param in tool.schema.parameters if param.name == "subagent_type"
    )
    assert "CodeExplore" in subagent_type_param.enum
    assert "code-explore" in subagent_type_param.enum
    assert "Explore" not in subagent_type_param.enum
    assert "explore" not in subagent_type_param.enum


def test_agent_tool_explore_prompt_includes_scan_guardrails():
    tool = AgentTool()
    prompt = tool._build_worker_system_prompt(
        worker_id="worker_test",
        subagent_type=tool.TYPE_EXPLORE,
        description="explore structure",
        selected_tools=["glob", "grep", "file_read"],
    )

    assert "Never use '*' or '**/*' at repository root." in prompt
    assert "default to recursive=false" in prompt
    assert "max_results <= 200" in prompt
    assert (
        "Always exclude node_modules, dist, build, .git, .venv, __pycache__, and lock files."
        in prompt
    )
    assert (
        "Any prose, markdown, code fences, or trailing commentary will be treated as failure."
        in prompt
    )


def test_agent_tool_explore_prompt_uses_backend_profile():
    tool = AgentTool()
    prompt = tool._build_worker_system_prompt(
        worker_id="worker_test",
        subagent_type=tool.TYPE_EXPLORE,
        description="Analyze backend modules",
        selected_tools=["glob", "grep", "file_read"],
    )

    assert "SUBTASK PROFILE: Backend Modules" in prompt
    assert "Start from backend bootstrap/backend.py and app entry files" in prompt
    assert "Do not drift into frontend structure or docs" in prompt


def test_agent_tool_explore_prompt_uses_layout_profile():
    tool = AgentTool()
    prompt = tool._build_worker_system_prompt(
        worker_id="worker_test",
        subagent_type=tool.TYPE_EXPLORE,
        description="Map repository layout",
        selected_tools=["glob", "grep", "file_read"],
    )

    assert "SUBTASK PROFILE: Repository Layout" in prompt
    assert "Start with immediate children of the repository root" in prompt
    assert "Prefer directory and manifest evidence" in prompt


def test_agent_tool_prompt_includes_execution_environment():
    tool = AgentTool()
    prompt = tool._build_worker_system_prompt(
        worker_id="worker_test",
        subagent_type=tool.TYPE_EXPLORE,
        description="Analyze backend modules",
        selected_tools=["glob", "grep", "file_read"],
        execution_workspace="~/code/magi",
    )

    assert "Execution environment:" in prompt
    assert "Workspace root:" in prompt
    assert "Home directory:" in prompt
    assert "Operating system:" in prompt
    assert "Interpret '~' as:" in prompt
    assert "Do not invent alternative Linux-style or macOS-style home paths" in prompt


def test_agent_tool_general_prompt_matches_validator_schema():
    tool = AgentTool()
    prompt = tool._build_worker_system_prompt(
        worker_id="worker_test",
        subagent_type=tool.TYPE_GENERAL,
        description="Compare memory systems",
        selected_tools=["file_read", "grep"],
    )

    assert '"findings":[{"title":"string","detail":"string"}]' in prompt
    assert '"evidence":[{"path":"string","detail":"string"}]' in prompt
    assert '"records":[{"field":"value"}]' in prompt
    assert "Never return a top-level JSON array." in prompt


def test_agent_tool_explore_prompt_requires_anchor_and_claim_validation():
    tool = AgentTool()
    prompt = tool._build_worker_system_prompt(
        worker_id="worker_explore",
        subagent_type=tool.TYPE_EXPLORE,
        description="Analyze backend orchestration flow",
        selected_tools=["glob", "grep", "file_read"],
    )

    assert "Identify the most concrete likely anchor first" in prompt
    assert "If you mention a file, symbol, route, flag, or config key in findings" in prompt


def test_agent_tool_plan_prompt_requires_anchor_first_decomposition():
    tool = AgentTool()
    prompt = tool._build_worker_system_prompt(
        worker_id="worker_plan",
        subagent_type=tool.TYPE_PLAN,
        description="Plan bounded subtasks for backend tracing",
        selected_tools=["glob", "grep", "file_read"],
    )

    assert "Start from the most concrete anchor or owning code path you can identify" in prompt
    assert "Avoid generic subtasks like gathering context or summarizing risks" in prompt
    assert (
        "If you name a file, symbol, route, flag, or config key in findings or evidence" in prompt
    )


def test_agent_tool_prompt_defaults_to_managed_workspace_when_missing(
    monkeypatch,
    tmp_path: Path,
):
    from magi.agent.workers import worker_prompting as worker_prompting_module

    fallback_cwd = tmp_path / "cwd"
    managed_workspace = tmp_path / "managed-chat-workspace"
    fallback_cwd.mkdir()
    managed_workspace.mkdir()

    monkeypatch.chdir(fallback_cwd)
    monkeypatch.setattr(
        worker_prompting_module,
        "get_default_chat_workspace_path",
        lambda: str(managed_workspace),
        raising=False,
    )

    tool = AgentTool()
    prompt = tool._build_worker_system_prompt(
        worker_id="worker_test",
        subagent_type=tool.TYPE_EXPLORE,
        description="Analyze backend modules",
        selected_tools=["glob", "grep", "file_read"],
        execution_workspace=None,
    )

    assert f"Workspace root: {managed_workspace.resolve()}" in prompt
    assert f"Workspace root: {fallback_cwd.resolve()}" not in prompt


@pytest.mark.asyncio
async def test_await_timeout_does_not_cancel_worker_task():
    tool = AgentTool()
    tool.configure(llm_adapter=_FakeLLMAdapter(), tool_registry_instance=_FakeToolRegistry())

    async def _long_running_task():
        await asyncio.sleep(0.5)

    run_state = WorkerRunState(
        worker_id="worker_timeout_check",
        subagent_type=tool.TYPE_EXPLORE,
        description="timeout behavior check",
        prompt="noop",
        orchestration_id=None,
        subtask_id=None,
        parent_task_agent_type="chat",
        parent_task_agent_id="u-chat",
        target_task_agent_type="chat",
        target_task_agent_id="u-chat",
        user_id="u-chat",
        session_id="s-chat",
        turn_id=None,
        created_at=0.0,
        updated_at=0.0,
    )
    run_state.task = asyncio.create_task(_long_running_task())
    tool._runs[run_state.worker_id] = run_state

    result = await tool._await_worker(run_state.worker_id, timeout_seconds=0)
    assert result.success is False
    assert result.error_code == "TIMEOUT"
    assert run_state.task is not None
    assert not run_state.task.cancelled()
    assert not run_state.task.done()

    run_state.task.cancel()
    try:
        await run_state.task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_cancel_run_workers_prefers_cooperative_token():
    from magi.agent.cancel import EventCancelToken

    tool = AgentTool()
    tool.configure(llm_adapter=_FakeLLMAdapter(), tool_registry_instance=_FakeToolRegistry())
    cancel_token = EventCancelToken()
    observed_cancel = False

    async def _cooperative_task():
        nonlocal observed_cancel
        await cancel_token.wait()
        observed_cancel = True

    run_state = WorkerRunState(
        worker_id="worker_cancel_check",
        subagent_type=tool.TYPE_EXPLORE,
        description="cancel behavior check",
        prompt="noop",
        orchestration_id=None,
        subtask_id=None,
        parent_task_agent_type="chat",
        parent_task_agent_id="u-chat",
        target_task_agent_type="chat",
        target_task_agent_id="u-chat",
        user_id="u-chat",
        session_id="s-chat",
        turn_id=None,
        run_id="run-1",
        run_revision=2,
        created_at=0.0,
        updated_at=0.0,
        cancel_token=cancel_token,
    )
    run_state.task = asyncio.create_task(_cooperative_task())
    tool._runs[run_state.worker_id] = run_state

    cancelled_ids = await tool._manager.cancel_run_workers(
        session_id="s-chat",
        run_id="run-1",
        run_revision=2,
        reason="test_cancel",
    )

    assert cancelled_ids == ["worker_cancel_check"]
    assert observed_cancel is True
    assert run_state.task.done()
    assert not run_state.task.cancelled()


@pytest.mark.asyncio
async def test_empty_worker_result_is_marked_failed(monkeypatch):
    from magi.agent.workers import worker_execution as worker_execution_module

    class _EmptyExecutor:
        def __init__(self, *args, **kwargs):
            _ = (args, kwargs)

        async def run(self, run_input):  # engine front door (ADR-0004 P4) → forwards
            return await self.execute_with_tools(**run_input.to_execute_kwargs())

        async def execute_with_tools(self, **kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            return ExecutionOutcome(
                status="failed",
                content="",
                failure_reason="EMPTY_FINAL_RESPONSE",
                iterations=2,
            )

    monkeypatch.setattr(worker_execution_module, "FunctionCallingOrchestrator", _EmptyExecutor)
    tool = AgentTool()
    tool.configure(llm_adapter=_FakeLLMAdapter(), tool_registry_instance=_FakeToolRegistry())

    async def _fake_publish(run_state, event_type, internal_payload, public_payload=None):
        _ = (run_state, event_type, internal_payload, public_payload)

    monkeypatch.setattr(tool._manager, "_publish_worker_fact", _fake_publish)

    result = await tool.execute(
        parameters={
            "action": "launch",
            "subagent_type": "CodeExplore",
            "description": "scan auth flow",
            "prompt": "Locate token generation points",
            "run_in_background": False,
        },
        context=ToolExecutionContext(
            agent_id="chat:u-chat",
            workspace="/tmp",
            env_vars={"user_id": "u-chat", "session_id": "s-chat"},
            permissions=["authenticated"],
        ),
    )

    assert result.success is False
    assert result.data["status"] == "failed"
    assert result.data["failure_reason"] == "EMPTY_FINAL_RESPONSE"


@pytest.mark.asyncio
async def test_invalid_json_worker_result_is_marked_failed(monkeypatch):
    from magi.agent.workers import worker_execution as worker_execution_module

    class _InvalidJsonExecutor:
        def __init__(self, *args, **kwargs):
            _ = (args, kwargs)

        async def run(self, run_input):  # engine front door (ADR-0004 P4) → forwards
            return await self.execute_with_tools(**run_input.to_execute_kwargs())

        async def execute_with_tools(self, **kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            return ExecutionOutcome(
                status="completed",
                content='Here is the result:\n```json\n{"summary":"oops"}\n```',
                iterations=1,
            )

    monkeypatch.setattr(
        worker_execution_module, "FunctionCallingOrchestrator", _InvalidJsonExecutor
    )
    tool = AgentTool()
    tool.configure(llm_adapter=_FakeLLMAdapter(), tool_registry_instance=_FakeToolRegistry())

    published_events = []

    async def _fake_publish(run_state, event_type, internal_payload, public_payload=None):
        _ = (internal_payload, public_payload)
        published_events.append((event_type, run_state.failure_reason, run_state.error))

    monkeypatch.setattr(tool._manager, "_publish_worker_fact", _fake_publish)

    result = await tool.execute(
        parameters={
            "action": "launch",
            "subagent_type": "CodeExplore",
            "description": "scan auth flow",
            "prompt": "Locate token generation points",
            "run_in_background": False,
        },
        context=ToolExecutionContext(
            agent_id="chat:u-chat",
            workspace="/tmp",
            env_vars={"user_id": "u-chat", "session_id": "s-chat"},
            permissions=["authenticated"],
        ),
    )

    assert result.success is False
    assert result.data["status"] == "failed"
    assert result.data["failure_reason"] == "INVALID_WORKER_RESULT"
    assert result.error == "Worker result is missing required fields"
    assert published_events[-1][0] == "WORKER_AGENT_FAILED"
    assert published_events[-1][1] == "INVALID_WORKER_RESULT"


@pytest.mark.asyncio
async def test_embedded_json_worker_result_is_accepted(monkeypatch):
    from magi.agent.workers import worker_execution as worker_execution_module

    class _EmbeddedJsonExecutor:
        def __init__(self, *args, **kwargs):
            _ = (args, kwargs)

        async def run(self, run_input):  # engine front door (ADR-0004 P4) → forwards
            return await self.execute_with_tools(**run_input.to_execute_kwargs())

        async def execute_with_tools(self, **kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            return ExecutionOutcome(
                status="completed",
                content=(
                    'Result:\n```json\n{"result_status":"success","summary":"done",'
                    '"findings":[{"title":"file","detail":"checked",'
                    '"path":"/tmp/a.py","why_it_matters":"evidence"}],'
                    '"evidence":[{"path":"/tmp/a.py","detail":"checked"}],'
                    '"gaps":[],"next_steps":[],"failure_reason":null}\n```'
                ),
                iterations=1,
            )

    monkeypatch.setattr(
        worker_execution_module, "FunctionCallingOrchestrator", _EmbeddedJsonExecutor
    )
    tool = AgentTool()
    tool.configure(llm_adapter=_FakeLLMAdapter(), tool_registry_instance=_FakeToolRegistry())

    async def _fake_publish(run_state, event_type, internal_payload, public_payload=None):
        _ = (run_state, event_type, internal_payload, public_payload)

    monkeypatch.setattr(tool._manager, "_publish_worker_fact", _fake_publish)

    result = await tool.execute(
        parameters={
            "action": "launch",
            "subagent_type": "CodeExplore",
            "description": "scan auth flow",
            "prompt": "Locate token generation points",
            "run_in_background": False,
        },
        context=ToolExecutionContext(
            agent_id="chat:u-chat",
            workspace="/tmp",
            env_vars={"user_id": "u-chat", "session_id": "s-chat"},
            permissions=["authenticated"],
        ),
    )

    assert result.success is True
    assert result.data["status"] == "completed"
    assert result.data["result"]["summary"] == "done"


def test_coding_worker_tool_profile_excludes_todo_write() -> None:
    tool = AgentTool()
    tool.configure(
        llm_adapter=_FakeLLMAdapter(),
        tool_registry_instance=_FakeToolRegistryWithTodo(),
    )

    selected_tools = tool._resolve_tools_for_type("Coding")

    assert "todo_write" not in selected_tools
    assert "file_write" in selected_tools


@pytest.mark.asyncio
async def test_structured_failed_worker_result_is_not_marked_completed(monkeypatch):
    from magi.agent.workers import worker_execution as worker_execution_module

    class _StructuredFailureExecutor:
        def __init__(self, *args, **kwargs):
            _ = (args, kwargs)

        async def run(self, run_input):  # engine front door (ADR-0004 P4) → forwards
            return await self.execute_with_tools(**run_input.to_execute_kwargs())

        async def execute_with_tools(self, **kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            return ExecutionOutcome(
                status="completed",
                content=(
                    '{"result_status":"failed","summary":"path did not exist",'
                    '"findings":[],"evidence":[],"gaps":["Target path was missing"],'
                    '"next_steps":["Verify the repository path"],'
                    '"failure_reason":"PATH_NOT_FOUND"}'
                ),
                tool_failures=[
                    {
                        "tool_name": "web-search",
                        "error_code": "PROVIDER_NOT_CONFIGURED",
                        "error": "Requested search provider is not configured.",
                    }
                ],
                iterations=1,
            )

    monkeypatch.setattr(
        worker_execution_module, "FunctionCallingOrchestrator", _StructuredFailureExecutor
    )
    tool = AgentTool()
    tool.configure(llm_adapter=_FakeLLMAdapter(), tool_registry_instance=_FakeToolRegistry())

    published_events = []

    async def _fake_publish(run_state, event_type, internal_payload, public_payload=None):
        _ = public_payload
        published_events.append(
            (event_type, run_state.failure_reason, run_state.status, internal_payload)
        )

    monkeypatch.setattr(tool._manager, "_publish_worker_fact", _fake_publish)

    result = await tool.execute(
        parameters={
            "action": "launch",
            "subagent_type": "CodeExplore",
            "description": "map repo",
            "prompt": "Inspect repository layout",
            "run_in_background": False,
        },
        context=ToolExecutionContext(
            agent_id="chat:u-chat",
            workspace="/tmp",
            env_vars={"user_id": "u-chat", "session_id": "s-chat"},
            permissions=["authenticated"],
        ),
    )

    assert result.success is False
    assert result.data["status"] == "failed"
    assert result.data["failure_reason"] == "PATH_NOT_FOUND"
    assert published_events[-1][:3] == ("WORKER_AGENT_FAILED", "PATH_NOT_FOUND", "failed")
    assert published_events[-1][3]["tool_failures"][0]["error_code"] == "PROVIDER_NOT_CONFIGURED"
