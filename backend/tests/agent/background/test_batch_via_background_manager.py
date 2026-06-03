"""Integration: the batch driver wired to a REAL BackgroundTaskManager.

Proves the self-enqueue pipeline works against the production async scheduler:
kickoff -> manager.enqueue -> dispatcher runs the (stubbed) agent run -> terminal
listener fires -> on_batch_run_done -> next batch -> ... -> reconcile -> DONE.

Only the LLM agent run is stubbed (run_fn writes outcomes directly instead of a
real model processing the goal). Everything else — the manager's queue/dispatcher,
the terminal listener, the lease/update/reconcile store ops, the self-enqueue
chain — is the real code. This is the most we can verify without a live magi+LLM.
"""
from __future__ import annotations

import asyncio
import sqlite3

import pytest

from magi.agent.background import (
    BackgroundTask,
    BackgroundTaskSpec,
    BackgroundTaskStatus,
    BackgroundTaskStore,
    BackgroundTaskTriggerSource,
)
from magi.agent.background.executor import BackgroundTaskRunResult
from magi.agent.background.manager import BackgroundTaskManager
from magi.agent.batch.contracts import BatchItemStatus, BatchJobStatus, ItemOutcome
from magi.agent.batch.runner import (
    build_batch_goal,
    kickoff_next_batch,
    on_batch_run_done,
    parse_job_id_from_goal,
)
from magi.agent.batch.store import BatchStore
from magi.agent.cancel import CancelToken

_BATCH_SCHEMA = """
CREATE TABLE batch_job (
    job_id TEXT PRIMARY KEY, title TEXT NOT NULL, owner TEXT NOT NULL,
    origin_session_id TEXT NOT NULL DEFAULT '', origin_turn_id TEXT NOT NULL DEFAULT '',
    handler_ref TEXT NOT NULL, handler_config TEXT NOT NULL DEFAULT '{}',
    seed_spec TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL,
    batch_size INTEGER NOT NULL DEFAULT 15, concurrency INTEGER NOT NULL DEFAULT 1,
    max_attempts INTEGER NOT NULL DEFAULT 3, reconcile_rounds_max INTEGER NOT NULL DEFAULT 2,
    created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL
);
CREATE TABLE batch_item (
    job_id TEXT NOT NULL, item_id TEXT NOT NULL, input TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, result TEXT, error TEXT,
    review_reason TEXT, review_decision TEXT, lease_owner TEXT, lease_expires_at_ms INTEGER,
    updated_at_ms INTEGER NOT NULL, PRIMARY KEY (job_id, item_id)
);
CREATE INDEX idx_batch_item_job_status ON batch_item(job_id, status);
"""


async def _wait_until(predicate, *, timeout: float = 3.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        if await predicate():
            return
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"condition not met within {timeout}s")
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_batch_self_enqueues_through_real_manager(runtime_paths_with_schema, tmp_path):
    # --- batch store (self-built table; independent of fixture) ---
    batch_db = tmp_path / "batch.db"
    conn = sqlite3.connect(batch_db)
    conn.executescript(_BATCH_SCHEMA)
    conn.commit()
    conn.close()
    batch_store = BatchStore(db_path=str(batch_db))

    # 5 items, batch_size=2 -> needs 3 chained background runs
    job = await batch_store.create_job(
        title="movies", owner="alice", origin_session_id="s", origin_turn_id="t",
        handler_ref="inline", handler_config={"prompt": "rename each file"},
        seed_spec={}, batch_size=2,
    )
    await batch_store.add_items(job.job_id, [{"path": f"/m/{i}.mkv"} for i in range(5)])
    job = await batch_store.get_job(job.job_id)

    # --- real BackgroundTaskManager with a stubbed agent run ---
    bg_store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))

    async def run_fn(task: BackgroundTask, token: CancelToken) -> BackgroundTaskRunResult:
        # stand in for the LLM agent: process this batch's leased items
        job_id = parse_job_id_from_goal(task.spec.goal)
        running = await batch_store.list_by_status(job_id, BatchItemStatus.RUNNING)
        await batch_store.update_items(job_id, [
            ItemOutcome(item_id=i.item_id, status=BatchItemStatus.DONE, result={"dedup_key": i.item_id})
            for i in running
        ])
        return BackgroundTaskRunResult(summary=f"batch of {len(running)} done")

    manager = BackgroundTaskManager(store=bg_store, run_fn=run_fn, max_concurrent=1)

    async def enqueue_run(j, items):
        spec = BackgroundTaskSpec(
            user_id=j.owner, session_id=j.origin_session_id, origin_turn_id=j.origin_turn_id,
            title=f"[batch:{j.job_id}] {j.title}",
            goal=build_batch_goal(j.handler_config["prompt"], j, items),
            selected_tools=["batch_item_update"],
            trigger_source=BackgroundTaskTriggerSource.RULE,
        )
        await manager.enqueue(spec)

    async def batch_listener(task: BackgroundTask) -> None:
        job_id = parse_job_id_from_goal(task.spec.goal)
        if job_id:
            await on_batch_run_done(batch_store, job_id, enqueue_run=enqueue_run)

    manager.add_listener(batch_listener)
    await manager.start()
    try:
        # kickoff the first batch; the chain self-propagates via the listener
        await kickoff_next_batch(batch_store, job, enqueue_run=enqueue_run)

        async def _job_done() -> bool:
            j = await batch_store.get_job(job.job_id)
            return j is not None and j.status == BatchJobStatus.DONE

        await _wait_until(_job_done)
    finally:
        await manager.stop()

    counts = await batch_store.status_counts(job.job_id)
    assert counts.get("done") == 5
    assert (await batch_store.get_job(job.job_id)).status == BatchJobStatus.DONE
