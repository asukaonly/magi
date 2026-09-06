from __future__ import annotations

import asyncio
import os
import time
from types import SimpleNamespace

import aiosqlite
import pytest
import sqlite_vec
from magi_plugin_sdk.fs import UnsafeManagedPathError

from _shared.sqlite_privacy import (
    assert_sqlite_fragment_absent,
    sqlite_fragment_present,
)
from _shared.memory_schema import apply_memory_shared_schema
from magi.context.user_profile_service import UserProfileService
from magi.memory.derivation_revision import MemoryClearGenerationChangedError
from magi.memory.embedding.embedding_service import EmbeddingResult
from magi.memory.embedding.sqlite_vec_index import SqliteVecIndex
from magi.memory.l1.event_store import L1EventStore
from magi.memory.l2.corrections.models import (
    ApplyAssertionCorrectionCommand,
    ApplyRelationshipCorrectionCommand,
    CorrectionKind,
    CorrectionTargetKind,
    NewMemoryCorrection,
)
from magi.memory.l2.corrections.repository import MemoryCorrectionRepository
from magi.memory.l2.corrections.relationship_service import RelationshipCorrectionService
from magi.memory.l2.corrections.service import MemoryCorrectionService
from magi.memory.l2.batch_models import L2BatchJob, L2ProjectionLease
from magi.memory.l2.entities.catalog import L2EntityCatalog
from magi.memory.l2.pipeline import L2Pipeline
from magi.memory.l2.store import L2CognitionStore
from magi.memory.manual_entries.asset_store import ManualEntryAssetStore
from magi.memory.shared_clear import clear_shared_auxiliary_memory
from magi.memory.unified_store import MemoryStoreTuning, UnifiedMemoryStore
from magi.user_profile.models import UserProfileProjection
from magi.user_profile.projection_repository import UserProfileProjectionRepository
from magi.user_profile.projection_builder import UserProfileProjectionBuilder


def _assertion_candidate(*, now: float) -> dict[str, object]:
    return {
        "entity_id": "user:u1",
        "entity_type": "user",
        "trait_family": "preference_profile",
        "trait_name": "favorite_food",
        "trait_value": "ramen",
        "confidence_score": 0.9,
        "evidence_events": ["event-old"],
        "volatility_index": 0.1,
        "source_domain": "conversation",
        "inference_depth": "explicit",
        "validation_state": "stable",
        "first_inferred_at": now,
        "last_validated_at": now,
        "temporal_scope": "persistent",
    }


async def test_clear_removes_correction_history_rules_and_versions(tmp_path) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()
    now = time.time()

    candidate = _assertion_candidate(now=now)
    assertion_id = await store.upsert_assertion_candidate(candidate)
    await MemoryCorrectionService(db_path).apply_assertion_correction(
        ApplyAssertionCorrectionCommand(
            assertion_id=assertion_id,
            request_id="clear-assertion",
            actor_id="user:u1",
            correction_kind=CorrectionKind.RECORD_ERROR,
            reason="Sensitive correction reason",
        )
    )

    triple_id = await store.upsert_knowledge_edge(
        subject_id="user:u1",
        subject_type="user",
        predicate="CURRENT_LIVES_IN",
        object_id="place:hangzhou",
        object_type="place",
        evidence_event_ids=["event-edge"],
        confidence=0.9,
        observed_at=now,
        source_type="conversation",
        extraction_method="explicit",
    )
    await RelationshipCorrectionService(db_path).apply(
        ApplyRelationshipCorrectionCommand(
            triple_id=triple_id,
            request_id="clear-edge",
            actor_id="user:u1",
            correction_kind=CorrectionKind.RECORD_ERROR,
        )
    )
    await MemoryCorrectionRepository(db_path).create(
        NewMemoryCorrection(
            correction_id="correction-invalid-evidence",
            request_id="clear-invalid-evidence",
            actor_id="user:u1",
            target_kind=CorrectionTargetKind.ASSERTION,
            target_id="assert-invalid-evidence",
            slot_key="slot-invalid-evidence",
            claim_fingerprint="claim-invalid-evidence",
            correction_kind=CorrectionKind.RECORD_ERROR,
            before={"evidence_events": [{"event_id": "invalid"}]},
            request_fingerprint="fingerprint-invalid-evidence",
            created_at=now,
        )
    )

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO memory_derivation_dependencies(
                artifact_kind, artifact_id, source_kind, source_id,
                subject_key, source_revision, created_at
            ) VALUES ('snapshot', 'user:u1', 'assertion', ?, 'user:u1', 1, ?)
            """,
            (assertion_id, now),
        )
        await db.commit()

    await store.clear()

    governed_tables = (
        "memory_derivation_dependencies",
        "memory_derivation_jobs",
        "memory_correction_evidence_fail_closed",
        "memory_correction_evidence_events",
        "memory_relationship_conflict_effects",
        "memory_correction_request_fingerprints",
        "memory_correction_revert_blocks",
        "memory_correction_rules",
        "memory_corrections",
        "memory_subject_revisions",
        "knowledge_graph_versions",
    )
    async with aiosqlite.connect(db_path) as db:
        for table in governed_tables:
            async with db.execute(f"SELECT COUNT(*) FROM {table}") as cursor:
                assert await cursor.fetchone() == (0,), table

    replayed_id = await store.upsert_assertion_candidate(candidate)
    current = await store.list_current_assertions(entity_id="user:u1")
    assert [item["assertion_id"] for item in current] == [replayed_id]


async def test_clear_waits_for_running_correction_work(tmp_path) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()
    assertion_id = await store.upsert_assertion_candidate(_assertion_candidate(now=time.time()))
    correction = await MemoryCorrectionService(db_path).apply_assertion_correction(
        ApplyAssertionCorrectionCommand(
            assertion_id=assertion_id,
            request_id="clear-running",
            actor_id="user:u1",
            correction_kind=CorrectionKind.RECORD_ERROR,
            replacement_value="udon",
        )
    )
    assert correction is not None
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            UPDATE memory_derivation_jobs
            SET status = 'completed'
            WHERE correction_id = ? AND job_kind != 'snapshot'
            """,
            (correction.correction.correction_id,),
        )
        await db.commit()

    started = asyncio.Event()
    release = asyncio.Event()

    async def pause_snapshot(_job) -> None:  # type: ignore[no-untyped-def]
        started.set()
        await release.wait()

    store.register_memory_correction_job_handler("snapshot", pause_snapshot)
    worker = asyncio.create_task(store.process_memory_correction_jobs(limit=1))
    await asyncio.wait_for(started.wait(), timeout=2)
    clearing = asyncio.create_task(store.clear())
    await asyncio.sleep(0.05)
    assert not clearing.done()

    release.set()
    await asyncio.gather(worker, clearing)

    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT COUNT(*) FROM memory_corrections") as cursor:
            assert await cursor.fetchone() == (0,)
        async with db.execute("SELECT COUNT(*) FROM memory_derivation_jobs") as cursor:
            assert await cursor.fetchone() == (0,)


