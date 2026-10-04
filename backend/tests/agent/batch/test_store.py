import sqlite3

import pytest

from _shared.sqlite_privacy import assert_sqlite_fragment_absent
from magi.agent.batch.contracts import BatchItemStatus, BatchJobStatus, ItemOutcome
from magi.agent.batch.store import BatchStore

# Baseline schema copied from
# backend/src/magi/db/migrations/batch/versions/v1_initial.py SCHEMA_SQL.
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
    assert await store.get_job("missing") is None
    job = await _make_job(store)
    assert job.job_id
    assert job.status == BatchJobStatus.PLANNING
    assert job.handler_config == {"dry_run": False}
    assert job.batch_size == 15

    fetched = await store.get_job(job.job_id)
    assert fetched == job

    async with store._connect() as db:
        assert (await (await db.execute("PRAGMA journal_mode")).fetchone())[0].lower() == "wal"
        assert (await (await db.execute("PRAGMA busy_timeout")).fetchone())[0] == 5000
    reopened = BatchStore(db_path=store._db_path)
    assert await reopened.get_job(job.job_id) == job


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


@pytest.mark.asyncio
async def test_clear_all_removes_jobs_and_content_payloads(store):
    private_marker = "magi-batch-private-marker-that-must-not-survive"
    first = await _make_job(store)
    second = await _make_job(store, origin_session_id="s2", origin_turn_id="u2")
    await store.add_items(
        first.job_id,
        [{"secret": private_marker}, {"secret": "second"}],
    )
    await store.add_items(second.job_id, [{"secret": "third"}])

    counts = await store.clear_all()

    assert counts == {"batch_items": 3, "batch_jobs": 2}
    assert await store.get_job(first.job_id) is None
    assert await store.get_job(second.job_id) is None
    assert await store.list_jobs_by_status(BatchJobStatus.PLANNING) == []
    assert_sqlite_fragment_absent(store._db_path, private_marker)


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

    assert (
        await store.lease_next_batch(job.job_id, limit=2, lease_owner="C", lease_ttl_ms=1, now_ms=1)
        == []
    )
    running = await store.list_by_status(job.job_id, BatchItemStatus.RUNNING)
    assert {item.item_id for item in running} == a_ids | b_ids
    assert {item.lease_owner for item in running} == {"A", "B"}


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
async def test_reclaim_expired_leases_preserves_boundary_future_and_other_job(store):
    job = await _make_job(store)
    other = await _make_job(store)
    await store.add_items(job.job_id, [{"index": i} for i in range(4)])
    await store.add_items(other.job_id, [{"index": 0}])
    groups = {}
    for owner, ttl in [("expired", 99), ("boundary", 100), ("future", 101)]:
        groups[owner] = (
            await store.lease_next_batch(
                job.job_id, limit=1, lease_owner=owner, lease_ttl_ms=ttl, now_ms=1000
            )
        )[0]
    other_lease = (
        await store.lease_next_batch(
            other.job_id, limit=1, lease_owner="expired", lease_ttl_ms=1, now_ms=1000
        )
    )[0]
    pending_before = await store.list_by_status(job.job_id, BatchItemStatus.PENDING)
    assert await store.reclaim_expired_leases(job.job_id, now_ms=1100) == 1
    pending = await store.list_by_status(job.job_id, BatchItemStatus.PENDING)
    assert {item.item_id for item in pending} == {
        pending_before[0].item_id,
        groups["expired"].item_id,
    }
    for item in pending:
        assert item.lease_owner is None and item.lease_expires_at_ms is None
    assert {
        item.item_id for item in await store.list_by_status(job.job_id, BatchItemStatus.RUNNING)
    } == {groups["boundary"].item_id, groups["future"].item_id}
    assert await store.get_item(other.job_id, other_lease.item_id) == other_lease
    assert await store.reclaim_expired_leases(job.job_id, now_ms=1100) == 0


@pytest.mark.asyncio
async def test_reclaim_owner_running_requeues_unreported(store):
    # A run leased 2 items but only reported one; the other is an orphan stuck
    # 'running' under the run's lease_owner with a still-valid lease.
    job = await _make_job(store)
    await store.add_items(job.job_id, [{"path": "/a"}, {"path": "/b"}])
    leased = await store.lease_next_batch(
        job.job_id, limit=2, lease_owner="A", lease_ttl_ms=30 * 60 * 1000, now_ms=1
    )
    await store.update_items(
        job.job_id, [ItemOutcome(item_id=leased[0].item_id, status=BatchItemStatus.DONE)]
    )

    requeued, dead = await store.reclaim_owner_running(job.job_id, "A", 3, now_ms=2)
    assert (requeued, dead) == (1, 0)
    pend = await store.list_by_status(job.job_id, BatchItemStatus.PENDING)
    assert [i.item_id for i in pend] == [leased[1].item_id]
    assert pend[0].attempts == 1  # the dead run counts as a consumed attempt
    assert pend[0].lease_owner is None


