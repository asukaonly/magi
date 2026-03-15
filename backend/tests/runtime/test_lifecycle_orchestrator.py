from __future__ import annotations

import pytest

from magi.runtime.lifecycle import LifecycleModule, ModuleLifecycleOrchestrator


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
