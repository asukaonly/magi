import sqlite3

import pytest

from magi.agent.batch.contracts import BatchItemStatus, BatchJobStatus, ItemOutcome
from magi.agent.batch.store import BatchStore

# Baseline schema copied from
# backend/src/magi/db/migrations/batch/versions/0001_initial.py SCHEMA_SQL.
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
    db_path = tmp_path / "batch.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()
    return BatchStore(db_path=str(db_path))


async def _make_job(store, **over):
    kwargs = dict(
        title="t", owner="local_user", origin_session_id="s1",
        origin_turn_id="u1", handler_ref="movie-rename",
        handler_config={"dry_run": False}, seed_spec={"source": "fs"},
    )
    kwargs.update(over)
    return await store.create_job(**kwargs)


# === jobs / items =========================================================

@pytest.mark.asyncio
async def test_create_job_then_get_round_trip(store):
    job = await _make_job(store)
    assert job.job_id
    assert job.status == BatchJobStatus.PLANNING
    assert job.handler_config == {"dry_run": False}
    assert job.batch_size == 15

    fetched = await store.get_job(job.job_id)
    assert fetched == job


@pytest.mark.asyncio
async def test_get_job_missing_returns_none(store):
    assert await store.get_job("nope") is None


@pytest.mark.asyncio
async def test_add_items_seeds_pending(store):
    job = await _make_job(store)
    n = await store.add_items(job.job_id, [{"path": "/a.mkv"}, {"path": "/b.mp4"}])
    assert n == 2

    items = await store.list_by_status(job.job_id, BatchItemStatus.PENDING)
    assert len(items) == 2
    assert {i.input["path"] for i in items} == {"/a.mkv", "/b.mp4"}
    assert all(i.status == BatchItemStatus.PENDING for i in items)
    assert all(i.attempts == 0 for i in items)


# === lease ================================================================

@pytest.mark.asyncio
async def test_lease_marks_running_and_returns_items(store):
    job = await _make_job(store)
    await store.add_items(job.job_id, [{"path": f"/{i}.mkv"} for i in range(5)])

    leased = await store.lease_next_batch(
        job.job_id, limit=3, lease_owner="run-A", lease_ttl_ms=60_000, now_ms=1_000
    )
    assert len(leased) == 3
    assert all(i.status == BatchItemStatus.RUNNING for i in leased)
    assert all(i.lease_owner == "run-A" for i in leased)
    assert all(i.lease_expires_at_ms == 61_000 for i in leased)
    assert len(await store.list_by_status(job.job_id, BatchItemStatus.PENDING)) == 2


@pytest.mark.asyncio
async def test_lease_does_not_double_claim(store):
    job = await _make_job(store)
    await store.add_items(job.job_id, [{"path": f"/{i}.mkv"} for i in range(3)])

    a = await store.lease_next_batch(job.job_id, limit=2, lease_owner="A", lease_ttl_ms=1, now_ms=1)
    b = await store.lease_next_batch(job.job_id, limit=2, lease_owner="B", lease_ttl_ms=1, now_ms=1)
    a_ids = {i.item_id for i in a}
    b_ids = {i.item_id for i in b}
    assert a_ids.isdisjoint(b_ids)
    assert len(a) == 2 and len(b) == 1


@pytest.mark.asyncio
async def test_lease_empty_when_no_pending(store):
    job = await _make_job(store)
    leased = await store.lease_next_batch(job.job_id, limit=5, lease_owner="A", lease_ttl_ms=1, now_ms=1)
    assert leased == []


# === update_items =========================================================

