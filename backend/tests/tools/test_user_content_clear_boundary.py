"""User-content clear boundary coverage for long-lived tool instances."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from magi.agent.workers.child_preset import ChildRunPreset
from magi.agent.workers.worker_manager import ChildRunCoordinator
from magi.agent.workers.worker_state import WorkerRunState
from magi.tools.builtin.find_relevant_tools_tool import FindRelevantToolsTool
from magi.tools.builtin.web_fetch_tool import WebFetchTool
from magi.tools.builtin.web_search_tool import WebSearchTool
from magi.tools.registry import ToolRegistry
from magi.tools.schema import (
    Tool,
    ToolExecutionContext,
    ToolResult,
    ToolSchema,
)


class _BlockingTool(Tool):
    def __init__(self) -> None:
        self.started = 0
        self.release_first = asyncio.Event()
        self.release_second = asyncio.Event()
        self.clear_calls = 0
        super().__init__()

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="blocking-test-tool",
            description="Test-only blocking tool",
            category="test",
            parameters=[],
        )

    async def execute(
        self,
        parameters: dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        self.started += 1
        if self.started == 1:
            await self.release_first.wait()
        else:
            await self.release_second.wait()
        return ToolResult(success=True, data={"call": self.started})

    async def clear_user_content(self) -> None:
        self.clear_calls += 1


class _NestedChildTool(Tool):
    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="nested-child-test-tool",
            description="Test-only nested child tool",
            category="test",
            parameters=[],
        )

    async def execute(
        self,
        parameters: dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        return ToolResult(success=True, data={"nested": True})


class _NestedParentTool(Tool):
    def __init__(self) -> None:
        self.ready_for_nested = asyncio.Event()
        self.run_nested = asyncio.Event()
        super().__init__()

    def _init_schema(self) -> None:
        self.schema = ToolSchema(
            name="nested-parent-test-tool",
            description="Test-only nested parent tool",
            category="test",
            parameters=[],
        )

    async def execute(
        self,
        parameters: dict[str, Any],
        context: ToolExecutionContext,
    ) -> ToolResult:
        self.ready_for_nested.set()
        await self.run_nested.wait()
        registry = getattr(self, "_tool_registry_ref")
        return await registry.execute("nested-child-test-tool", {}, context)


def _context() -> ToolExecutionContext:
    return ToolExecutionContext(
        user_id="user-1",
        agent_id="agent-1",
        session_id="session-1",
    )


@pytest.mark.asyncio
async def test_clear_boundary_drains_old_calls_and_blocks_new_calls() -> None:
    registry = ToolRegistry()
    registry.register(_BlockingTool)
    tool = registry.get_tool("blocking-test-tool")
    assert isinstance(tool, _BlockingTool)

    first = asyncio.create_task(registry.execute("blocking-test-tool", {}, _context()))
    while tool.started < 1:
        await asyncio.sleep(0)

    boundary_entered = asyncio.Event()
    release_boundary = asyncio.Event()

    async def hold_boundary() -> None:
        async with registry.user_content_clear_boundary():
            boundary_entered.set()
            await release_boundary.wait()

    boundary = asyncio.create_task(hold_boundary())
    await asyncio.sleep(0)
    second = asyncio.create_task(registry.execute("blocking-test-tool", {}, _context()))
    await asyncio.sleep(0)

    assert not boundary_entered.is_set()
    assert tool.started == 1

    tool.release_first.set()
    await asyncio.wait_for(boundary_entered.wait(), timeout=1)
    await asyncio.sleep(0)
    assert tool.clear_calls == 1
    assert tool.started == 1

    release_boundary.set()
    await boundary
    while tool.started < 2:
        await asyncio.sleep(0)
    tool.release_second.set()
    await asyncio.gather(first, second)


@pytest.mark.asyncio
async def test_clear_boundary_allows_nested_work_to_drain_without_deadlock() -> None:
    registry = ToolRegistry()
    registry.register(_NestedChildTool)
    registry.register(_NestedParentTool)
    parent = registry.get_tool("nested-parent-test-tool")
    assert isinstance(parent, _NestedParentTool)

    execution = asyncio.create_task(registry.execute("nested-parent-test-tool", {}, _context()))
    await parent.ready_for_nested.wait()

    boundary_entered = asyncio.Event()

    async def clear_content() -> None:
        async with registry.user_content_clear_boundary():
            boundary_entered.set()

    boundary = asyncio.create_task(clear_content())
    await asyncio.sleep(0)
    parent.run_nested.set()

    result = await asyncio.wait_for(execution, timeout=1)
    assert result.success is True
    await asyncio.wait_for(boundary, timeout=1)
    assert boundary_entered.is_set()


@pytest.mark.asyncio
async def test_cancelled_clear_boundary_releases_execution_admission() -> None:
    registry = ToolRegistry()
    registry.register(_BlockingTool)
    tool = registry.get_tool("blocking-test-tool")
    assert isinstance(tool, _BlockingTool)

    first = asyncio.create_task(registry.execute("blocking-test-tool", {}, _context()))
    while tool.started < 1:
        await asyncio.sleep(0)

    async def clear_content() -> None:
        async with registry.user_content_clear_boundary():
            pass

    boundary = asyncio.create_task(clear_content())
    await asyncio.sleep(0)
    boundary.cancel()
    with pytest.raises(asyncio.CancelledError):
        await boundary

    second = asyncio.create_task(registry.execute("blocking-test-tool", {}, _context()))
    while tool.started < 2:
        await asyncio.sleep(0)
    tool.release_second.set()
    result = await asyncio.wait_for(second, timeout=1)
    assert result.success is True

    tool.release_first.set()
    await first


@pytest.mark.asyncio
async def test_clear_boundary_erases_builtin_tool_caches() -> None:
    registry = ToolRegistry()
    registry.register(WebSearchTool)
    registry.register(WebFetchTool)
    registry.register(FindRelevantToolsTool)

    search = registry.get_tool("web-search")
    fetch = registry.get_tool("web-fetch")
    discovery = registry.get_tool("find-relevant-tools")
    assert isinstance(search, WebSearchTool)
    assert isinstance(fetch, WebFetchTool)
    assert isinstance(discovery, FindRelevantToolsTool)

    search._turn_query_cache["turn"] = {("provider", "query", 1): 1.0}
    search._query_result_counts[("provider", "query", 1)] = (1.0, 1)
    search._result_cache[("agent", "provider", (), "query", 1)] = (
        1.0,
        {"results": ["private"]},
    )
    fetch._fetch_cache[("https://example.com", "auto", "text", "load", 1, 1, True)] = (
        1.0,
        {"content": "private"},
    )
    discovery._discovery_cache[("session", "private")] = (
        1.0,
        {"tools": ["private"]},
    )

    async with registry.user_content_clear_boundary():
        assert search._turn_query_cache == {}
        assert search._query_result_counts == {}
        assert search._result_cache == {}
        assert fetch._fetch_cache == {}
        assert discovery._discovery_cache == {}


@pytest.mark.asyncio
async def test_worker_manager_clear_cancels_runs_and_erases_retained_content() -> None:
    manager = ChildRunCoordinator()
    teardown_started = asyncio.Event()
    release_teardown = asyncio.Event()

    async def wait_for_clear() -> None:
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            teardown_started.set()
            await release_teardown.wait()
            raise

    worker_task = asyncio.create_task(wait_for_clear())
    state = WorkerRunState(
        worker_id="worker-1",
        child_run_id="child-1",
        preset=ChildRunPreset.READ_ONLY,
        description="private description",
        prompt="private prompt",
        parent_task_agent_type="chat",
        parent_task_agent_id="default",
        target_task_agent_type="chat",
        target_task_agent_id="default",
        user_id="user-1",
        session_id="session-1",
        turn_id="turn-1",
        parent_run_id="run-1",
        owner_run_id="run-1",
        created_at=1.0,
        result={"private": "result"},
        parent_context_summary="private context",
        task=worker_task,
    )
    manager._runs[state.worker_id] = state
    old_key = ("session-1", "run-1", 1)
    new_key = ("session-2", "run-2", 2)
    manager._cancelled_run_keys[old_key] = 1.0

    clear_task = asyncio.create_task(manager.clear_user_content())
    await teardown_started.wait()
    await manager.cancel_run_workers(
        session_id=new_key[0],
        run_id=new_key[1],
        run_revision=new_key[2],
    )
    release_teardown.set()
    await clear_task

    assert manager._runs == {}
    assert old_key not in manager._cancelled_run_keys
    assert new_key in manager._cancelled_run_keys
    assert worker_task.done()
    assert worker_task.cancelled()
