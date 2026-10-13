"""Historical archive reading respects the live governance boundary."""

from __future__ import annotations

from dataclasses import replace
import json
import time

import aiosqlite
import pytest

from magi.memory.archives.reader import ArchiveGovernanceUnavailable, ArchiveReader
from magi.memory.event_contracts import MemoryDomain, RetentionClass
from magi.memory.l2.corrections.models import CorrectionKind
from magi.memory.l3.models import L3Candidate
from magi.memory.source_event_governance import (
    chat_session_source_reference,
    tombstone_source_event_ids,
)

from .test_durable_forgetting import _build_memory, _event


@pytest.fixture
async def archive_memory(tmp_path):
    store = _build_memory(tmp_path)
    await store.initialize()
    try:
        yield store
    finally:
        await store.shutdown()


def _reader(store):
    return ArchiveReader(archive_dir=store._archive_dir, memory_db_path=store.memory_db_path)


async def _archive_event(
    store, event_id, *, at=None, content="曾经去过京都 Kyoto", session_id="history"
):
    event = _event(
        event_id, timestamp=at or time.time() - 45 * 86400, content=content, session_id=session_id
    )
    await store.l1.store(event)
    raw = await store.l1.get_event(event_id)
    await store._archive_l1_event(raw, archived_at=time.time())
    return raw


@pytest.mark.asyncio
async def test_real_retention_archive_is_readable_without_restoring_active_layers(archive_memory):
    store = archive_memory
    at = time.time() - 45 * 86400
    event = replace(
        _event("retained", timestamp=at, content="京都的旅行完成了 Kyoto"),
        memory_domain=MemoryDomain.EXTERNAL_ACTIVITY,
        retention_class=RetentionClass.COMPRESSIBLE,
        cognition_eligible=False,
    )
    await store.l1.store(event)
    await store.l3.upsert_candidate(
        candidate=L3Candidate(
            summary_type="insight",
            summary_category="state_change",
            content="京都行程回顾",
            source_event_ids=[event.event_id],
        ),
        summary_overrides={
            "period_start": at,
            "period_end": at,
            "created_at": at,
            "updated_at": at,
        },
    )
    removed = await store.cleanup_old_data(older_than_days=30, history_behavior="archive")
    assert removed["archived_events"] == 1 and removed["archived_summaries"] == 1
    assert not await store.l1.query_events(event_id=event.event_id)
    assert await store.l3.count_summaries() == 0
    result = await _reader(store).search(query="京都")
    assert result.total == 2 and not result.partial
    assert {item.layer for item in result.items} == {"l1", "l3"}
    assert all(
        item.archived and item.evidence_event_ids == [event.event_id] for item in result.items
    )
    assert {item.occurred_at for item in result.items} == {at}
    assert (await _reader(store).search(query="kyoto")).total == 1
    assert not await store.l1.query_events(event_id=event.event_id)
    assert await store.l3.count_summaries() == 0
    await store.clear_all_memory()
    assert (await _reader(store).search()).total == 0


@pytest.mark.asyncio
async def test_page_order_and_total_span_multiple_archive_files(archive_memory):
    store = archive_memory
    at = time.time() - 1000
    for index in range(5):
        raw = await _archive_event(store, f"event-{index}", at=at + index)
        await store._archive_l1_event(raw, archived_at=time.time() - (index + 1) * 86400)
    result = await _reader(store).search(limit=2, offset=2)
    assert result.total == 5
    assert [item.record_id for item in result.items] == ["event-2", "event-1"]
    assert not result.partial


@pytest.mark.asyncio
@pytest.mark.parametrize("typed_session", [False, True])
async def test_barriers_hide_archive_even_before_physical_cleanup(archive_memory, typed_session):
    store = archive_memory
    await _archive_event(store, "governed")
    ref = (
        chat_session_source_reference(user_id="u1", session_id="history")
        if typed_session
        else "governed"
    )
    async with aiosqlite.connect(store.memory_db_path) as db:
        await tombstone_source_event_ids(
            db, event_ids=[ref], reason="user_deleted", created_at=time.time()
        )
        await db.commit()
    assert (await _reader(store).search()).total == 0
    assert list(store._archive_dir.glob("*.db"))


@pytest.mark.asyncio
async def test_real_source_forget_and_stale_archive_copy_cannot_reappear(archive_memory):
    store = archive_memory
    raw = await _archive_event(store, "deleted-source")
    await store.forget_source_events(["deleted-source"])
    assert (await _reader(store).search()).total == 0
    await store._archive_l1_event(raw, archived_at=time.time())
    assert (await _reader(store).search()).total == 0


