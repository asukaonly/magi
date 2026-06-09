import sqlite3

import pytest

from magi.agent.batch.contracts import BatchItemStatus, BatchJobStatus, ItemOutcome
from magi.agent.batch.engine import drive_job
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
        handler_ref="h", handler_config={}, seed_spec={}, **over,
    )
    await store.add_items(job.job_id, [{"path": f"/{i}"} for i in range(n)])
    return await store.get_job(job.job_id)


@pytest.mark.asyncio
async def test_drive_all_done(store):
    job = await _job(store, 5, batch_size=2)

    async def run_batch(items):
        await store.update_items(job.job_id, [
            ItemOutcome(item_id=i.item_id, status=BatchItemStatus.DONE,
                        result={"dedup_key": i.item_id})
            for i in items
        ])

    report = await drive_job(store, job, run_batch=run_batch)
    assert report.complete is True
    assert report.counts.get("done") == 5
    assert (await store.get_job(job.job_id)).status == BatchJobStatus.DONE


@pytest.mark.asyncio
async def test_drive_retries_failed_then_done(store):
    job = await _job(store, 1, batch_size=5, max_attempts=3)
    calls = {"n": 0}

    async def run_batch(items):
        calls["n"] += 1
        st = BatchItemStatus.FAILED if calls["n"] == 1 else BatchItemStatus.DONE
        await store.update_items(job.job_id, [
            ItemOutcome(item_id=i.item_id, status=st,
                        error="boom" if st == BatchItemStatus.FAILED else None)
            for i in items
        ])

    report = await drive_job(store, job, run_batch=run_batch)
    assert calls["n"] == 2  # failed once, requeued, ran again
    assert report.complete is True
    assert report.counts.get("done") == 1


@pytest.mark.asyncio
async def test_drive_needs_review_is_incomplete(store):
    job = await _job(store, 2, batch_size=5)

    async def run_batch(items):
        await store.update_items(job.job_id, [
            ItemOutcome(item_id=items[0].item_id, status=BatchItemStatus.DONE),
            ItemOutcome(item_id=items[1].item_id, status=BatchItemStatus.NEEDS_REVIEW, review_reason="?"),
        ])

    report = await drive_job(store, job, run_batch=run_batch)
    assert report.complete is False
    assert report.counts.get("needs_review") == 1
    assert (await store.get_job(job.job_id)).status != BatchJobStatus.DONE


@pytest.mark.asyncio
async def test_drive_dedup_conflict_blocks_done(store):
    job = await _job(store, 2, batch_size=5)

    async def run_batch(items):
        await store.update_items(job.job_id, [
            ItemOutcome(item_id=i.item_id, status=BatchItemStatus.DONE, result={"dedup_key": "SAME"})
            for i in items
        ])

    report = await drive_job(store, job, run_batch=run_batch)
    assert len(report.conflicts) == 1
    assert (await store.get_job(job.job_id)).status != BatchJobStatus.DONE


@pytest.mark.asyncio
async def test_drive_failed_over_limit_stays_failed(store):
    job = await _job(store, 1, batch_size=5, max_attempts=1)

    async def run_batch(items):
        await store.update_items(job.job_id, [
            ItemOutcome(item_id=i.item_id, status=BatchItemStatus.FAILED, error="boom")
            for i in items
        ])

    report = await drive_job(store, job, run_batch=run_batch)
    # attempts reaches 1 == max_attempts → not requeued → terminal failed
    assert report.counts.get("failed") == 1
    assert report.complete is True  # failed is terminal; no pending/running/review
