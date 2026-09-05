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
    BackgroundTaskStore,
)
from magi.agent.background.executor import BackgroundTaskRunResult
from magi.agent.background.manager import BackgroundTaskManager
from magi.agent.batch.contracts import BatchItemStatus, BatchJobStatus, BatchRunIdentity, ItemOutcome
from magi.agent.batch.driver import BatchDriver
from magi.agent.batch.store import BatchStore
from magi.agent.batch.tool_selection import default_batch_tool_names
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


class _FakeToolRegistry:
    def __init__(self) -> None:
        self._tools = set(default_batch_tool_names())

    @staticmethod
    def resolve_tool_name(tool_name: str) -> str:
        return tool_name

    def get_tool(self, tool_name: str):
        return object() if tool_name in self._tools else None

    @staticmethod
    def is_skill(_skill_name: str) -> bool:
        return False


async def _wait_until(predicate, *, timeout: float = 3.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        if await predicate():
            return
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"condition not met within {timeout}s")
        await asyncio.sleep(0.01)


def _build_batch_store(tmp_path) -> BatchStore:
    """Real BatchStore on a self-built table (independent of the runtime fixture)."""
    batch_db = tmp_path / "batch.db"
    conn = sqlite3.connect(batch_db)
    conn.executescript(_BATCH_SCHEMA)
    conn.commit()
    conn.close()
    return BatchStore(db_path=str(batch_db))


def _make_batch_run_fn(batch_store: BatchStore):
    """Stub the LLM agent run: read this batch's leased ('running') items off the
    persisted trigger and mark them DONE — exactly as a real batch run would write back."""

    async def run_fn(task: BackgroundTask, token: CancelToken) -> BackgroundTaskRunResult:
        identity = BatchRunIdentity.from_trigger(task.spec.trigger)
        job_id = identity.job_id
        running = [
            item for item in await batch_store.list_by_status(job_id, BatchItemStatus.RUNNING)
            if item.lease_owner == identity.lease_owner
        ]
        await batch_store.update_items(job_id, [
            ItemOutcome(item_id=i.item_id, status=BatchItemStatus.DONE, result={"dedup_key": i.item_id})
            for i in running
        ])
        return BackgroundTaskRunResult(summary=f"batch of {len(running)} done")

    return run_fn


@pytest.mark.asyncio
async def test_batch_self_enqueues_through_real_manager(runtime_paths_with_schema, tmp_path):
    # --- batch store (self-built table; independent of fixture) ---
    batch_store = _build_batch_store(tmp_path)

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
    manager = BackgroundTaskManager(store=bg_store, run_fn=_make_batch_run_fn(batch_store), max_concurrent=1)

    driver = BatchDriver(manager, tool_registry=_FakeToolRegistry(), store_factory=lambda: batch_store)
    manager.add_listener(driver.on_terminal)
    await manager.start()
    try:
        # kickoff the first batch; the chain self-propagates via the listener
        await driver.kickoff(job.job_id)

        async def _job_done() -> bool:
            j = await batch_store.get_job(job.job_id)
            return j is not None and j.status == BatchJobStatus.DONE

        await _wait_until(_job_done)
    finally:
        await manager.stop()

    counts = await batch_store.status_counts(job.job_id)
    assert counts.get("done") == 5
    assert (await batch_store.get_job(job.job_id)).status == BatchJobStatus.DONE


@pytest.mark.asyncio
async def test_resume_running_jobs_drives_to_done_after_restart(
    runtime_paths_with_schema, tmp_path
):
    """Restart recovery, end-to-end through the REAL manager.

    Simulates the state a crashed process leaves behind: a RUNNING job whose
    runs never got enqueued (manager._running is empty after a restart). On the
    fresh process we register BatchDriver.on_terminal, start the manager, then
    call resume_running_jobs() once — the same one-liner lifecycle.py runs after
    manager.start(). That force-requeues orphaned items and refills the runs; the
    terminal listener then chains the remaining batches to completion.
    """
    batch_store = _build_batch_store(tmp_path)

    # 5 items, batch_size=2 -> 3 chained runs once resume kicks the first one(s).
    job = await batch_store.create_job(
        title="movies", owner="alice", origin_session_id="s", origin_turn_id="t",
        handler_ref="inline", handler_config={"prompt": "rename each file"},
        seed_spec={}, batch_size=2,
    )
    await batch_store.add_items(job.job_id, [{"path": f"/m/{i}.mkv"} for i in range(5)])
    # Crashed-process state: job is RUNNING but NO kickoff happened (no runs enqueued).
    await batch_store.set_job_status(job.job_id, BatchJobStatus.RUNNING)

    # --- fresh process: real manager + real BatchDriver, only the agent run stubbed ---
    bg_store = BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))
    manager = BackgroundTaskManager(store=bg_store, run_fn=_make_batch_run_fn(batch_store), max_concurrent=1)
    driver = BatchDriver(
        manager,
        tool_registry=_FakeToolRegistry(),
        store_factory=lambda: batch_store,
    )
    manager.add_listener(driver.on_terminal)
    await manager.start()
    try:
        # The lifecycle hook: pick up RUNNING jobs left by the previous process.
        resumed = await driver.resume_running_jobs()
        assert resumed == 1

        async def _job_done() -> bool:
            j = await batch_store.get_job(job.job_id)
            return j is not None and j.status == BatchJobStatus.DONE

        await _wait_until(_job_done)
    finally:
        await manager.stop()

    counts = await batch_store.status_counts(job.job_id)
    assert counts.get("done") == 5
    assert (await batch_store.get_job(job.job_id)).status == BatchJobStatus.DONE
