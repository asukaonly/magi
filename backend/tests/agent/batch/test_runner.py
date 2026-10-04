import sqlite3

import pytest

from magi.agent.batch.contracts import BatchItemStatus, BatchJobStatus, ItemOutcome
from magi.agent.batch.runner import (
    fill_to_concurrency,
    kickoff_next_batch,
    on_batch_run_done,
)
from magi.agent.batch.store import BatchStore

_SCHEMA = """
CREATE TABLE batch_job (
    job_id TEXT PRIMARY KEY, title TEXT NOT NULL, owner TEXT NOT NULL,
    origin_session_id TEXT NOT NULL DEFAULT '', origin_turn_id TEXT NOT NULL DEFAULT '',
    handler_ref TEXT NOT NULL, handler_config TEXT NOT NULL DEFAULT '{}',
    seed_spec TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL,
    batch_size INTEGER NOT NULL DEFAULT 15, concurrency INTEGER NOT NULL DEFAULT 1,
    max_attempts INTEGER NOT NULL DEFAULT 3,
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
    job = await store.create_job(
        title="t", owner="u", origin_session_id="", origin_turn_id="",
        handler_ref="movie-rename", handler_config={}, seed_spec={}, **over,
    )
    await store.add_items(job.job_id, [{"path": f"/{i}"} for i in range(n)])
    return await store.get_job(job.job_id)


@pytest.mark.asyncio
async def test_on_done_reclaims_orphan_and_redispatches(store):
    """A run that ends without reporting every item (cap/crash) must not strand
    those items under a live lease: the terminal handler reclaims its own
    orphans and re-dispatches them, driving the job to completion."""
    job = await _job(store, 2, batch_size=2)
    calls = {"n": 0}
    statuses = []

    async def enqueue_run(j, items):
        calls["n"] += 1
        owner = items[0].lease_owner
        if calls["n"] == 1:
            # first run caps: report only the first item, orphan the rest
            await store.update_items(
                j.job_id, [ItemOutcome(item_id=items[0].item_id, status=BatchItemStatus.DONE)]
            )
        else:
            await store.update_items(
                j.job_id,
                [ItemOutcome(item_id=i.item_id, status=BatchItemStatus.DONE) for i in items],
            )
        statuses.append(
            await on_batch_run_done(store, j.job_id, enqueue_run=enqueue_run, lease_owner=owner)
        )

    await kickoff_next_batch(store, job, enqueue_run=enqueue_run)

    assert calls["n"] == 2  # orphan was re-dispatched in a second run
    assert (await store.status_counts(job.job_id)).get("done") == 2
    assert (await store.get_job(job.job_id)).status == BatchJobStatus.DONE

    assert statuses == ["done", "continued"]


@pytest.mark.asyncio
async def test_chain_retries_failed(store):
    job = await _job(store, 1, batch_size=5, max_attempts=3)
    calls = {"n": 0}

    async def enqueue_run(job, items):
        calls["n"] += 1
        st = BatchItemStatus.FAILED if calls["n"] == 1 else BatchItemStatus.DONE
        await store.update_items(job.job_id, [
            ItemOutcome(item_id=i.item_id, status=st, error="x" if st == BatchItemStatus.FAILED else None)
            for i in items
        ])
        await on_batch_run_done(store, job.job_id, enqueue_run=enqueue_run)

    await kickoff_next_batch(store, job, enqueue_run=enqueue_run)
    assert calls["n"] == 2
    assert (await store.get_job(job.job_id)).status == BatchJobStatus.DONE


@pytest.mark.asyncio
async def test_on_done_needs_review_blocks_done(store):
    job = await _job(store, 2, batch_size=5)
    seen = {}

    async def enqueue_run(job, items):
        await store.update_items(job.job_id, [
            ItemOutcome(item_id=items[0].item_id, status=BatchItemStatus.DONE),
            ItemOutcome(item_id=items[1].item_id, status=BatchItemStatus.NEEDS_REVIEW, review_reason="?"),
        ])
        seen["status"] = await on_batch_run_done(store, job.job_id, enqueue_run=enqueue_run)

    await kickoff_next_batch(store, job, enqueue_run=enqueue_run)
    assert seen["status"] == "needs_review"
    assert (await store.get_job(job.job_id)).status != BatchJobStatus.DONE


# --- Task 5: fill_to_concurrency + lease-driven on_batch_run_done ----------
# (reuses the `store` fixture and `_job` helper above)


@pytest.mark.asyncio
async def test_fill_stops_when_pending_exhausted(store):
    job = await _job(store, 3, batch_size=2)  # only 2 batches worth
    runs = []

    async def enqueue(j, items):
        runs.append(items)

    started = await fill_to_concurrency(store, job, enqueue_run=enqueue, target_n=5)
    assert started == 2  # 2 + 1, then nothing left


@pytest.mark.asyncio
async def test_on_done_finalizes_when_all_done(store):
    job = await _job(store, 2, batch_size=2)
    leased = await store.lease_next_batch(
        job.job_id, limit=2, lease_owner="A", lease_ttl_ms=1000, now_ms=1
    )
    await store.update_items(job.job_id, [
        ItemOutcome(item_id=i.item_id, status=BatchItemStatus.DONE) for i in leased
    ])

    async def enqueue(j, items):
        raise AssertionError("should not enqueue")

    status = await on_batch_run_done(store, job.job_id, enqueue_run=enqueue, now_fn=lambda: 9999)
    assert status == "done"
