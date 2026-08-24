"""Regression tests for worker-start rejection at public execution boundaries."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from magi.agent.execution.task_budget import task_execution_budget_scope
from magi.agent.runtime.contracts import FactRecord
from magi.agent.runtime.task_agent import TaskAgent
from magi.agent.runtime.types import TaskAgentType
from magi.agent.runtime_tools import AgentTool
from magi.tools.registry import ToolRegistry
from magi.tools.schema import ToolExecutionContext, ToolResult


class _EmptyWorkerToolRegistry:
    @staticmethod
    def list_tools() -> list[str]:
        return []


def _tool_context() -> ToolExecutionContext:
    return ToolExecutionContext(
        agent_id="chat:test-user",
        workspace=".",
        env_vars={
            "user_id": "test-user",
            "session_id": "test-session",
            "run_id": "cancelled-run",
            "run_revision": "7",
        },
        permissions=["authenticated"],
    )


def _launch_parameters() -> dict[str, object]:
    return {
        "action": "launch",
        "preset": "read_only",
        "description": "inspect cancellation",
        "prompt": "Do not start after the parent run was cancelled.",
    }


def _configured_registry() -> tuple[ToolRegistry, AgentTool]:
    registry = ToolRegistry()
    registry.register(AgentTool)
    tool = registry.get_tool("agent")
    assert isinstance(tool, AgentTool)
    tool.configure(
        llm_adapter=SimpleNamespace(model_name="fake-worker"),
        tool_registry_instance=_EmptyWorkerToolRegistry(),  # type: ignore[arg-type]
    )
    return registry, tool


async def _add_tombstone(tool: AgentTool) -> None:
    await tool._manager.cancel_run_workers(
        session_id="test-session",
        run_id="cancelled-run",
        run_revision=7,
        reason="parent_run_cancelled",
    )


@pytest.mark.asyncio
async def test_registry_returns_cancelled_result_for_late_worker_start() -> None:
    registry, tool = _configured_registry()
    await _add_tombstone(tool)

    async with task_execution_budget_scope(max_worker_launches=1) as budget:
        result = await registry.execute(
            "agent",
            _launch_parameters(),
            _tool_context(),
        )

    assert result.success is False
    assert result.error_code == "CANCELLED"
    assert result.data == {"reason": "run_cancelled_before_worker_start"}
    assert tool._manager._runs == {}
    assert tool._manager._pending_runs == {}
    assert budget.worker_launches == 0


class _RegistryCallingTaskAgent(TaskAgent):
    def __init__(self, registry: ToolRegistry) -> None:
        super().__init__(TaskAgentType.CHAT, "actor-survival", queue_maxsize=4)
        self._registry = registry
        self.results: list[ToolResult | str] = []
        self.result_available = asyncio.Event()

    async def call_llm(self, context, llm_params):  # type: ignore[no-untyped-def]
        _ = llm_params
        latest_fact = context.latest_fact
        if latest_fact.payload["kind"] == "cancelled_launch":
            return await self._registry.execute(
                "agent",
                _launch_parameters(),
                _tool_context(),
            )
        return "second-fact-processed"

    async def parse_result(self, context, raw_result) -> None:  # type: ignore[no-untyped-def]
        _ = context
        self.results.append(raw_result)
        self.result_available.set()


async def _await_result_count(agent: _RegistryCallingTaskAgent, count: int) -> None:
    for _ in range(100):
        if len(agent.results) >= count:
            return
        agent.result_available.clear()
        await asyncio.wait_for(agent.result_available.wait(), timeout=1)
    raise AssertionError(f"TaskAgent produced fewer than {count} results")


@pytest.mark.asyncio
async def test_late_worker_start_does_not_stop_persistent_task_agent() -> None:
    registry, tool = _configured_registry()
    await _add_tombstone(tool)
    agent = _RegistryCallingTaskAgent(registry)
    await agent.start(event_emitter=None)

    try:
        assert await agent.add_fact(
            FactRecord(
                agent_id="chat:actor-survival",
                event_type="TEST",
                payload={"kind": "cancelled_launch"},
            )
        )
        await _await_result_count(agent, 1)
        assert isinstance(agent.results[0], ToolResult)
        assert agent.results[0].error_code == "CANCELLED"
        assert agent._task is not None
        assert agent._task.done() is False

        assert await agent.add_fact(
            FactRecord(
                agent_id="chat:actor-survival",
                event_type="TEST",
                payload={"kind": "ordinary_fact"},
            )
        )
        await _await_result_count(agent, 2)

        assert agent.results[1] == "second-fact-processed"
        assert agent.get_stats()["processed"] == 2
        assert agent._task is not None
        assert agent._task.done() is False
    finally:
        await agent.stop()