@pytest.mark.asyncio
async def test_summary_with_any_forgotten_evidence_is_hidden_before_archive_cleanup(archive_memory):
    store = archive_memory
    raw = await _archive_event(store, "summary-source")
    summary = {
        "summary": {
            "summary_id": "archived-summary",
            "source_event_ids": ["summary-source", "other-source"],
            "summary_type": "insight",
            "summary_category": "state_change",
            "content": "京都回顾",
            "period_start": raw["timestamp"],
            "period_end": raw["timestamp"],
        },
        "event_links": [{"event_id": "summary-source"}, {"event_id": "other-source"}],
    }
    await store._archive_l3_summary(summary, archived_at=time.time())
    assert (await _reader(store).search()).total == 2
    async with aiosqlite.connect(store.memory_db_path) as db:
        await tombstone_source_event_ids(
            db, event_ids=["other-source"], reason="user_deleted", created_at=time.time()
        )
        await db.commit()
    result = await _reader(store).search()
    assert [item.record_id for item in result.items] == ["summary-source"]


@pytest.mark.asyncio
async def test_real_time_range_forget_covers_stale_archive(archive_memory):
    store = archive_memory
    at = time.time() - 1000
    raw = await _archive_event(store, "time-governed", at=at)
    await store.forget_time_range_memory(start=at - 1, end=at + 1, delete_l1_events=True)
    await store._archive_l1_event(raw, archived_at=time.time())
    assert (await _reader(store).search()).total == 0


@pytest.mark.asyncio
async def test_current_correction_hides_stale_original_archive(archive_memory):
    store = archive_memory
    raw = await _archive_event(
        store, "corrected-source", content="我住在上海", at=time.time() - 1000
    )
    triple = await store.l2.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="LIVES_IN",
        object_id="place:shanghai",
        object_type="place",
        fact_kind="explicit_fact",
        evidence_event_ids=["corrected-source"],
        confidence=0.9,
        observed_at=raw["timestamp"],
        source_type="conversation",
        extraction_method="explicit",
        evidence_class="user_self_report",
    )
    assert (await _reader(store).search()).total == 1
    correction = await store.l2.apply_relationship_correction(
        triple_id=triple,
        request_id="correct-archive",
        actor_id="user:u1",
        correction_kind=CorrectionKind.RECORD_ERROR,
    )
    assert correction is not None
    assert (await _reader(store).search()).total == 0


@pytest.mark.asyncio
async def test_corrupt_unsafe_and_malformed_records_report_partial_without_paths(
    archive_memory, tmp_path
):
    store = archive_memory
    await _archive_event(store, "visible")
    root = store._archive_dir
    (root / "2000-01-01.db").write_text("not sqlite")
    outside = tmp_path / "outside.db"
    outside.write_text("private path")
    (root / "2000-01-02.db").symlink_to(outside)
    archive = next(path for path in root.glob("*.db") if path.name.startswith("202"))
    async with aiosqlite.connect(archive) as db:
        await db.execute(
            "UPDATE archived_l1_events SET payload_json = ?", (json.dumps({"unexpected": "data"}),)
        )
        await db.commit()
    result = await _reader(store).search()
    assert result.total == 0 and result.partial
    assert {item.code: item.count for item in result.issues} == {
        "archive_unreadable": 1,
        "archive_unsafe": 1,
        "record_invalid": 1,
    }
    assert (
        str(root) not in result.model_dump_json() and str(outside) not in result.model_dump_json()
    )


@pytest.mark.asyncio
async def test_unavailable_governance_never_returns_archive_text(archive_memory, tmp_path):
    store = archive_memory
    await _archive_event(store, "private")
    invalid = tmp_path / "invalid-governance.db"
    async with aiosqlite.connect(invalid) as db:
        await db.execute("CREATE TABLE unrelated(id TEXT)")
    with pytest.raises(ArchiveGovernanceUnavailable):
        await ArchiveReader(archive_dir=store._archive_dir, memory_db_path=invalid).search()


@pytest.mark.asyncio
async def test_unknown_forgotten_evidence_fails_closed_for_archive_results(archive_memory):
    store = archive_memory
    await _archive_event(store, "unknown-support")
    async with aiosqlite.connect(store.memory_db_path) as db:
        await db.execute(
            """INSERT INTO memory_forget_claim_rules(
                rule_id, target_kind, claim_fingerprint, semantic_fingerprint,
                forget_kind, evidence_fail_closed, created_at
            ) VALUES ('unknown-rule', 'edge', 'unknown-claim', 'unknown-semantic', 'entity', 1, ?)""",
            (time.time(),),
        )
        await db.commit()
    assert (await _reader(store).search()).total == 0
