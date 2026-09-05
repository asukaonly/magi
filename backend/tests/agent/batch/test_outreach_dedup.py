"""W3: outreach producer stays quiet mid-job, emits ONE report when job drains."""
import sqlite3

import pytest

from magi.agent.batch.contracts import BatchItemStatus, ItemOutcome
from magi.agent.batch.store import BatchStore
from magi.outreach.producers import background_completion as bc

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


class _FakeTask:
    def __init__(self, goal, user_id="alice", session_id="s1"):
        self.spec = type("_S", (), {
            "goal": goal, "user_id": user_id, "session_id": session_id,
            "title": "Movies", "pending_message_id": None,
        })()


@pytest.fixture
def store(tmp_path, monkeypatch):
    db = tmp_path / "batch.db"
    conn = sqlite3.connect(db)
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()
    s = BatchStore(db_path=str(db))
    monkeypatch.setattr(bc, "default_batch_store", lambda: s)
    return s


def _goal(job_id):
    return f"process items\nBATCH_JOB_ID: {job_id}\n[...]"


async def _job(store, n):
    job = await store.create_job(
        title="Movies", owner="alice", origin_session_id="s1", origin_turn_id="u",
        handler_ref="inline", handler_config={"prompt": "p"}, seed_spec={},
    )
    await store.add_items(job.job_id, [{"path": f"/{i}.mkv"} for i in range(n)])
    return job


@pytest.mark.asyncio
async def test_midbatch_stays_quiet(store):
    job = await _job(store, 5)
    await store.lease_next_batch(job.job_id, limit=2, lease_owner="A", lease_ttl_ms=1, now_ms=1)
    # 2 running, 3 pending → mid-job → no notification
    assert await bc.batch_job_intent(_FakeTask(_goal(job.job_id)), job.job_id) is None


@pytest.mark.asyncio
async def test_job_done_emits_one_report(store):
    job = await _job(store, 3)
    leased = await store.lease_next_batch(job.job_id, limit=3, lease_owner="A", lease_ttl_ms=1, now_ms=1)
    await store.update_items(job.job_id, [
        ItemOutcome(item_id=i.item_id, status=BatchItemStatus.DONE) for i in leased
    ])
    intent = await bc.batch_job_intent(_FakeTask(_goal(job.job_id)), job.job_id)
    repeated = await bc.batch_job_intent(_FakeTask(_goal(job.job_id)), job.job_id)
    assert intent is not None
    assert repeated is not None
    assert intent.user_id == "alice"
    assert intent.title == "Movies"
    assert "3/3 done" in intent.facts
    assert intent.payload["batch_job_id"] == job.job_id
    assert intent.correlation_id == repeated.correlation_id
    assert intent.correlation_id.startswith(f"{job.job_id}:terminal:")
    assert intent.completed_at_ms == job.updated_at_ms
    assert intent == repeated


@pytest.mark.asyncio
async def test_job_done_with_review_and_failures(store):
    job = await _job(store, 4)
    leased = await store.lease_next_batch(job.job_id, limit=4, lease_owner="A", lease_ttl_ms=1, now_ms=1)
    await store.update_items(job.job_id, [
        ItemOutcome(item_id=leased[0].item_id, status=BatchItemStatus.DONE),
        ItemOutcome(item_id=leased[1].item_id, status=BatchItemStatus.DONE),
        ItemOutcome(item_id=leased[2].item_id, status=BatchItemStatus.NEEDS_REVIEW, review_reason="?"),
        ItemOutcome(item_id=leased[3].item_id, status=BatchItemStatus.FAILED, error="x"),
    ])
    intent = await bc.batch_job_intent(_FakeTask(_goal(job.job_id)), job.job_id)
    assert intent is not None
    assert "need review" in intent.facts and "failed" in intent.facts