async def test_clear_removes_all_l2_user_memory_tables(tmp_path) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()
    now = time.time()

    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS l2_promotion_counter (
                source_type TEXT NOT NULL,
                key TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                promoted INTEGER NOT NULL DEFAULT 0,
                first_seen REAL NOT NULL,
                last_seen REAL NOT NULL,
                promoted_at REAL,
                PRIMARY KEY (source_type, key)
            )
            """)
        await db.execute(
            "CREATE TABLE IF NOT EXISTS l2_promotion_seen "
            "(event_id TEXT PRIMARY KEY, seen_at REAL NOT NULL)"
        )
        await db.execute(
            "INSERT INTO l2_promotion_counter VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("private-source", "private.example", 2, 1, now, now, now),
        )
        await db.execute(
            "INSERT INTO l2_promotion_seen VALUES (?, ?)",
            ("private-event", now),
        )
        await db.execute(
            """
            INSERT INTO experience_drafts(
                draft_id, status, query_text, title, one_sentence_review,
                time_start, time_end, chapters_json, possible_evidence_json,
                excluded_evidence_json, created_at, updated_at
            ) VALUES (?, 'editing', ?, ?, ?, ?, ?, '[]', '[]', '[]', ?, ?)
            """,
            (
                "private-draft",
                "private query",
                "Private title",
                "Private recap",
                now,
                now,
                now,
                now,
            ),
        )
        await db.execute(
            """
            INSERT INTO experience_chapters(
                experience_id, chapter_id, position, title, summary,
                episode_ids_json, event_ids_json, created_at, updated_at
            ) VALUES (?, ?, 0, ?, ?, '[]', ?, ?, ?)
            """,
            (
                "private-experience",
                "private-chapter",
                "Private chapter",
                "Private summary",
                '["private-event"]',
                now,
                now,
            ),
        )
        await db.execute(
            "INSERT INTO episodes_fts(episode_id, summary, label, user_label) "
            "VALUES ('private-episode', 'Private summary', 'Private label', 'Private user label')"
        )
        await db.commit()

    await store.clear()

    tables = (
        "l2_promotion_counter",
        "l2_promotion_seen",
        "experience_drafts",
        "experience_chapters",
        "episodes_fts",
    )
    async with aiosqlite.connect(db_path) as db:
        for table in tables:
            async with db.execute(f"SELECT COUNT(*) FROM {table}") as cursor:
                assert await cursor.fetchone() == (0,), table


async def test_clear_invalidates_existing_chat_profile_cache(tmp_path) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()
    repository = UserProfileProjectionRepository(db_path)
    await repository.upsert(
        UserProfileProjection(
            user_id="u1",
            entity_id="user:u1",
            display_name="Private Name",
            refreshed_at=time.time(),
        )
    )
    service = UserProfileService(
        unified_memory=SimpleNamespace(l2=store, l2_entity_catalog=None),
        cache_ttl=300,
    )
    assert await service.get_display_name("u1") == "Private Name"

    await store.clear()

    assert await service.get_display_name("u1") == "unknown"


async def test_clear_waits_for_running_l2_pipeline_writeback(tmp_path) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()
    pipeline = L2Pipeline(
        store,
        entity_catalog=object(),
        llm_service=object(),
        batch_flush_interval_seconds=0,
    )
    event_id = "event-before-clear"
    await store.enqueue_projection_job(
        event_id=event_id,
        source="conversation",
        event_type="USER_MESSAGE",
    )
    claimed = await store.claim_projection_jobs(consumer_name="test-consumer", limit=1)
    assert [row["event_id"] for row in claimed] == [event_id]
    pipeline._projection_consumer_name = "test-consumer"
    job = L2BatchJob(
        job_id="job-before-clear",
        bucket_key="event:event-before-clear",
        events=[
            {
                "event_id": event_id,
                "timestamp": time.time(),
                "event_type": "USER_MESSAGE",
            }
        ],
        flush_reason="immediate",
        estimated_tokens=1,
        projection_leases=[L2ProjectionLease.from_dict(claimed[0])],
    )
    assert (
        await store.bind_projection_job_batch(
            job.projection_leases,
            consumer_name="test-consumer",
            attempt_key=job.attempt_key,
        )
        == 1
    )
    started = asyncio.Event()
    release = asyncio.Event()

    async def delayed_writeback(_job: L2BatchJob) -> dict[str, object]:
        started.set()
        await release.wait()
        await store.upsert_assertion_candidate(_assertion_candidate(now=time.time()))
        return {
            "relation_count": 0,
            "assertion_count": 1,
            "touched_entity_ids": [],
            "touched_place_ids": [],
            "touched_topic_keys": [],
            "skipped": True,
        }

    pipeline._extract_and_persist = delayed_writeback  # type: ignore[method-assign]
    worker = asyncio.create_task(pipeline._process_extract_job(job))
    await asyncio.wait_for(started.wait(), timeout=2)
    clearing = asyncio.create_task(store.clear())
    await asyncio.sleep(0.05)
    assert not clearing.done()

    release.set()
    await asyncio.gather(worker, clearing)

    assert await store.count_tom_assertions() == 0


async def test_rev_zero_profile_built_before_clear_cannot_be_written_back(tmp_path) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()
    await store.upsert_assertion_candidate(
        {
            **_assertion_candidate(now=time.time()),
            "trait_name": "identity.real_name",
            "trait_value": "Private Name",
            "trait_family": "identity_profile",
        }
    )
    projection = await UserProfileProjectionBuilder(store).build("u1")
    assert projection.source_revision == 0
    assert projection.source_generation == 0

    await store.clear()

    with pytest.raises(MemoryClearGenerationChangedError):
        await UserProfileProjectionRepository(db_path).upsert(projection)
    assert await UserProfileProjectionRepository(db_path).get("u1") is None


async def test_catalog_clear_removes_entity_and_relationship_vectors(tmp_path) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    catalog = L2EntityCatalog(db_path=db_path, embedding_service=object())  # type: ignore[arg-type]
    await catalog.initialize()
    entity_index = catalog._vector_index
    edge_index = catalog.edge_vector_index
    assert entity_index is not None and edge_index is not None
    embedding = EmbeddingResult(
        model_name="test-embedding",
        dimension=2,
        vector=[1.0, 0.0],
    )
    await entity_index.upsert(entity_id="user:u1", embedding=embedding)
    await edge_index.upsert(entity_id="private-edge", embedding=embedding)

    await catalog.clear()

    async with aiosqlite.connect(db_path) as db:
        for table in ("l2_entity_vectors", "l2_edge_vectors"):
            async with db.execute(f"SELECT COUNT(*) FROM {table}") as cursor:
                assert await cursor.fetchone() == (0,), table
    await catalog.close()


async def test_catalog_clear_closes_cleanup_only_indexes_without_embedding_model(
    tmp_path,
) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    seeded = L2EntityCatalog(db_path=db_path, embedding_service=object())  # type: ignore[arg-type]
    entity_index = seeded._vector_index
    edge_index = seeded.edge_vector_index
    assert entity_index is not None and edge_index is not None
    embedding = EmbeddingResult(
        model_name="test-embedding",
        dimension=2,
        vector=[1.0, 0.0],
    )
    await entity_index.upsert(entity_id="user:u1", embedding=embedding)
    await edge_index.upsert(entity_id="private-edge", embedding=embedding)
    await seeded.close()

    catalog = L2EntityCatalog(db_path=db_path, vector_enabled=False)
    assert catalog._vector_index is None

    await catalog.clear()

    assert catalog._vector_index is not None
    assert catalog._vector_index._db is None
    assert catalog._edge_vector_index._db is None
    async with aiosqlite.connect(db_path) as db:
        for table in ("l2_entity_vectors", "l2_edge_vectors"):
            async with db.execute(f"SELECT COUNT(*) FROM {table}") as cursor:
                assert await cursor.fetchone() == (0,), table


async def test_shared_clear_removes_manual_location_and_rebuild_rows(tmp_path) -> None:
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    now = time.time()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO manual_entries(entry_id, created_at, event_at, body) "
            "VALUES ('private-entry', ?, ?, 'Private note')",
            (now, now),
        )
        await db.execute(
            "INSERT INTO location_samples(sample_id, source, sampled_at, city, created_at) "
            "VALUES ('private-location', 'source', ?, 'Private City', ?)",
            (now, now),
        )
        await db.execute(
            "INSERT INTO place_labels(label_id, center_lat, center_lng, user_label, created_at) "
            "VALUES ('private-label', 1, 2, 'Private Home', ?)",
            (now,),
        )
        await db.execute(
            "INSERT INTO place_geocode_cache(grid_key, city, cached_at) "
            "VALUES ('private-grid', 'Private City', ?)",
            (now,),
        )
        await db.execute(
            """
            INSERT INTO embedding_rebuild_jobs(
                job_id, status, requested_layers_json, created_at, updated_at
            ) VALUES ('private-job', 'running', '["l2"]', ?, ?)
            """,
            (now, now),
        )
        await db.execute(
            """
            INSERT INTO embedding_rebuild_job_layers(job_id, layer, status, updated_at)
            VALUES ('private-job', 'l2', 'running', ?)
            """,
            (now,),
        )
        await db.execute(
            """
            INSERT INTO history_import_jobs(
                job_id, source_type, source_fingerprint, detected_kind, status,
                total_records, meaningful_records, created_at, updated_at
            ) VALUES (
                'private-import', 'markdown', 'private-fingerprint', 'document',
                'completed', 1, 1, ?, ?
            )
            """,
            (now, now),
        )
        await db.execute(
            """
            INSERT INTO history_import_source_records(
                source_record_key, file_fingerprint, source_name,
                parsed_session_key, session_id, session_seq,
                speaker_name, content, event_at, timestamp_confidence,
                timestamp_anchor_source, calendar_timezone_id,
                meaningful, event_id, created_at
            ) VALUES (
                'private-source-record', 'private-file', 'private.md',
                'private-session-key', 'private-session', 0,
                '__document_author__', 'Private history', ?, 'explicit',
                'message_timestamp', 'UTC',
                1, 'private-event', ?
            )
            """,
            (now, now),
        )
        await db.execute(
            """
            INSERT INTO history_import_job_records(
                job_record_id, job_id, source_record_key,
                raw_state, projection_state, created_at, updated_at
            ) VALUES (
                'private-job-record', 'private-import', 'private-source-record',
                'stored', 'projected', ?, ?
            )
            """,
            (now, now),
        )
        await db.execute("""
            CREATE TABLE timeline_cover_preferences (
                scope_key TEXT PRIMARY KEY,
                asset_ref TEXT NOT NULL
            )
            """)
        await db.execute(
            "INSERT INTO timeline_cover_preferences(scope_key, asset_ref) "
            "VALUES ('private-period', 'manual-entry-asset://private.jpg')"
        )
        await db.commit()

    await clear_shared_auxiliary_memory(db_path)

    tables = (
        "manual_entries",
        "location_samples",
        "place_labels",
        "place_geocode_cache",
        "embedding_rebuild_job_layers",
        "embedding_rebuild_jobs",
        "history_import_job_records",
        "history_import_source_records",
        "history_import_jobs",
        "timeline_cover_preferences",
    )
    async with aiosqlite.connect(db_path) as db:
        for table in tables:
            async with db.execute(f"SELECT COUNT(*) FROM {table}") as cursor:
                assert await cursor.fetchone() == (0,), table


async def test_unified_clear_removes_archives_and_manual_assets_only(tmp_path) -> None:
    memory_root = tmp_path / "memory"
    archive_dir = memory_root / "archive"
    archive_dir.mkdir(parents=True)
    managed_archive_names = (
        "2026-07-14.db",
        "2026-07-14.db-wal",
        "2026-07-14.db-shm",
        "2026-07-14.db-journal",
    )
    for name in managed_archive_names:
        (archive_dir / name).write_bytes(b"private archive")
    keep_archive_file = archive_dir / "README.txt"
    keep_archive_file.write_text("keep")
    unmanaged_similar_name = archive_dir / "2026-07-14.db-journal.bak"
    unmanaged_similar_name.write_text("keep")

    media_root = tmp_path / "media"
    asset_store = ManualEntryAssetStore(media_root=media_root)
    asset_ref = asset_store.store_bytes(b"private image", content_type="image/png")
    unrelated_media = media_root / "other" / "keep.bin"
    unrelated_media.parent.mkdir(parents=True)
    unrelated_media.write_bytes(b"keep")

    unified = UnifiedMemoryStore(
        persist_dir=str(memory_root),
        archive_dir_path=str(archive_dir),
        enable_l0=False,
        enable_l1=False,
        enable_l2=False,
        enable_l3=False,
        enable_l4=False,
    )
    await unified.clear_all_memory(auxiliary_clearers=[asset_store.clear])

    assert asset_store.resolve(asset_ref) is None
    assert (media_root / "manual_entries").is_dir()
    assert unrelated_media.read_bytes() == b"keep"
    assert archive_dir.is_dir()
    assert keep_archive_file.read_text() == "keep"
    assert unmanaged_similar_name.read_text() == "keep"
    for name in managed_archive_names:
        assert not os.path.lexists(archive_dir / name)


async def test_unified_clear_replaces_archive_directory_link_without_following_it(
    tmp_path,
) -> None:
    external_archive = tmp_path / "external-archive"
    external_archive.mkdir()
    external_db = external_archive / "2026-07-15.db"
    external_db.write_bytes(b"must remain outside managed archive")

    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    archive_dir = memory_root / "archive"
    archive_dir.symlink_to(external_archive, target_is_directory=True)
    unified = UnifiedMemoryStore(
        persist_dir=str(memory_root),
        archive_dir_path=str(archive_dir),
        enable_l0=False,
        enable_l1=False,
        enable_l2=False,
        enable_l3=False,
        enable_l4=False,
    )

    await unified.clear_all_memory()

    assert archive_dir.is_dir()
    assert archive_dir.is_symlink() is False
    assert list(archive_dir.iterdir()) == []
    assert external_db.read_bytes() == b"must remain outside managed archive"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO is unavailable")
async def test_unified_clear_unlinks_archive_links_and_special_files_without_opening_targets(
    tmp_path,
) -> None:
    archive_dir = tmp_path / "memory" / "archive"
    archive_dir.mkdir(parents=True)
    external_db = tmp_path / "external.db"
    external_db.write_bytes(b"external content must survive")

    symlink_entry = archive_dir / "2026-07-16.db"
    symlink_entry.symlink_to(external_db)
    hardlink_entry = archive_dir / "2026-07-17.db"
    os.link(external_db, hardlink_entry)
    fifo_entry = archive_dir / "2026-07-18.db-wal"
    os.mkfifo(fifo_entry)
    unrelated = archive_dir / "README.txt"
    unrelated.write_text("keep", encoding="utf-8")

    unified = UnifiedMemoryStore(
        persist_dir=str(tmp_path / "memory"),
        archive_dir_path=str(archive_dir),
        enable_l0=False,
        enable_l1=False,
        enable_l2=False,
        enable_l3=False,
        enable_l4=False,
    )

    await unified.clear_all_memory()

    assert symlink_entry.is_symlink() is False
    assert hardlink_entry.exists() is False
    assert fifo_entry.exists() is False
    assert external_db.read_bytes() == b"external content must survive"
    assert unrelated.read_text(encoding="utf-8") == "keep"


async def test_unified_clear_rejects_linked_archive_parent_without_following_it(
    tmp_path,
) -> None:
    external_root = tmp_path / "external"
    external_archive = external_root / "archive"
    external_archive.mkdir(parents=True)
    external_db = external_archive / "2026-07-19.db"
    external_db.write_bytes(b"external content must survive")
    managed_root = tmp_path / "managed"
    managed_root.mkdir()
    linked_parent = managed_root / "linked"
    linked_parent.symlink_to(external_root, target_is_directory=True)
    archive_dir = linked_parent / "archive"
    persist_dir = managed_root / "memory"
    unified = UnifiedMemoryStore(
        persist_dir=str(persist_dir),
        archive_dir_path=str(archive_dir),
        enable_l0=False,
        enable_l1=False,
        enable_l2=False,
        enable_l3=False,
        enable_l4=False,
    )

    with pytest.raises(UnsafeManagedPathError):
        await unified.clear_all_memory()

    assert external_db.read_bytes() == b"external content must survive"


async def test_unified_clear_removes_dormant_l0_rows_when_l0_is_disabled(
    tmp_path,
) -> None:
    private_marker = "magi-memory-private-marker-that-must-not-survive"
    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA secure_delete=OFF")
        await db.execute(
            """
            INSERT INTO l0_sessions(
                session_id, status, started_at, last_active_at, metadata
            ) VALUES ('old-session', 'active', 1, 1, '{}')
            """
        )
        await db.execute(
            """
            INSERT INTO l0_attention_items(
                item_id, session_id, kind, summary, status,
                salience, confidence, evidence_mode,
                first_seen_at, last_reinforced_at
            ) VALUES (
                'old-attention', 'old-session', 'focus', ?,
                'active', 0.8, 0.9, 'direct', 1, 1
            )
            """,
            (private_marker,),
        )
        await db.execute(
            """
            INSERT INTO l0_forgotten_attention_source_refs(source_ref, created_at)
            VALUES ('old-source', 1)
            """
        )
        await db.execute(
            """
            INSERT INTO l0_forgotten_attention_entities(
                entity_id, cutoff_at, operation_id, updated_at
            ) VALUES ('old-entity', 1, 'old-operation', 1)
            """
        )
        await db.execute(
            """
            INSERT INTO memory_source_turn_cutoffs(
                turn_id, cutoff_at, reason, updated_at
            ) VALUES ('old-turn', 1, 'old-forget', 1)
            """
        )
        await db.commit()

    assert sqlite_fragment_present(db_path, private_marker)

    unified = UnifiedMemoryStore(
        memory_db_path=db_path,
        persist_dir=str(tmp_path / "memory"),
        enable_l0=False,
        enable_l1=False,
        enable_l2=False,
        enable_l3=False,
        enable_l4=False,
    )
    await unified.clear_all_memory()

    async with aiosqlite.connect(db_path) as db:
        for table in (
            "l0_attention_items",
            "l0_sessions",
            "l0_forgotten_attention_source_refs",
            "l0_forgotten_attention_entities",
            "memory_source_turn_cutoffs",
        ):
            async with db.execute(f"SELECT COUNT(*) FROM {table}") as cursor:
                assert await cursor.fetchone() == (0,), table
    assert_sqlite_fragment_absent(db_path, private_marker)


async def test_unified_clear_removes_every_dormant_memory_layer(tmp_path) -> None:
    private_marker = "magi-dormant-memory-private-marker-that-must-not-survive"
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    db_path = str(memory_root / "memory.db")
    l1_db_path = str(memory_root / "l1_events.db")
    await apply_memory_shared_schema(db_path)
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA secure_delete=OFF")
        await db.execute(
            """
            INSERT INTO entity_catalog(
                entity_id, canonical_name, entity_type, created_at, updated_at
            ) VALUES ('private-entity', ?, 'person', 1, 1)
            """,
            (private_marker,),
        )
        await db.execute(
            """
            INSERT INTO summaries(
                summary_id, summary_type, summary_category, period_start,
                period_end, content, source_event_ids, source_event_count,
                created_at, updated_at
            ) VALUES ('private-summary', 'temporal', 'day', 1, 2, ?, '[]', 0, 1, 1)
            """,
            (private_marker,),
        )
        await db.execute(
            """
            INSERT INTO procedural_skills(
                skill_id, skill_name, skill_category, skill_type,
                source_event_ids, created_at, updated_at
            ) VALUES ('private-skill', ?, 'test', 'workflow', '[]', 1, 1)
            """,
            (private_marker,),
        )
        await db.execute(
            """
            INSERT INTO l4_skill_event_links(skill_id, event_id, created_at)
            VALUES ('private-skill', ?, 1)
            """,
            (private_marker,),
        )
        await db.execute(
            """
            INSERT INTO memory_projection_blocks(
                block_kind, target_id, event_id, operation_id, created_at
            ) VALUES ('entity_projection', 'private-target', ?, 'private-operation', 1)
            """,
            (private_marker,),
        )
        await db.execute(
            """
            INSERT INTO memory_entity_projection_identity_blocks(
                target_id, event_id, normalized_surface, entity_type,
                operation_id, created_at
            ) VALUES (
                'private-target', 'private-event', ?, 'person',
                'private-operation', 1
            )
            """,
            (private_marker,),
        )
        for table in (
            "l0_goal_stack",
            "l0_active_entities",
            "l0_temporary_tactics",
            "l0_forgotten_tactic_source_refs",
        ):
            await db.execute(f"CREATE TABLE {table}(content TEXT NOT NULL)")
            await db.execute(f"INSERT INTO {table}(content) VALUES (?)", (private_marker,))
        await db.commit()
    async with aiosqlite.connect(l1_db_path) as db:
        await db.execute("CREATE TABLE events(content TEXT NOT NULL)")
        await db.execute("INSERT INTO events(content) VALUES (?)", (private_marker,))
        await db.commit()
    l1_journal_path = f"{l1_db_path}-journal"
    l1_unmanaged_backup_path = f"{l1_db_path}-journal.bak"
    with open(l1_journal_path, "wb") as journal_file:
        journal_file.write(private_marker.encode("utf-8"))
    with open(l1_unmanaged_backup_path, "wb") as backup_file:
        backup_file.write(b"keep")

    l3_index = SqliteVecIndex(
        db_path=db_path,
        registry_table="l3_summary_chunk_vectors",
        entity_column="chunk_id",
        vec_table_prefix="l3_summary_chunk_vec",
    )
    await l3_index.upsert(
        entity_id="private-summary-chunk",
        embedding=EmbeddingResult(
            model_name="private-test-model",
            dimension=2,
            vector=[1.0, 0.0],
        ),
    )
    await l3_index.close()
    assert sqlite_fragment_present(db_path, private_marker)

    unified = UnifiedMemoryStore(
        memory_db_path=db_path,
        l1_db_path=l1_db_path,
        persist_dir=str(memory_root),
        enable_l0=False,
        enable_l1=False,
        enable_l2=False,
        enable_l3=False,
        enable_l4=False,
    )
    counts = await unified.clear_all_memory()

    assert counts["l2"] == 1
    assert counts["l3"] == 1
    assert counts["l4"] == 1
    assert not os.path.lexists(l1_db_path)
    assert not os.path.lexists(l1_journal_path)
    with open(l1_unmanaged_backup_path, "rb") as backup_file:
        assert backup_file.read() == b"keep"
    async with aiosqlite.connect(db_path) as db:
        for table in (
            "entity_catalog",
            "summaries",
            "procedural_skills",
            "l4_skill_event_links",
            "memory_projection_blocks",
            "memory_entity_projection_identity_blocks",
            "l3_summary_chunk_vectors",
            "l0_goal_stack",
            "l0_active_entities",
            "l0_temporary_tactics",
            "l0_forgotten_tactic_source_refs",
        ):
            async with db.execute(f"SELECT COUNT(*) FROM {table}") as cursor:
                assert await cursor.fetchone() == (0,), table
        async with db.execute(
            "SELECT generation FROM memory_clear_state WHERE singleton_id = 1"
        ) as cursor:
            assert await cursor.fetchone() == (1,)
    assert_sqlite_fragment_absent(db_path, private_marker)


async def test_active_l1_clear_removes_rollback_journal(tmp_path) -> None:
    db_path = str(tmp_path / "l1_events.db")
    journal_path = f"{db_path}-journal"
    store = L1EventStore(db_path=db_path, vector_enabled=False)
    await store.initialize(start_workers=False)
    original_count_events = store.count_events

    async def count_events_and_seed_journal() -> int:
        count = await original_count_events()
        with open(journal_path, "wb") as journal_file:
            journal_file.write(b"private-active-l1-marker")
        return count

    store.count_events = count_events_and_seed_journal  # type: ignore[method-assign]

    await store.clear(restart_workers=False)

    assert not os.path.lexists(journal_path)
    await store.shutdown()


async def test_unified_clear_removes_stale_vectors_when_active_layers_disable_vectors(
    tmp_path,
) -> None:
    private_marker = "magi-disabled-vector-private-marker-that-must-not-survive"
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    db_path = str(memory_root / "memory.db")
    await apply_memory_shared_schema(db_path)
    vector_specs = (
        ("l2_entity_vectors", "entity_id", "l2_entity_vec", "entity"),
        ("l2_edge_vectors", "entity_id", "l2_edge_vec", "edge"),
        ("l3_summary_chunk_vectors", "chunk_id", "l3_summary_chunk_vec", "summary"),
        ("l4_skill_chunk_vectors", "chunk_id", "l4_skill_chunk_vec", "skill"),
    )
    vector_tables: list[str] = []
    for registry_table, entity_column, vec_table_prefix, entity_kind in vector_specs:
        index = SqliteVecIndex(
            db_path=db_path,
            registry_table=registry_table,
            entity_column=entity_column,
            vec_table_prefix=vec_table_prefix,
        )
        await index.upsert(
            entity_id=f"{private_marker}-{entity_kind}",
            embedding=EmbeddingResult(
                model_name="private-disabled-vector-model",
                dimension=2,
                vector=[1.0, 0.0],
            ),
        )
        await index.close()
        async with aiosqlite.connect(db_path) as db:
            async with db.execute(f"SELECT vec_table FROM {registry_table}") as cursor:
                vector_tables.extend(str(row[0]) for row in await cursor.fetchall())

    assert sqlite_fragment_present(db_path, private_marker)
    unified = UnifiedMemoryStore(
        memory_db_path=db_path,
        persist_dir=str(memory_root),
        enable_l0=False,
        enable_l1=False,
        enable_l2=True,
        enable_l3=True,
        enable_l4=True,
        tuning=MemoryStoreTuning(
            enable_l1_vectors=False,
            enable_l2_vectors=False,
            enable_l3_vectors=False,
            enable_l4_vectors=False,
        ),
    )
    assert unified.l2_entity_catalog is not None
    assert unified.l2_entity_catalog._vector_index is None
    assert unified.l3 is not None and unified.l3._vector_index is None
    assert unified.l4 is not None and unified.l4._vector_index is None

    await unified.clear_all_memory()

    async with aiosqlite.connect(db_path) as db:
        await db.enable_load_extension(True)
        try:
            await db.execute("SELECT load_extension(?)", (sqlite_vec.loadable_path(),))
        finally:
            await db.enable_load_extension(False)
        for registry_table, _, _, _ in vector_specs:
            async with db.execute(f"SELECT COUNT(*) FROM {registry_table}") as cursor:
                assert await cursor.fetchone() == (0,), registry_table
        for vector_table in vector_tables:
            async with db.execute(f'SELECT COUNT(*) FROM "{vector_table}"') as cursor:
                assert await cursor.fetchone() == (0,), vector_table
    assert_sqlite_fragment_absent(db_path, private_marker)


async def test_unified_clear_restarts_pipeline_when_later_quiesce_step_fails(
    tmp_path,
) -> None:
    class Pipeline:
        def __init__(self) -> None:
            self._stats = SimpleNamespace(is_running=True)
            self.abort_calls = 0
            self.start_calls = 0

        async def abort_for_clear(self) -> None:
            self.abort_calls += 1
            self._stats.is_running = False

        async def start(self) -> None:
            self.start_calls += 1
            self._stats.is_running = True

    class ProjectionScheduler:
        async def shutdown(self) -> None:
            raise RuntimeError("projection shutdown failed")

    unified = UnifiedMemoryStore(
        persist_dir=str(tmp_path / "memory"),
        enable_l0=False,
        enable_l1=False,
        enable_l2=False,
        enable_l3=False,
        enable_l4=False,
    )
    pipeline = Pipeline()
    unified.l2_pipeline = pipeline  # type: ignore[assignment]
    unified._portrait_projection_scheduler = ProjectionScheduler()

    with pytest.raises(RuntimeError, match="projection shutdown failed"):
        await unified.clear_all_memory()

    assert pipeline.abort_calls == 1
    assert pipeline.start_calls == 1
    assert pipeline._stats.is_running is True


async def test_unified_clear_reports_writer_restart_failure(tmp_path) -> None:
    class Pipeline:
        def __init__(self) -> None:
            self._stats = SimpleNamespace(is_running=True)
            self.abort_calls = 0
            self.reset_calls = 0
            self.start_calls = 0

        async def abort_for_clear(self) -> None:
            self.abort_calls += 1
            self._stats.is_running = False

        async def reset_after_clear(self) -> None:
            self.reset_calls += 1

        async def start(self) -> None:
            self.start_calls += 1
            raise RuntimeError("pipeline restart failed")

    unified = UnifiedMemoryStore(
        persist_dir=str(tmp_path / "memory"),
        enable_l0=False,
        enable_l1=False,
        enable_l2=False,
        enable_l3=False,
        enable_l4=False,
    )
    pipeline = Pipeline()
    unified.l2_pipeline = pipeline  # type: ignore[assignment]

    with pytest.raises(
        RuntimeError,
        match="Failed to resume memory writers after clear: l2_pipeline",
    ):
        await unified.clear_all_memory()

    assert pipeline.abort_calls == 1
    assert pipeline.reset_calls == 1
    assert pipeline.start_calls == 1


async def test_unified_clear_keeps_clear_failure_when_writer_restart_also_fails(
    tmp_path,
) -> None:
    class L2Store:
        async def clear(
            self,
            *,
            entity_link_clear_generation: int | None = None,
        ) -> int:
            assert entity_link_clear_generation is not None
            raise RuntimeError("l2 clear failed")

    class Pipeline:
        def __init__(self) -> None:
            self._stats = SimpleNamespace(is_running=True)
            self.abort_calls = 0
            self.start_calls = 0

        async def abort_for_clear(self) -> None:
            self.abort_calls += 1
            self._stats.is_running = False

        async def start(self) -> None:
            self.start_calls += 1
            raise RuntimeError("pipeline restart failed")

    unified = UnifiedMemoryStore(
        persist_dir=str(tmp_path / "memory"),
        enable_l0=False,
        enable_l1=False,
        enable_l2=False,
        enable_l3=False,
        enable_l4=False,
    )
    pipeline = Pipeline()
    unified.l2 = L2Store()  # type: ignore[assignment]
    unified.l2_pipeline = pipeline  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="l2 clear failed"):
        await unified.clear_all_memory()

    assert pipeline.abort_calls == 1
    assert pipeline.start_calls == 1


async def test_unified_clear_attempts_later_writer_restarts_after_one_fails(
    tmp_path,
) -> None:
    class RunningWorker:
        @staticmethod
        def done() -> bool:
            return False

    class L4Store:
        def __init__(self) -> None:
            self._embedding_worker = RunningWorker()
            self.abort_calls = 0
            self.initialize_calls = 0

        async def abort_for_clear(self) -> None:
            self.abort_calls += 1

        async def clear(self) -> int:
            return 0

        async def initialize(self) -> None:
            self.initialize_calls += 1
            raise RuntimeError("l4 restart failed")

    class Pipeline:
        def __init__(self) -> None:
            self._stats = SimpleNamespace(is_running=True)
            self.start_calls = 0

        async def abort_for_clear(self) -> None:
            self._stats.is_running = False

        async def reset_after_clear(self) -> None:
            return None

        async def start(self) -> None:
            self.start_calls += 1
            self._stats.is_running = True

    unified = UnifiedMemoryStore(
        persist_dir=str(tmp_path / "memory"),
        enable_l0=False,
        enable_l1=False,
        enable_l2=False,
        enable_l3=False,
        enable_l4=False,
    )
    l4 = L4Store()
    pipeline = Pipeline()
    unified.l4 = l4  # type: ignore[assignment]
    unified.l2_pipeline = pipeline  # type: ignore[assignment]

    with pytest.raises(
        RuntimeError,
        match="Failed to resume memory writers after clear: l4_embedding",
    ):
        await unified.clear_all_memory()

    assert l4.abort_calls == 1
    assert l4.initialize_calls == 1
    assert pipeline.start_calls == 1
    assert pipeline._stats.is_running is True