@pytest.mark.asyncio
async def test_update_items_writes_outcomes(store):
    job = await _make_job(store)
    await store.add_items(job.job_id, [{"path": "/a.mkv"}, {"path": "/b.mkv"}])
    leased = await store.lease_next_batch(job.job_id, limit=2, lease_owner="A", lease_ttl_ms=1, now_ms=1)
    a, b = leased[0], leased[1]

    updated = await store.update_items(job.job_id, [
        ItemOutcome(item_id=a.item_id, status=BatchItemStatus.DONE, result={"new": "X (2020).mkv"}),
        ItemOutcome(item_id=b.item_id, status=BatchItemStatus.NEEDS_REVIEW, review_reason="ambiguous"),
    ])
    assert updated == 2

    ra = await store.get_item(job.job_id, a.item_id)
    rb = await store.get_item(job.job_id, b.item_id)
    assert ra.status == BatchItemStatus.DONE and ra.result == {"new": "X (2020).mkv"}
    assert ra.attempts == 1
    assert rb.status == BatchItemStatus.NEEDS_REVIEW and rb.review_reason == "ambiguous"


@pytest.mark.asyncio
async def test_update_items_only_touches_running(store):
    job = await _make_job(store)
    await store.add_items(job.job_id, [{"path": "/a.mkv"}])
    leased = await store.lease_next_batch(job.job_id, limit=1, lease_owner="A", lease_ttl_ms=1, now_ms=1)
    iid = leased[0].item_id

    await store.update_items(job.job_id, [ItemOutcome(item_id=iid, status=BatchItemStatus.DONE)])
    n = await store.update_items(job.job_id, [ItemOutcome(item_id=iid, status=BatchItemStatus.PENDING)])
    assert n == 0
    assert (await store.get_item(job.job_id, iid)).status == BatchItemStatus.DONE


# === counts / reclaim / reconcile =========================================

@pytest.mark.asyncio
async def test_status_counts(store):
    job = await _make_job(store)
    await store.add_items(job.job_id, [{"path": f"/{i}.mkv"} for i in range(3)])
    leased = await store.lease_next_batch(job.job_id, limit=1, lease_owner="A", lease_ttl_ms=1, now_ms=1)
    await store.update_items(job.job_id, [ItemOutcome(item_id=leased[0].item_id, status=BatchItemStatus.DONE)])

    counts = await store.status_counts(job.job_id)
    assert counts.get("done") == 1
    assert counts.get("pending") == 2


@pytest.mark.asyncio
async def test_reclaim_expired_leases(store):
    job = await _make_job(store)
    await store.add_items(job.job_id, [{"path": "/a.mkv"}])
    await store.lease_next_batch(job.job_id, limit=1, lease_owner="A", lease_ttl_ms=100, now_ms=1_000)
    reclaimed = await store.reclaim_expired_leases(job.job_id, now_ms=2_000)
    assert reclaimed == 1
    assert len(await store.list_by_status(job.job_id, BatchItemStatus.PENDING)) == 1


@pytest.mark.asyncio
async def test_reconcile_scan_complete_and_conflicts(store):
    job = await _make_job(store)
    await store.add_items(job.job_id, [{"path": "/a.mkv"}, {"path": "/b.mkv"}])
    leased = await store.lease_next_batch(job.job_id, limit=2, lease_owner="A", lease_ttl_ms=1, now_ms=1)
    await store.update_items(job.job_id, [
        ItemOutcome(item_id=leased[0].item_id, status=BatchItemStatus.DONE, result={"dedup_key": "Dune (2021).mkv"}),
        ItemOutcome(item_id=leased[1].item_id, status=BatchItemStatus.DONE, result={"dedup_key": "Dune (2021).mkv"}),
    ])
    rep = await store.reconcile_scan(job.job_id, now_ms=10)
    assert rep.total == 2
    assert rep.counts.get("done") == 2
    assert rep.complete is True
    assert len(rep.conflicts) == 1


@pytest.mark.asyncio
async def test_reconcile_scan_incomplete_when_pending(store):
    job = await _make_job(store)
    await store.add_items(job.job_id, [{"path": "/a.mkv"}])
    rep = await store.reconcile_scan(job.job_id, now_ms=10)
    assert rep.complete is False
    assert rep.counts.get("pending") == 1


