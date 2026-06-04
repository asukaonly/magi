import sqlite3

import pytest

from magi.agent.batch.contracts import BatchItemStatus, BatchJobStatus, ItemOutcome
from magi.agent.batch.store import BatchStore
from magi.agent.batch.tools import (
    batch_create_tool,
    batch_item_update_tool,
    batch_review_tool,
)
from magi.tools.schema import ToolExecutionContext

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
def store(tmp_path, monkeypatch):
    db = tmp_path / "batch.db"
    conn = sqlite3.connect(db)
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()
    s = BatchStore(db_path=str(db))
    for mod in (batch_create_tool, batch_item_update_tool, batch_review_tool):
        monkeypatch.setattr(mod, "default_batch_store", lambda: s)
    return s


def _ctx(**env):
    return ToolExecutionContext(agent_id="a", workspace="/tmp", env_vars=env)


async def _seed_job(store, n_inputs):
    job = await store.create_job(
        title="t", owner="local_user", origin_session_id="", origin_turn_id="",
        handler_ref="h", handler_config={}, seed_spec={},
    )
    await store.add_items(job.job_id, [{"path": f"/{i}"} for i in range(n_inputs)])
    return job


@pytest.mark.asyncio
async def test_batch_create_seeds_and_runs(store, tmp_path):
    (tmp_path / "a.mkv").write_text("")
    (tmp_path / "b.mkv").write_text("")
    (tmp_path / "c.txt").write_text("")
    tool = batch_create_tool.BatchCreateTool()
    res = await tool.execute(
        {"handler_ref": "movie-rename",
         "seed_spec": {"source": "fs", "root": str(tmp_path), "patterns": ["*.mkv"]}},
        _ctx(user_id="local_user", session_id="s1", turn_id="u1"),
    )
    assert res.success
    job_id = res.data["job_id"]
    assert res.data["total_items"] == 2
    job = await store.get_job(job_id)
    assert job.owner == "local_user" and job.origin_session_id == "s1"
    assert job.status == BatchJobStatus.RUNNING
    assert len(await store.list_by_status(job_id, BatchItemStatus.PENDING)) == 2


@pytest.mark.asyncio
async def test_batch_create_bad_seed(store):
    tool = batch_create_tool.BatchCreateTool()
    res = await tool.execute(
        {"handler_ref": "h", "seed_spec": {"source": "prompt"}}, _ctx()
    )
    assert not res.success
    assert res.error_code == "INVALID_PARAMETERS"


@pytest.mark.asyncio
async def test_batch_item_update_writes_back(store):
    job = await _seed_job(store, 2)
    leased = await store.lease_next_batch(job.job_id, limit=2, lease_owner="A", lease_ttl_ms=1, now_ms=1)
    tool = batch_item_update_tool.BatchItemUpdateTool()
    res = await tool.execute(
        {"job_id": job.job_id, "updates": [
            {"item_id": leased[0].item_id, "status": "done", "result": {"new": "X"}},
            {"item_id": leased[1].item_id, "status": "needs_review", "review_reason": "?"},
        ]},
        _ctx(),
    )
    assert res.success and res.data["applied"] == 2
    assert (await store.get_item(job.job_id, leased[0].item_id)).status == BatchItemStatus.DONE


@pytest.mark.asyncio
async def test_batch_item_update_bad_status(store):
    job = await _seed_job(store, 1)
    tool = batch_item_update_tool.BatchItemUpdateTool()
    res = await tool.execute(
        {"job_id": job.job_id, "updates": [{"item_id": "x", "status": "bogus"}]}, _ctx()
    )
    assert not res.success
    assert res.error_code == "INVALID_PARAMETERS"


@pytest.mark.asyncio
async def test_batch_review_approve_and_skip(store):
    job = await _seed_job(store, 2)
    leased = await store.lease_next_batch(job.job_id, limit=2, lease_owner="A", lease_ttl_ms=1, now_ms=1)
    await store.update_items(job.job_id, [
        ItemOutcome(item_id=leased[0].item_id, status=BatchItemStatus.NEEDS_REVIEW, review_reason="?"),
        ItemOutcome(item_id=leased[1].item_id, status=BatchItemStatus.NEEDS_REVIEW, review_reason="?"),
    ])
    tool = batch_review_tool.BatchReviewTool()
    r1 = await tool.execute({"job_id": job.job_id, "item_id": leased[0].item_id, "decision": "approve"}, _ctx())
    r2 = await tool.execute({"job_id": job.job_id, "item_id": leased[1].item_id, "decision": "skip"}, _ctx())
    assert r1.data["applied"] is True and r2.data["applied"] is True
    assert (await store.get_item(job.job_id, leased[0].item_id)).status == BatchItemStatus.PENDING
    assert (await store.get_item(job.job_id, leased[1].item_id)).status == BatchItemStatus.SKIPPED


@pytest.mark.asyncio
async def test_batch_create_inline_handler_prompt(store, tmp_path):
    (tmp_path / "a.mkv").write_text("")
    tool = batch_create_tool.BatchCreateTool()
    res = await tool.execute(
        {"handler_prompt": "Rename each file to 'Title (Year)'.",
         "seed_spec": {"source": "fs", "root": str(tmp_path), "patterns": ["*.mkv"]}},
        _ctx(user_id="local_user"),
    )
    assert res.success
    job = await store.get_job(res.data["job_id"])
    assert job.handler_ref == "inline"
    assert job.handler_config.get("prompt") == "Rename each file to 'Title (Year)'."


@pytest.mark.asyncio
async def test_batch_create_requires_handler(store):
    tool = batch_create_tool.BatchCreateTool()
    res = await tool.execute({"seed_spec": {"source": "fs", "root": "/tmp", "patterns": ["*.x"]}}, _ctx())
    assert not res.success
    assert res.error_code == "INVALID_PARAMETERS"


@pytest.mark.asyncio
async def test_batch_create_concurrency_reaches_job(store, tmp_path):
    (tmp_path / "a.mkv").write_text("")
    (tmp_path / "b.mkv").write_text("")
    tool = batch_create_tool.BatchCreateTool()
    res = await tool.execute(
        {"handler_prompt": "Look up each movie and rename it.",
         "seed_spec": {"source": "fs", "root": str(tmp_path), "patterns": ["*.mkv"]},
         "concurrency": 5, "title": "movies"},
        _ctx(user_id="local_user"),
    )
    assert res.success
    assert res.data["total_items"] == 2
    job = await store.get_job(res.data["job_id"])
    assert job.concurrency == 5


@pytest.mark.asyncio
async def test_batch_create_concurrency_defaults_to_3(store, tmp_path):
    (tmp_path / "a.mkv").write_text("")
    tool = batch_create_tool.BatchCreateTool()
    res = await tool.execute(
        {"handler_prompt": "Rename each file.",
         "seed_spec": {"source": "fs", "root": str(tmp_path), "patterns": ["*.mkv"]}},
        _ctx(user_id="local_user"),
    )
    assert res.success
    job = await store.get_job(res.data["job_id"])
    assert job.concurrency == 3
