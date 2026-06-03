import sqlite3

import pytest

from magi.agent.batch.contracts import BatchItemStatus, BatchJobStatus, ItemOutcome
from magi.agent.batch.driver import BatchDriver
from magi.agent.batch.runner import parse_job_id_from_goal
from magi.agent.batch.store import BatchStore

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


class _FakeTask:
    def __init__(self, goal: str) -> None:
        self.spec = type("_Spec", (), {"goal": goal})()


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "batch.db"
    conn = sqlite3.connect(db)
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()
    return BatchStore(db_path=str(db))


async def _job(store, n, **over):
    job = await store.create_job(
        title="movies", owner="alice", origin_session_id="s", origin_turn_id="u",
        handler_ref="inline", handler_config={"prompt": "PROMPT-X"}, seed_spec={}, **over,
    )
    await store.add_items(job.job_id, [{"path": f"/{i}.mkv"} for i in range(n)])
    return await store.get_job(job.job_id)


@pytest.mark.asyncio
async def test_kickoff_builds_correct_spec(store):
    job = await _job(store, 5, batch_size=2)
    enqueued = []

    class FakeManager:
        max_concurrent = 4

        async def enqueue(self, spec):
            enqueued.append(spec)

    driver = BatchDriver(FakeManager(), store_factory=lambda: store)
    n = await driver.kickoff(job.job_id)

    assert n == 1  # default concurrency=1 → effective_N = min(1, 4-1) = 1 run
    assert len(enqueued) == 1
    spec = enqueued[0]
    assert "PROMPT-X" in spec.goal                      # handler prompt injected
    assert job.job_id in spec.goal                       # job_id marker for the listener
    assert "batch_item_update" in spec.selected_tools    # write-back tool present
    assert spec.user_id == "alice"                       # identity from job
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
            job_id = parse_job_id_from_goal(spec.goal)
            running = await store.list_by_status(job_id, BatchItemStatus.RUNNING)
            await store.update_items(job_id, [
                ItemOutcome(item_id=i.item_id, status=BatchItemStatus.DONE, result={"dedup_key": i.item_id})
                for i in running
            ])
            await self.driver.on_terminal(_FakeTask(spec.goal))

    mgr = FakeManager()
    driver = BatchDriver(mgr, store_factory=lambda: store)
    mgr.driver = driver

    await driver.kickoff(job.job_id)

    assert (await store.status_counts(job.job_id)).get("done") == 5
    assert (await store.get_job(job.job_id)).status == BatchJobStatus.DONE


@pytest.mark.asyncio
async def test_on_terminal_ignores_non_batch_run(store):
    driver = BatchDriver(None, store_factory=lambda: store)
    # a background run that isn't a batch (no job_id marker) must be a safe no-op
    await driver.on_terminal(_FakeTask("just a regular background task goal"))


class _Mgr:
    def __init__(self, max_concurrent=4):
        self.max_concurrent = max_concurrent
        self.enqueued = []
    async def enqueue(self, spec):
        self.enqueued.append(spec)


@pytest.mark.asyncio
async def test_effective_n_reserves_one_slot(store):
    job = await _job(store, 1, concurrency=10)
    d = BatchDriver(_Mgr(max_concurrent=4), store_factory=lambda: store)
    assert d._effective_n(job) == 3           # min(10, 4-1)
    d2 = BatchDriver(_Mgr(max_concurrent=1), store_factory=lambda: store)
    assert d2._effective_n(job) == 1          # max(1, min(10, 0))


@pytest.mark.asyncio
async def test_kickoff_starts_effective_n_runs(store):
    job = await _job(store, 20, batch_size=2, concurrency=3)
    mgr = _Mgr(max_concurrent=4)
    d = BatchDriver(mgr, store_factory=lambda: store)
    started = await d.kickoff(job.job_id)
    assert started == 3                        # effective_N = min(3, 3)
    assert len(mgr.enqueued) == 3


@pytest.mark.asyncio
async def test_resume_running_jobs_refills(store):
    job = await _job(store, 6, batch_size=2, concurrency=2)
    await store.set_job_status(job.job_id, BatchJobStatus.RUNNING)
    # simulate a crash mid-run: 2 items stuck 'running' with an EXPIRED lease.
    await store.lease_next_batch(job.job_id, limit=2, lease_owner="dead", lease_ttl_ms=1, now_ms=1)
    mgr = _Mgr(max_concurrent=4)
    d = BatchDriver(mgr, store_factory=lambda: store)
    n = await d.resume_running_jobs()
    assert n == 1                              # one RUNNING job resumed
    assert len(mgr.enqueued) >= 1              # refilled at least one run
    assert len(await store.list_by_status(job.job_id, BatchItemStatus.PENDING)) <= 4
