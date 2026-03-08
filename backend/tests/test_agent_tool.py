import asyncio

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

from magi.tools.builtin.agent_tool import (
    AgentTool,
    WorkerRunState,
    WORKER_AGENT_COMPLETED,
    WORKER_AGENT_PROGRESS,
)
from magi.agent.execution.function_calling import ExecutionOutcome
from magi.tools.schema import ToolExecutionContext


class _FakeLLMAdapter:
    model_name = "fake-model"


class _FakeToolRegistry:
    def list_tools(self):
        return ["glob", "grep", "file_read", "bash", "web-search", "agent"]


class _FakeFunctionCallingExecutor:
    def __init__(self, llm_adapter, tool_registry, skill_executor=None, tool_result_callback=None):
        self._tool_result_callback = tool_result_callback

    async def execute_with_tools(
        self,
        user_message,
        system_prompt,
        selected_tools,
        user_id,
        session_id=None,
        conversation_history=None,
        max_iterations=10,
        disable_thinking=True,
        intent="unknown",
        execution_agent_id="chat_agent",
        execution_workspace=None,
    ):
        _ = (
            system_prompt,
            selected_tools,
            user_id,
            session_id,
            conversation_history,
            max_iterations,
            disable_thinking,
            intent,
            execution_agent_id,
            execution_workspace,
        )
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
        await asyncio.sleep(0.01)
        if disable_thinking is False:
            content = (
                '{"result_status":"success","summary":"plan ready","findings":[{"title":"plan","detail":"created subtasks"}],'
                '"evidence":[{"path":"/tmp/plan.json","detail":"planner output"}],'
                '"gaps":[],"next_steps":["launch subtasks"],"failure_reason":null,'
                '"subtasks":[{"description":"scan module","subagent_type":"Explore","prompt":"Inspect module layout","parallel_group":"g1"}]}'
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
    from magi.agent.workers import worker_manager as worker_manager_module

    monkeypatch.setattr(worker_manager_module, "FunctionCallingExecutor", _FakeFunctionCallingExecutor)
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
            "subagent_type": "Explore",
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
async def test_agent_tool_background_then_await(monkeypatch):
    from magi.agent.workers import worker_manager as worker_manager_module

    monkeypatch.setattr(worker_manager_module, "FunctionCallingExecutor", _FakeFunctionCallingExecutor)
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
    from magi.agent.workers import worker_manager as worker_manager_module

    monkeypatch.setattr(worker_manager_module, "FunctionCallingExecutor", _FakeFunctionCallingExecutor)
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
                    "subagent_type": "Explore",
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
    assert selected_tools == ["glob", "grep", "file_read"]
    assert "bash" not in selected_tools
    assert tool.schema is not None
    assert tool.schema.timeout == 300


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
    assert "Always exclude node_modules, dist, build, .git, .venv, __pycache__, and lock files." in prompt
    assert "Any prose, markdown, code fences, or trailing commentary will be treated as failure." in prompt


def test_agent_tool_explore_prompt_uses_backend_profile():
    tool = AgentTool()
    prompt = tool._build_worker_system_prompt(
        worker_id="worker_test",
        subagent_type=tool.TYPE_EXPLORE,
        description="Analyze backend modules",
        selected_tools=["glob", "grep", "file_read"],
    )

    assert "SUBTASK PROFILE: Backend Modules" in prompt
    assert "Start from backend runtime/bootstrap/app entry files" in prompt
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
async def test_empty_worker_result_is_marked_failed(monkeypatch):
    from magi.agent.workers import worker_manager as worker_manager_module

    class _EmptyExecutor:
        def __init__(self, *args, **kwargs):
            _ = (args, kwargs)

        async def execute_with_tools(self, **kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            return ExecutionOutcome(
                status="failed",
                content="",
                failure_reason="EMPTY_FINAL_RESPONSE",
                iterations=2,
            )

    monkeypatch.setattr(worker_manager_module, "FunctionCallingExecutor", _EmptyExecutor)
    tool = AgentTool()
    tool.configure(llm_adapter=_FakeLLMAdapter(), tool_registry_instance=_FakeToolRegistry())

    async def _fake_publish(run_state, event_type, internal_payload, public_payload=None):
        _ = (run_state, event_type, internal_payload, public_payload)

    monkeypatch.setattr(tool._manager, "_publish_worker_fact", _fake_publish)

    result = await tool.execute(
        parameters={
            "action": "launch",
            "subagent_type": "Explore",
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
    from magi.agent.workers import worker_manager as worker_manager_module

    class _InvalidJsonExecutor:
        def __init__(self, *args, **kwargs):
            _ = (args, kwargs)

        async def execute_with_tools(self, **kwargs):  # type: ignore[no-untyped-def]
            _ = kwargs
            return ExecutionOutcome(
                status="completed",
                content="Here is the result:\n```json\n{\"summary\":\"oops\"}\n```",
                iterations=1,
            )

    monkeypatch.setattr(worker_manager_module, "FunctionCallingExecutor", _InvalidJsonExecutor)
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
            "subagent_type": "Explore",
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
    assert result.error == "Worker did not return valid JSON"
    assert published_events[-1][0] == "WORKER_AGENT_FAILED"
    assert published_events[-1][1] == "INVALID_WORKER_RESULT"


@pytest.mark.asyncio
async def test_structured_failed_worker_result_is_not_marked_completed(monkeypatch):
    from magi.agent.workers import worker_manager as worker_manager_module

    class _StructuredFailureExecutor:
        def __init__(self, *args, **kwargs):
            _ = (args, kwargs)

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
                iterations=1,
            )

    monkeypatch.setattr(worker_manager_module, "FunctionCallingExecutor", _StructuredFailureExecutor)
    tool = AgentTool()
    tool.configure(llm_adapter=_FakeLLMAdapter(), tool_registry_instance=_FakeToolRegistry())

    published_events = []

    async def _fake_publish(run_state, event_type, internal_payload, public_payload=None):
        _ = (internal_payload, public_payload)
        published_events.append((event_type, run_state.failure_reason, run_state.status))

    monkeypatch.setattr(tool._manager, "_publish_worker_fact", _fake_publish)

    result = await tool.execute(
        parameters={
            "action": "launch",
            "subagent_type": "Explore",
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
    assert published_events[-1] == ("WORKER_AGENT_FAILED", "PATH_NOT_FOUND", "failed")
