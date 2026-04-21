"""Tests for background-task bootstrap wiring (Phase 4c)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from magi.agent.background import (
    BackgroundTask,
    BackgroundTaskSpec,
    BackgroundTaskStatus,
    BackgroundTaskStore,
    BackgroundTaskTriggerSource,
)
from magi.bootstrap.background_tasks import (
    build_background_task_wiring,
    build_completion_handshake_listener,
)


def _make_task(
    *,
    status: BackgroundTaskStatus = BackgroundTaskStatus.SUCCEEDED,
    session_id: str = "s1",
    user_id: str = "u1",
) -> BackgroundTask:
    spec = BackgroundTaskSpec(
        user_id=user_id,
        session_id=session_id,
        origin_turn_id="turn-1",
        title="T",
        goal="g",
        selected_tools=[],
        trigger_source=BackgroundTaskTriggerSource.RULE,
    )
    task = BackgroundTask.new(spec)
    task.status = status
    task.summary = "all good"
    return task


# ----------------------------------------------------------------------
# build_background_task_wiring
# ----------------------------------------------------------------------


def test_build_background_task_wiring_composes_components(tmp_path: Path) -> None:
    wiring = build_background_task_wiring(
        store_db_path=str(tmp_path / "bg.db"),
        llm_adapter=None,
        llm_pool=None,
        skill_runner=None,
        runtime_trace_store=None,
        max_concurrent=3,
    )
    assert isinstance(wiring.store, BackgroundTaskStore)
    assert wiring.store.db_path == str(tmp_path / "bg.db")
    assert wiring.manager is not None
    assert wiring.dispatcher is not None
    assert wiring.launch_service is not None


# ----------------------------------------------------------------------
# build_completion_handshake_listener
# ----------------------------------------------------------------------


class _FakePostProcess:
    def __init__(self) -> None:
        self.calls: list[BackgroundTask] = []

    async def deliver_background_task_completion(self, task: BackgroundTask) -> None:
        self.calls.append(task)


class _FakeTaskAgent:
    def __init__(self, postprocess: Any | None) -> None:
        self.postprocess_service = postprocess


class _FakeManager:
    def __init__(self, agent: Any, *, raise_on_ensure: bool = False) -> None:
        self._agent = agent
        self._raise = raise_on_ensure
        self.ensure_calls: list[tuple[Any, str]] = []

    async def ensure_agent(self, agent_type: Any, agent_id: str) -> Any:
        self.ensure_calls.append((agent_type, agent_id))
        if self._raise:
            raise RuntimeError("no chat agent")
        return self._agent


@pytest.mark.asyncio
async def test_listener_routes_to_chat_agent_postprocess_service() -> None:
    postprocess = _FakePostProcess()
    agent = _FakeTaskAgent(postprocess)
    manager = _FakeManager(agent)
    listener = build_completion_handshake_listener(
        get_task_agent_manager=lambda: manager,
    )
    task = _make_task()

    await listener(task)

    assert postprocess.calls == [task]
    assert len(manager.ensure_calls) == 1
    _, agent_id = manager.ensure_calls[0]
    assert agent_id == "default"


@pytest.mark.asyncio
async def test_listener_respects_custom_chat_agent_id() -> None:
    postprocess = _FakePostProcess()
    manager = _FakeManager(_FakeTaskAgent(postprocess))
    listener = build_completion_handshake_listener(
        get_task_agent_manager=lambda: manager,
        chat_agent_id="custom-agent",
    )

    await listener(_make_task())

    _, agent_id = manager.ensure_calls[0]
    assert agent_id == "custom-agent"


@pytest.mark.asyncio
async def test_listener_degrades_when_task_agent_manager_missing() -> None:
    postprocess = _FakePostProcess()
    listener = build_completion_handshake_listener(
        get_task_agent_manager=lambda: None,
    )

    await listener(_make_task())

    assert postprocess.calls == []


@pytest.mark.asyncio
async def test_listener_swallows_ensure_agent_exception() -> None:
    manager = _FakeManager(agent=None, raise_on_ensure=True)
    listener = build_completion_handshake_listener(
        get_task_agent_manager=lambda: manager,
    )

    # Must not raise.
    await listener(_make_task())


@pytest.mark.asyncio
async def test_listener_skips_when_agent_lacks_postprocess_service() -> None:
    # Agent without postprocess_service attribute should be handled
    # gracefully instead of raising AttributeError.
    agent = SimpleNamespace()
    manager = _FakeManager(agent)
    listener = build_completion_handshake_listener(
        get_task_agent_manager=lambda: manager,
    )

    await listener(_make_task())


@pytest.mark.asyncio
async def test_listener_swallows_deliver_exception() -> None:
    class _ExplodingPostProcess:
        async def deliver_background_task_completion(
            self, task: BackgroundTask
        ) -> None:
            raise ValueError("chat store down")

    manager = _FakeManager(_FakeTaskAgent(_ExplodingPostProcess()))
    listener = build_completion_handshake_listener(
        get_task_agent_manager=lambda: manager,
    )

    # Must not raise.
    await listener(_make_task())