@pytest.mark.asyncio
async def test_result_normalized_when_agent_sends_string(store):
    """Regression: the agent fills ``result`` freeform via batch_item_update and
    isn't always consistent — a JSON-encoded string or plain text must be stored
    as a dict, never a double-encoded blob that crashes reconcile_scan's dedup
    scan (AttributeError: 'str' object has no attribute 'get').
    """
    job = await _make_job(store)
    await store.add_items(job.job_id, [{"path": "/a.mkv"}, {"path": "/b.mkv"}])
    leased = await store.lease_next_batch(job.job_id, limit=2, lease_owner="A", lease_ttl_ms=1, now_ms=1)
    await store.update_items(job.job_id, [
        ItemOutcome(item_id=leased[0].item_id, status=BatchItemStatus.DONE, result='{"new_name": "X.mkv"}'),
        ItemOutcome(item_id=leased[1].item_id, status=BatchItemStatus.DONE, result="cannot identify"),
    ])
    a = await store.get_item(job.job_id, leased[0].item_id)
    b = await store.get_item(job.job_id, leased[1].item_id)
    assert a.result == {"new_name": "X.mkv"}          # JSON string parsed into a dict
    assert b.result == {"value": "cannot identify"}   # plain scalar wrapped
    rep = await store.reconcile_scan(job.job_id, now_ms=10)  # must not raise
    assert rep.complete is True
    assert rep.counts.get("done") == 2


@pytest.mark.asyncio
async def test_add_items_accepts_iterable_and_chunks(store):
    job = await _make_job(store)

    def gen():  # a lazy generator, not a list — must be accepted
        for i in range(5):
            yield {"path": f"/{i}.mkv"}

    total = await store.add_items(job.job_id, gen(), chunk_size=2)
    assert total == 5
    items = await store.list_by_status(job.job_id, BatchItemStatus.PENDING)
    assert len(items) == 5


@pytest.mark.asyncio
async def test_add_items_empty_iterable(store):
    job = await _make_job(store)
    assert await store.add_items(job.job_id, iter([])) == 0


@pytest.mark.asyncio
async def test_list_jobs_by_status(store):
    j1 = await _make_job(store)
    j2 = await _make_job(store)
    await store.set_job_status(j1.job_id, BatchJobStatus.RUNNING)
    running = await store.list_jobs_by_status(BatchJobStatus.RUNNING)
    assert [j.job_id for j in running] == [j1.job_id]
    planning = await store.list_jobs_by_status(BatchJobStatus.PLANNING)
    assert {j.job_id for j in planning} == {j2.job_id}


@pytest.mark.asyncio
async def test_requeue_running_forces_all_regardless_of_lease(store):
    job = await _make_job(store)
    await store.add_items(job.job_id, [{"path": "/a.mkv"}, {"path": "/b.mkv"}])
    # lease with a FAR-FUTURE expiry (NOT expired) — simulates a fresh lease at crash time
    await store.lease_next_batch(job.job_id, limit=2, lease_owner="dead", lease_ttl_ms=30*60*1000, now_ms=10**12)
    assert len(await store.list_by_status(job.job_id, BatchItemStatus.RUNNING)) == 2
    n = await store.requeue_running(job.job_id)
    assert n == 2
    assert len(await store.list_by_status(job.job_id, BatchItemStatus.RUNNING)) == 0
    assert len(await store.list_by_status(job.job_id, BatchItemStatus.PENDING)) == 2


@pytest.mark.asyncio
async def test_store_connections_use_wal_and_busy_timeout(store):
    # Any store op routes through _connect, which puts the db in WAL mode
    # (persistent, db-file level) and sets a busy_timeout on the connection.
    await _make_job(store)
    import aiosqlite
    # WAL is persistent: a fresh external connection observes it.
    async with aiosqlite.connect(store._db_path) as probe:
        mode = (await (await probe.execute("PRAGMA journal_mode")).fetchone())[0]
    assert mode.lower() == "wal"
    # busy_timeout is connection-scoped: assert _connect sets it on its own conns.
    async with store._connect() as db:
        timeout = (await (await db.execute("PRAGMA busy_timeout")).fetchone())[0]
    assert timeout == 5000
