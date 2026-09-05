"""Exercise real batch dispatch, manifest updates, and file operations.

The per-batch handler uses a fixed catalog in place of the model. Scheduling
and completion pass through BatchDriver and its production runner.
"""
import os
import sqlite3
import time
from types import SimpleNamespace

import pytest

from magi.agent.batch.contracts import BatchItemStatus, BatchJobStatus, BatchRunIdentity, ItemOutcome
from magi.agent.batch.driver import BatchDriver
from magi.agent.batch.tool_selection import default_batch_tool_names
from magi.agent.batch.enumerator import enumerate_seed
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

# What a real handler would resolve from websearch — here a fixed table.
_CATALOG = {
    ("Dune", "2021"): "Dune (2021) · SciFi · Timothee Chalamet",
    ("Matrix", "1999"): "The Matrix (1999) · SciFi · Keanu Reeves",
}


def _lookup(filename: str) -> str | None:
    low = filename.lower()
    for (kw, year), title in _CATALOG.items():
        if kw.lower() in low and year in filename:
            return title
    return None


async def _drive_job(store, job, *, run_batch):
    class Registry:
        @staticmethod
        def resolve_tool_name(name):
            return name

        @staticmethod
        def get_tool(name):
            return object() if name in default_batch_tool_names() else None

        @staticmethod
        def is_skill(name):
            return False

    class Manager:
        max_concurrent = 2

        async def enqueue(self, spec):
            identity = BatchRunIdentity.from_trigger(spec.trigger)
            items = [
                item for item in await store.list_by_status(identity.job_id, BatchItemStatus.RUNNING)
                if item.lease_owner == identity.lease_owner
            ]
            await run_batch(items)
            await driver.on_terminal(SimpleNamespace(spec=spec))

    driver = BatchDriver(Manager(), tool_registry=Registry(), store_factory=lambda: store)
    await driver.kickoff(job.job_id)
    return await store.reconcile_scan(job.job_id, now_ms=int(time.time() * 1000))


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "batch.db"
    conn = sqlite3.connect(db)
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()
    return BatchStore(db_path=str(db))


@pytest.mark.asyncio
async def test_e2e_movie_rename_drives_to_completion(store, tmp_path):
    movies = tmp_path / "movies"
    movies.mkdir()
    (movies / "Dune.2021.1080p.WEBRip.x264-GRP.mkv").write_text("v")
    (movies / "Matrix.1999.BluRay.REMUX.mkv").write_text("v")
    (movies / "mystery.clip.mkv").write_text("v")  # not in catalog -> needs_review

    # seed manifest from the fs enumerator (now a lazy iterator: materialize once)
    seed = {"source": "fs", "root": str(movies), "patterns": ["*.mkv"]}
    inputs = list(enumerate_seed(seed))
    assert len(inputs) == 3
    job = await store.create_job(
        title="movies", owner="local_user", origin_session_id="s", origin_turn_id="u",
        handler_ref="movie-rename", handler_config={"dry_run": False}, seed_spec=seed,
        batch_size=2,
    )
    await store.add_items(job.job_id, inputs)
    job = await store.get_job(job.job_id)

    # inline handler: simulate the agent processing each leased item
    async def run_batch(items):
        outs = []
        for it in items:
            path = it.input["path"]
            title = _lookup(os.path.basename(path))
            if title is None:
                outs.append(ItemOutcome(item_id=it.item_id,
                                        status=BatchItemStatus.NEEDS_REVIEW,
                                        review_reason="movie not found"))
                continue
            new_name = f"{title}.mkv"
            new_path = os.path.join(os.path.dirname(path), new_name)
            os.rename(path, new_path)  # the actual rename
            outs.append(ItemOutcome(item_id=it.item_id, status=BatchItemStatus.DONE,
                                    result={"old": path, "new": new_path, "dedup_key": new_name}))
        await store.update_items(job.job_id, outs)

    report = await _drive_job(store, job, run_batch=run_batch)

    # manifest outcome
    assert report.counts.get("done") == 2
    assert report.counts.get("needs_review") == 1
    assert report.complete is False           # one item still awaits human review
    assert not report.conflicts
    assert (await store.get_job(job.job_id)).status == BatchJobStatus.RECONCILING

    # the real files were renamed for the 2 resolved movies
    on_disk = set(os.listdir(movies))
    assert "Dune (2021) · SciFi · Timothee Chalamet.mkv" in on_disk
    assert "The Matrix (1999) · SciFi · Keanu Reeves.mkv" in on_disk
    assert "Dune.2021.1080p.WEBRip.x264-GRP.mkv" not in on_disk   # old name gone
    assert "mystery.clip.mkv" in on_disk                          # needs_review -> untouched


@pytest.mark.asyncio
async def test_e2e_review_then_resume(store, tmp_path):
    """After review, an approved item goes back to pending and re-runs to done."""
    movies = tmp_path / "movies"
    movies.mkdir()
    (movies / "mystery.clip.mkv").write_text("v")
    seed = {"source": "fs", "root": str(movies), "patterns": ["*.mkv"]}
    job = await store.create_job(
        title="m", owner="u", origin_session_id="", origin_turn_id="",
        handler_ref="movie-rename", handler_config={}, seed_spec=seed,
    )
    await store.add_items(job.job_id, enumerate_seed(seed))
    job = await store.get_job(job.job_id)

    async def to_review(items):
        await store.update_items(job.job_id, [
            ItemOutcome(item_id=i.item_id, status=BatchItemStatus.NEEDS_REVIEW, review_reason="?")
            for i in items
        ])

    await _drive_job(store, job, run_batch=to_review)
    review_items = await store.list_by_status(job.job_id, BatchItemStatus.NEEDS_REVIEW)
    assert len(review_items) == 1

    # human approves -> back to pending
    assert await store.apply_review(job.job_id, review_items[0].item_id, "approve") is True

    async def resolve(items):
        await store.update_items(job.job_id, [
            ItemOutcome(item_id=i.item_id, status=BatchItemStatus.DONE, result={"dedup_key": i.item_id})
            for i in items
        ])

    report = await _drive_job(store, job, run_batch=resolve)
    assert report.complete is True
    assert report.counts.get("done") == 1
    assert (await store.get_job(job.job_id)).status == BatchJobStatus.DONE
