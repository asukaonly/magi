from __future__ import annotations

import sqlite3

import pytest

from magi.memory.event_contracts import IngestTarget, MemoryDomain


def _migrated_l1_db_path(tmp_path):
    from magi.db.runner import MIGRATION_TARGETS, run_upgrade_head
    from magi.utils.runtime import RuntimePaths

    runtime_paths = RuntimePaths(base_dir=tmp_path / "runtime")
    l1_target = next(target for target in MIGRATION_TARGETS if target.name == "l1")

    run_upgrade_head(runtime_paths, targets=(l1_target,))
    return runtime_paths.l1_memory_db_path


def _insert_legacy_event(
    db_path,
    *,
    event_id: str,
    content: str,
    author_type: str,
    source: str,
    event_type: str = "UserMessage",
) -> None:
    with sqlite3.connect(db_path) as db:
        db.execute(
            """
            INSERT INTO fact_events(
                event_id, correlation_id, timestamp, created_at,
                event_type, source, memory_domain, ingest_target,
                content, author_type, content_type, user_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                f"corr-{event_id}",
                1710000000.0,
                1710000001.0,
                event_type,
                source,
                int(MemoryDomain.USER_AUTHORED),
                int(IngestTarget.L1_ONLY),
                content,
                author_type,
                "text",
                "user-1",
            ),
        )


@pytest.mark.asyncio
async def test_l1_evidence_backfill_classifies_legacy_default_rows(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    db_path = _migrated_l1_db_path(tmp_path)
    _insert_legacy_event(
        db_path,
        event_id="evt-legacy-user",
        content="I like oolong tea.",
        author_type="user",
        source="chat",
    )
    _insert_legacy_event(
        db_path,
        event_id="evt-legacy-assistant",
        content="You like oolong tea.",
        author_type="assistant",
        source="assistant",
        event_type="AIResponse",
    )

    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()
    try:
        result = await store.backfill_evidence_annotations(batch_size=1)

        user_event = await store.get_event("evt-legacy-user")
        assistant_event = await store.get_event("evt-legacy-assistant")
        second_run = await store.backfill_evidence_annotations()
    finally:
        await store.shutdown()

    assert result.matched == 2
    assert result.processed == 2
    assert result.updated == 2
    assert result.by_l1_retrieval_scope == {
        "fact_authoritative": 1,
        "conversation_only": 1,
    }

    assert user_event is not None
    assert user_event["evidence_status"] == "classified"
    assert user_event["evidence_class"] == "user_self_report"
    assert user_event["l1_retrieval_scope"] == "fact_authoritative"

    assert assistant_event is not None
    assert assistant_event["evidence_status"] == "classified"
    assert assistant_event["evidence_class"] == "assistant_freeform"
    assert assistant_event["l1_retrieval_scope"] == "conversation_only"
    assert assistant_event["evidence_skip_reason"] == "assistant_freeform"

    assert second_run.matched == 0
    assert second_run.updated == 0


@pytest.mark.asyncio
async def test_l1_evidence_backfill_dry_run_leaves_rows_unchanged(tmp_path):
    from magi.memory.l1.event_store import L1EventStore

    db_path = _migrated_l1_db_path(tmp_path)
    _insert_legacy_event(
        db_path,
        event_id="evt-legacy-dry-run",
        content="I like jasmine tea.",
        author_type="user",
        source="chat",
    )

    store = L1EventStore(db_path=str(db_path), vector_enabled=False)
    await store.initialize()
    try:
        result = await store.backfill_evidence_annotations(dry_run=True)
        fetched = await store.get_event("evt-legacy-dry-run")
    finally:
        await store.shutdown()

    assert result.matched == 1
    assert result.processed == 1
    assert result.would_update == 1
    assert result.updated == 0
    assert result.by_l1_retrieval_scope == {"fact_authoritative": 1}

    assert fetched is not None
    assert fetched["evidence_status"] == "unclassified"
    assert fetched["evidence_class"] == "unknown"
    assert fetched["l1_retrieval_scope"] == "none"
