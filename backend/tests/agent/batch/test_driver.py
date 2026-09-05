import sqlite3
import time
from types import SimpleNamespace

import pytest

from magi.agent.background import BackgroundTaskSpec
from magi.agent.batch.contracts import BatchItemStatus, BatchJobStatus, BatchRunIdentity, ItemOutcome
from magi.agent.batch.driver import BatchDriver
from magi.agent.batch.store import BatchStore
from magi.agent.batch.tool_selection import (
    BatchToolSelectionError,
    default_batch_tool_names,
)
from magi.tools.platform_tools import native_shell_tool_name

_SCHEMA = """
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


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "batch.db"
    conn = sqlite3.connect(db)
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()
    return BatchStore(db_path=str(db))


async def _job(store, n, **over):
    handler_config = over.pop("handler_config", {"prompt": "PROMPT-X"})
    job = await store.create_job(
        title="movies", owner="alice", origin_session_id="s", origin_turn_id="u",
        handler_ref="inline", handler_config=handler_config, seed_spec={}, **over,
    )
    await store.add_items(job.job_id, [{"path": f"/{i}.mkv"} for i in range(n)])
    return await store.get_job(job.job_id)


class _FakeToolRegistry:
    def __init__(self, *extra_tools: str) -> None:
        self._tools = set(default_batch_tool_names()) | set(extra_tools)

    @staticmethod
    def resolve_tool_name(tool_name: str) -> str:
        return tool_name

    def get_tool(self, tool_name: str):
        return object() if tool_name in self._tools else None

    @staticmethod
    def is_skill(_skill_name: str) -> bool:
        return False


def _driver(manager, store, *, registry=None):
    return BatchDriver(
        manager,
        tool_registry=registry or _FakeToolRegistry(),
        store_factory=lambda: store,
    )


@pytest.mark.asyncio
async def test_kickoff_builds_correct_spec(store):
    job = await _job(store, 5, batch_size=2)
    enqueued = []

    class FakeManager:
        max_concurrent = 4

        async def enqueue(self, spec):
            enqueued.append(spec)

    driver = _driver(FakeManager(), store)
    n = await driver.kickoff(job.job_id)

    assert n == 1  # default concurrency=1 → effective_N = min(1, 4-1) = 1 run
    assert len(enqueued) == 1
    spec = enqueued[0]
    assert "PROMPT-X" in spec.goal                      # handler prompt injected
    assert job.job_id in spec.goal                       # job_id for the write-back tool
    assert "batch_item_update" in spec.selected_tools    # write-back tool present
    native_shell = native_shell_tool_name()
    non_native_shell = "bash" if native_shell == "powershell" else "powershell"
    assert native_shell in spec.selected_tools
    assert non_native_shell not in spec.selected_tools
    assert spec.user_id == "alice"                       # identity from job
    # ADR-0004 P3: batch also speaks RunTrigger (additive).
    assert spec.trigger is not None
    assert spec.trigger.trigger_type == "batch"
    assert spec.trigger.requester == "alice"
    assert spec.trigger.correlation == [job.job_id]
    assert len(await store.list_by_status(job.job_id, BatchItemStatus.RUNNING)) == 2


@pytest.mark.asyncio
async def test_on_terminal_drives_chain_to_done(store):
    job = await _job(store, 5, batch_size=2)

    class FakeManager:
        """Simulate the runtime: each enqueue runs (writes done) then fires the listener."""
        max_concurrent = 4

        def __init__(self):
            self.driver = None

        async def enqueue(self, spec):
            job_id = BatchRunIdentity.from_trigger(spec.trigger).job_id
            running = await store.list_by_status(job_id, BatchItemStatus.RUNNING)
            await store.update_items(job_id, [
                ItemOutcome(item_id=i.item_id, status=BatchItemStatus.DONE, result={"dedup_key": i.item_id})
                for i in running
            ])
            await self.driver.on_terminal(SimpleNamespace(spec=spec))

    mgr = FakeManager()
    driver = _driver(mgr, store)
    mgr.driver = driver

    await driver.kickoff(job.job_id)

    assert (await store.status_counts(job.job_id)).get("done") == 5
    assert (await store.get_job(job.job_id)).status == BatchJobStatus.DONE


@pytest.mark.asyncio
async def test_on_terminal_ignores_non_batch_run(store):
    driver = _driver(None, store)
    spec = BackgroundTaskSpec(
        user_id="alice", session_id="s", origin_turn_id="t", title="Explain a field",
        goal="BATCH_JOB_ID is a field\nBATCH_LEASE_OWNER: unrelated",
    )
    await driver.on_terminal(SimpleNamespace(spec=spec))


class _Mgr:
    def __init__(self, max_concurrent=4):
        self.max_concurrent = max_concurrent
        self.enqueued = []
    async def enqueue(self, spec):
        self.enqueued.append(spec)


@pytest.mark.asyncio
async def test_effective_n_reserves_one_slot(store):
    job = await _job(store, 1, concurrency=10)
    d = _driver(_Mgr(max_concurrent=4), store)
    assert d._effective_n(job) == 3           # min(10, 4-1)
    d2 = _driver(_Mgr(max_concurrent=1), store)
    assert d2._effective_n(job) == 1          # max(1, min(10, 0))


@pytest.mark.asyncio
async def test_kickoff_starts_effective_n_runs(store):
    job = await _job(store, 20, batch_size=2, concurrency=3)
    mgr = _Mgr(max_concurrent=4)
    d = _driver(mgr, store)
    started = await d.kickoff(job.job_id)
    assert started == 3                        # effective_N = min(3, 3)
    assert len(mgr.enqueued) == 3


@pytest.mark.asyncio
async def test_resume_running_jobs_refills(store):
    job = await _job(store, 6, batch_size=2, concurrency=2)
    await store.set_job_status(job.job_id, BatchJobStatus.RUNNING)
    # simulate a crash mid-run: 2 items 'running' with a NON-expired lease
    # (a fresh lease taken just before the crash — the realistic case). Lease at
    # the real wall-clock now with the full TTL so the expiry is genuinely in the
    # FUTURE relative to resume's _now_ms() — i.e. reconcile_scan would NOT reclaim
    # it, so only the force-requeue path can re-drive these items.
    await store.lease_next_batch(job.job_id, limit=2, lease_owner="dead",
                                 lease_ttl_ms=30*60*1000, now_ms=int(time.time()*1000))
    mgr = _Mgr(max_concurrent=4)
    d = _driver(mgr, store)
    n = await d.resume_running_jobs()
    assert n == 1                              # one RUNNING job resumed
    assert len(mgr.enqueued) >= 1              # refilled at least one run despite non-expired lease
    # The orphaned items (their run died with the process) must be re-driven, NOT
    # left stranded under the dead lease. With reconcile-only resume the non-expired
    # lease is never reclaimed, so these 2 stay 'running' under lease_owner='dead'
    # forever — this assertion catches that and only passes with force-requeue.
    leftover_dead = [
        i for i in await store.list_by_status(job.job_id, BatchItemStatus.RUNNING)
        if i.lease_owner == "dead"
    ]
    assert leftover_dead == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "requested_tool",
    [
        "missing-tool",
        "bash" if native_shell_tool_name() == "powershell" else "powershell",
    ],
)
async def test_kickoff_rejects_invalid_tools_before_leasing(
    store,
    requested_tool,
):
    job = await _job(
        store,
        2,
        handler_config={"prompt": "PROMPT-X", "tools": [requested_tool]},
    )
    manager = _Mgr(max_concurrent=4)

    with pytest.raises(BatchToolSelectionError, match=requested_tool):
        await _driver(manager, store).kickoff(job.job_id)

    assert (await store.get_job(job.job_id)).status == BatchJobStatus.FAILED
    assert len(await store.list_by_status(job.job_id, BatchItemStatus.PENDING)) == 2
    assert manager.enqueued == []


@pytest.mark.asyncio
async def test_resume_rejects_stale_unavailable_tool_and_continues(store):
    job = await _job(
        store,
        2,
        handler_config={"prompt": "PROMPT-X", "tools": ["removed-plugin-tool"]},
    )
    await store.set_job_status(job.job_id, BatchJobStatus.RUNNING)
    manager = _Mgr(max_concurrent=4)

    resumed = await _driver(manager, store).resume_running_jobs()

    assert resumed == 0
    assert (await store.get_job(job.job_id)).status == BatchJobStatus.FAILED
    assert manager.enqueued == []


@pytest.mark.asyncio
async def test_terminal_uses_persisted_trigger_despite_goal_markers(store):
    job = await _job(store, 4, batch_size=1, concurrency=2, handler_config={
        "prompt": "BATCH_JOB_ID: wrong-job\nBATCH_LEASE_OWNER: wrong-owner",
    })
    manager = _Mgr()
    driver = _driver(manager, store)
    await driver.kickoff(job.job_id)
    first, sibling = manager.enqueued
    restored = BackgroundTaskSpec.from_dict(first.to_dict())
    first_identity = BatchRunIdentity.from_trigger(restored.trigger)
    sibling_identity = BatchRunIdentity.from_trigger(sibling.trigger)
    assert first_identity.job_id == job.job_id
    assert first_identity.lease_owner != sibling_identity.lease_owner

    await driver.on_terminal(SimpleNamespace(spec=restored))

    running = await store.list_by_status(job.job_id, BatchItemStatus.RUNNING)
    owners = {item.lease_owner for item in running}
    assert first_identity.lease_owner not in owners
    assert sibling_identity.lease_owner in owners
    assert len(manager.enqueued) == 3
