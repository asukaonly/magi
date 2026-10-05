"""Tests for background-task bootstrap wiring (Phase 4c)."""

from __future__ import annotations

import pytest

from magi.bootstrap.background_tasks import build_background_task_wiring
from magi.control.session_store import ControlSessionStore


# ----------------------------------------------------------------------
# build_background_task_wiring
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_background_wiring_launches_with_shared_store_and_limit(
    runtime_paths_with_schema, monkeypatch
):
    import asyncio
    from types import SimpleNamespace
    import magi.bootstrap.background_tasks as bootstrap
    from magi.agent.background import BackgroundTaskTriggerSource
    from magi.agent.background.executor import BackgroundTaskRunResult
    from magi.agent.execution.checkpoint import AgentRunCheckpoint
    from magi.agent.execution.reasoning import ReasoningPolicy, ReasoningState

    release, three_started = asyncio.Event(), asyncio.Event()
    active, peak, seen = 0, 0, []

    async def run(task, token):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        seen.append(task.task_id)
        if active == 3:
            three_started.set()
        try:
            await release.wait()
            return BackgroundTaskRunResult(summary=task.spec.goal)
        finally:
            active -= 1

    monkeypatch.setattr(bootstrap, "build_background_run_fn", lambda **_: run)
    wiring = build_background_task_wiring(
        store_db_path=str(runtime_paths_with_schema.background_tasks_db_path),
        llm_adapter=None,
        llm_pool=None,
        skill_runner=None,
        runtime_trace_store=None,
        chat_task_budget_store=None,
        run_plan_store=ControlSessionStore(),
        max_concurrent=3,
    )
    await wiring.manager.start()
    ids = []
    try:
        for index in range(4):
            policy = ReasoningPolicy()
            checkpoint = AgentRunCheckpoint(
                run_id=f"run-{index}",
                messages=[{"role": "user", "content": f"goal-{index}"}],
                effective_system_prompt="system",
                tools=[],
                iteration=1,
                reasoning_policy=policy,
                reasoning_state=ReasoningState.start(policy),
            ).to_dict()
            request = SimpleNamespace(
                mode=None,
                admission=None,
                capabilities=SimpleNamespace(tools=[]),
                context=SimpleNamespace(
                    user_id="owner",
                    session_id="session",
                    latest_user_message=f"goal-{index}",
                    latest_payload=SimpleNamespace(turn_id=f"turn-{index}"),
                ),
            )
            result = await wiring.launch_service.enqueue_from_request(
                request,
                trigger_source=BackgroundTaskTriggerSource.RULE,
                agent_run_checkpoint=checkpoint,
            )
            ids.append(result.message_payload["background_task_id"])
        await asyncio.wait_for(three_started.wait(), 2)
        assert wiring.manager.active_count() == 3
        assert wiring.manager.store is wiring.store
        rows = [await wiring.store.get_task(task_id) for task_id in ids]
        assert [row.spec.goal for row in rows] == [f"goal-{i}" for i in range(4)]
        release.set()

        async def wait_completed():
            while True:
                rows = [await wiring.store.get_task(task_id) for task_id in ids]
                if all(row.status.value == "succeeded" for row in rows):
                    return rows
                await asyncio.sleep(0.005)

        rows = await asyncio.wait_for(wait_completed(), 3)
        assert peak == 3
        assert set(seen) == set(ids)
        assert [row.summary for row in rows] == [f"goal-{i}" for i in range(4)]
    finally:
        release.set()
        await wiring.manager.stop()