@pytest.mark.asyncio
async def test_reclaim_owner_running_scoped_to_owner(store):
    # Two concurrent runs each hold one in-flight item. Reclaiming run A must
    # NOT touch run B's still-live item.
    job = await _make_job(store)
    await store.add_items(job.job_id, [{"path": "/a"}, {"path": "/b"}])
    await store.lease_next_batch(job.job_id, limit=1, lease_owner="A", lease_ttl_ms=10**7, now_ms=1)
    b = await store.lease_next_batch(job.job_id, limit=1, lease_owner="B", lease_ttl_ms=10**7, now_ms=1)

    requeued, dead = await store.reclaim_owner_running(job.job_id, "A", 3, now_ms=2)
    assert (requeued, dead) == (1, 0)
    still_running = await store.list_by_status(job.job_id, BatchItemStatus.RUNNING)
    assert [i.item_id for i in still_running] == [b[0].item_id]
    assert still_running[0].lease_owner == "B"


@pytest.mark.asyncio
async def test_reclaim_owner_running_dead_letters_when_exhausted(store):
    # With the dead run as the final allowed attempt, the orphan dead-letters to
    # 'failed' instead of looping pending -> running -> cap forever.
    job = await _make_job(store, max_attempts=1)
    await store.add_items(job.job_id, [{"path": "/a"}])
    await store.lease_next_batch(job.job_id, limit=1, lease_owner="A", lease_ttl_ms=10**7, now_ms=1)

    requeued, dead = await store.reclaim_owner_running(job.job_id, "A", 1, now_ms=2)
    assert (requeued, dead) == (0, 1)
    failed = await store.list_by_status(job.job_id, BatchItemStatus.FAILED)
    assert len(failed) == 1
    assert failed[0].attempts == 1
    assert "orphaned" in (failed[0].error or "")


@pytest.mark.asyncio
async def test_reconcile_scan_complete_and_conflicts(store):
    job = await _make_job(store)
    await store.add_items(job.job_id, [{"path": "/a.mkv"}, {"path": "/b.mkv"}])
    initial = await store.reconcile_scan(job.job_id, now_ms=0)
    assert initial.counts == {"pending": 2} and initial.complete is False
    leased = await store.lease_next_batch(
        job.job_id, limit=2, lease_owner="A", lease_ttl_ms=1, now_ms=1
    )
    await store.update_items(
        job.job_id,
        [
            ItemOutcome(
                item_id=leased[0].item_id,
                status=BatchItemStatus.DONE,
                result={"dedup_key": "Dune (2021).mkv"},
            ),
            ItemOutcome(
                item_id=leased[1].item_id,
                status=BatchItemStatus.DONE,
                result={"dedup_key": "Dune (2021).mkv"},
            ),
        ],
    )
    rep = await store.reconcile_scan(job.job_id, now_ms=10)
    assert rep.total == 2
    assert rep.counts.get("done") == 2
    assert rep.complete is True
    assert {frozenset(pair) for pair in rep.conflicts} == {
        frozenset(item.item_id for item in leased)
    }


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
async def test_add_items_commits_each_chunk_before_consuming_more_input(store):
    job = await _make_job(store)
    observed = []
    with sqlite3.connect(store._db_path) as reader:

        def inputs():
            for index in range(5):
                count = reader.execute(
                    "SELECT COUNT(*) FROM batch_item WHERE job_id=?", (job.job_id,)
                ).fetchone()[0]
                observed.append(count)
                yield {"path": f"/{index}.mkv"}

        assert await store.add_items(job.job_id, inputs(), chunk_size=2) == 5
    assert observed == [0, 0, 2, 2, 4]
    items = await store.list_by_status(job.job_id, BatchItemStatus.PENDING)
    assert {item.input["path"] for item in items} == {f"/{i}.mkv" for i in range(5)}
    assert await store.add_items(job.job_id, iter([]), chunk_size=2) == 0
    assert await store.list_by_status(job.job_id, BatchItemStatus.PENDING) == items


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
@pytest.mark.parametrize(
    "status,complete",
    [
        (BatchItemStatus.PENDING, False),
        (BatchItemStatus.RUNNING, False),
        (BatchItemStatus.NEEDS_REVIEW, False),
        (BatchItemStatus.DONE, True),
        (BatchItemStatus.FAILED, True),
        (BatchItemStatus.SKIPPED, True),
    ],
)
async def test_reconcile_mixed_done_and_each_state(store, status, complete):
    job = await _make_job(store)
    await store.add_items(job.job_id, [{"index": i} for i in range(2)])
    done = (
        await store.lease_next_batch(
            job.job_id, limit=1, lease_owner="done", lease_ttl_ms=100, now_ms=0
        )
    )[0]
    await store.update_items(
        job.job_id, [ItemOutcome(item_id=done.item_id, status=BatchItemStatus.DONE)]
    )
    if status != BatchItemStatus.PENDING:
        second = (
            await store.lease_next_batch(
                job.job_id, limit=1, lease_owner="second", lease_ttl_ms=100, now_ms=0
            )
        )[0]
        if status != BatchItemStatus.RUNNING:
            await store.update_items(
                job.job_id, [ItemOutcome(item_id=second.item_id, status=status)]
            )
    expected = {"done": 2} if status == BatchItemStatus.DONE else {"done": 1, status.value: 1}
    assert await store.status_counts(job.job_id) == expected
    report = await store.reconcile_scan(job.job_id, now_ms=1)
    assert report.counts == expected
    assert report.complete is complete
    assert report.total == 2
    assert report.conflicts == []
    assert report.reclaimed_leases == 0
