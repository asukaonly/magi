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
        return f"worker finished: {user_message}"


@pytest.mark.asyncio
async def test_agent_tool_launch_foreground(monkeypatch):
    from magi.tools.builtin import agent_tool as agent_tool_module

    monkeypatch.setattr(agent_tool_module, "FunctionCallingExecutor", _FakeFunctionCallingExecutor)
    tool = AgentTool()
    tool.configure(llm_adapter=_FakeLLMAdapter(), tool_registry_instance=_FakeToolRegistry())

    published_events = []

    async def _fake_publish(run_state, event_type, event_payload):
        _ = (run_state, event_payload)
        published_events.append(event_type)

    monkeypatch.setattr(tool, "_publish_worker_fact", _fake_publish)

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
    assert "worker finished" in result.data["result"]
    assert WORKER_AGENT_PROGRESS in published_events
    assert WORKER_AGENT_COMPLETED in published_events


@pytest.mark.asyncio
async def test_agent_tool_background_then_await(monkeypatch):
    from magi.tools.builtin import agent_tool as agent_tool_module

    monkeypatch.setattr(agent_tool_module, "FunctionCallingExecutor", _FakeFunctionCallingExecutor)
    tool = AgentTool()
    tool.configure(llm_adapter=_FakeLLMAdapter(), tool_registry_instance=_FakeToolRegistry())

    async def _fake_publish(run_state, event_type, event_payload):
        _ = (run_state, event_type, event_payload)

    monkeypatch.setattr(tool, "_publish_worker_fact", _fake_publish)

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
    from magi.tools.builtin import agent_tool as agent_tool_module

    monkeypatch.setattr(agent_tool_module, "FunctionCallingExecutor", _FakeFunctionCallingExecutor)
    tool = AgentTool()
    tool.configure(llm_adapter=_FakeLLMAdapter(), tool_registry_instance=_FakeToolRegistry())

    async def _fake_publish(run_state, event_type, event_payload):
        _ = (run_state, event_type, event_payload)

    monkeypatch.setattr(tool, "_publish_worker_fact", _fake_publish)

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
