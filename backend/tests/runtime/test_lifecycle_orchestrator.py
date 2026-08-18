from __future__ import annotations

import pytest

from magi.bootstrap.lifecycle import (
    LifecycleModule,
    LifecycleShutdownError,
    ModuleLifecycleOrchestrator,
)


@pytest.mark.asyncio
async def test_startup_runs_init_then_post_init_in_order() -> None:
    events: list[str] = []

    async def _a_init() -> None:
        events.append("a.init")

    async def _a_post_init() -> None:
        events.append("a.post")

    async def _a_shutdown() -> None:
        events.append("a.stop")

    async def _b_init() -> None:
        events.append("b.init")

    async def _b_post_init() -> None:
        events.append("b.post")

    async def _b_shutdown() -> None:
        events.append("b.stop")

    orchestrator = ModuleLifecycleOrchestrator(
        modules=[
            LifecycleModule(name="a", init=_a_init, post_init=_a_post_init, shutdown=_a_shutdown),
            LifecycleModule(name="b", init=_b_init, post_init=_b_post_init, shutdown=_b_shutdown),
        ]
    )

    await orchestrator.startup()
    await orchestrator.shutdown()

    assert events == [
        "a.init",
        "b.init",
        "a.post",
        "b.post",
        "b.stop",
        "a.stop",
    ]


@pytest.mark.asyncio
async def test_startup_failure_triggers_reverse_shutdown_for_initialized_modules() -> None:
    events: list[str] = []

    async def _a_init() -> None:
        events.append("a.init")

    async def _a_shutdown() -> None:
        events.append("a.stop")

    async def _b_init() -> None:
        events.append("b.init")
        raise RuntimeError("boom")

    async def _b_shutdown() -> None:
        events.append("b.stop")

    orchestrator = ModuleLifecycleOrchestrator(
        modules=[
            LifecycleModule(name="a", init=_a_init, shutdown=_a_shutdown),
            LifecycleModule(name="b", init=_b_init, shutdown=_b_shutdown),
        ]
    )

    with pytest.raises(RuntimeError, match="boom"):
        await orchestrator.startup()

    assert events == ["a.init", "b.init", "a.stop"]


@pytest.mark.asyncio
async def test_post_init_failure_triggers_reverse_shutdown_for_all_initialized_modules() -> None:
    events: list[str] = []

    async def _a_init() -> None:
        events.append("a.init")

    async def _a_post_init() -> None:
        events.append("a.post")

    async def _a_shutdown() -> None:
        events.append("a.stop")

    async def _b_init() -> None:
        events.append("b.init")

    async def _b_post_init() -> None:
        events.append("b.post")
        raise RuntimeError("post-boom")

    async def _b_shutdown() -> None:
        events.append("b.stop")

    orchestrator = ModuleLifecycleOrchestrator(
        modules=[
            LifecycleModule(name="a", init=_a_init, post_init=_a_post_init, shutdown=_a_shutdown),
            LifecycleModule(name="b", init=_b_init, post_init=_b_post_init, shutdown=_b_shutdown),
        ]
    )

    with pytest.raises(RuntimeError, match="post-boom"):
        await orchestrator.startup()

    assert events == ["a.init", "b.init", "a.post", "b.post", "b.stop", "a.stop"]


@pytest.mark.asyncio
async def test_strict_shutdown_reports_failures_and_can_be_retried() -> None:
    events: list[str] = []
    attempts = 0

    async def _shutdown() -> None:
        nonlocal attempts
        attempts += 1
        events.append(f"stop.{attempts}")
        if attempts == 1:
            raise OSError("database still busy")

    orchestrator = ModuleLifecycleOrchestrator(
        modules=[LifecycleModule(name="memory", shutdown=_shutdown)]
    )
    await orchestrator.startup()

    with pytest.raises(LifecycleShutdownError) as failure:
        await orchestrator.shutdown(strict=True)
    assert failure.value.failures[0][0] == "memory"

    await orchestrator.shutdown(strict=True)
    assert events == ["stop.1", "stop.2"]


@pytest.mark.asyncio
async def test_dependencies_are_started_in_topological_order() -> None:
    events: list[str] = []

    async def _record(name: str) -> None:
        events.append(name)

    orchestrator = ModuleLifecycleOrchestrator(
        modules=[
            LifecycleModule(name="scheduler", dependencies=["runtime"], init=lambda: _record("scheduler.init")),
            LifecycleModule(name="runtime", dependencies=["memory"], init=lambda: _record("runtime.init")),
            LifecycleModule(name="memory", dependencies=["bus"], init=lambda: _record("memory.init")),
            LifecycleModule(name="bus", init=lambda: _record("bus.init")),
        ]
    )

    await orchestrator.startup()

    assert events == ["bus.init", "memory.init", "runtime.init", "scheduler.init"]


def test_unknown_dependency_raises_value_error() -> None:
    with pytest.raises(ValueError, match="depends on unknown module"):
        ModuleLifecycleOrchestrator(
            modules=[
                LifecycleModule(name="a", dependencies=["missing"]),
            ]
        )


def test_cycle_dependency_raises_value_error() -> None:
    with pytest.raises(ValueError, match="dependency cycle detected"):
        ModuleLifecycleOrchestrator(
            modules=[
                LifecycleModule(name="a", dependencies=["b"]),
                LifecycleModule(name="b", dependencies=["a"]),
            ]
        )
