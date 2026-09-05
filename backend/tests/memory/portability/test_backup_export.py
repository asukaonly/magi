from __future__ import annotations

import errno
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import zipfile

import pytest

from magi.memory.history_imports.store import HistoryImportStore
from magi.memory.l4.storage.records import soft_delete_skill
from magi.memory.manual_entries.store import ManualEntryStore
import magi.memory.portability.backup as backup_module
import magi.memory.portability.storage as storage_module
from magi.memory.portability.backup import build_memory_backup
from magi.memory.portability.crypto import decrypt_backup_payload, is_encrypted_backup
from magi.memory.portability.errors import MemoryPortabilityError
from magi.memory.portability.export import build_readable_export
from magi.memory.portability.models import SnapshotFile
from magi.memory.portability.storage import create_memory_snapshot, discard_snapshot
from magi.utils.runtime import RuntimePaths

from ._helpers import FakeUnifiedMemory, migrate_memory_databases, seed_memory


@pytest.mark.asyncio
@pytest.mark.parametrize("pending_delete", [False, True])
async def test_readable_export_omits_deleted_content_and_owned_assets(
    tmp_path: Path, pending_delete: bool,
) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    migrate_memory_databases(paths)
    digest, _ = seed_memory(paths)
    _seed_restorable_layers_and_operational_rows(paths)
    with sqlite3.connect(paths.l1_memory_db_path) as connection:
        connection.execute("UPDATE fact_events SET content = 'deleted-event-secret', deleted_at = 2")
        connection.execute(
            "INSERT INTO l1_event_payload(event_id, content, created_at) "
            "VALUES ('event-1', 'deleted-payload-secret', 1)"
        )
    with sqlite3.connect(paths.memory_db_path) as connection:
        connection.execute(
            "UPDATE manual_entries SET body = 'deleted-manual-secret', delete_requested_at = 2"
        )
        connection.execute("UPDATE procedural_skills SET optimized_prompt = 'deleted-procedure-secret'")
        connection.execute(
            "INSERT INTO l4_execution_traces(trace_id, skill_id, event_id, success, "
            "input_summary, created_at) VALUES ('trace-1', 'skill-keep', 'event-1', 1, "
            "'deleted-trace-secret', 1)"
        )
        connection.execute(
            "INSERT INTO memory_source_event_tombstones(event_id, reason, created_at) "
            "VALUES ('event-1', 'user_delete', 2)"
        )
    if not pending_delete:
        assert await ManualEntryStore(db_path=str(paths.memory_db_path)).finalize_delete(
            "entry-1", deleted_at=2,
        )
    await soft_delete_skill(db_path=str(paths.memory_db_path), skill_id="skill-keep", now=2)
    snapshot = await create_memory_snapshot(
        runtime_paths=paths, archive_dir=paths.memory_dir / "archive",
        unified_memory=None, include_l0=False,
    )
    # A backup may retain an asset owned only by a non-exported draft.
    snapshot.files.append(SnapshotFile(
        source_path=paths.manual_entry_assets_dir / digest[:2] / f"{digest}.png",
        archive_path=f"assets/manual_entries/{digest[:2]}/{digest}.png",
        purpose="manual_entry_asset",
    ))
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    try:
        output_path, manifest = build_readable_export(
            snapshot=snapshot, output_directory=output_dir, include_l0=False,
        )
        with zipfile.ZipFile(output_path) as archive:
            content = b"\n".join(archive.read(name) for name in archive.namelist())
            for secret in (b"deleted-event-secret", b"deleted-payload-secret", b"deleted-manual-secret",
                           b"deleted-procedure-secret", b"deleted-trace-secret"):
                assert secret not in content
            assert digest not in "\n".join(archive.namelist())
            assert json.loads(archive.read("governance/forgotten_source_events.jsonl"))["source_event_id"] == "event-1"
            for name in ("l1/events.jsonl", "l1/source_payloads.jsonl", "l2/manual_entries.jsonl",
                         "l4/procedures.jsonl", "l4/execution_traces.jsonl"):
                assert archive.read(name) == b""
                assert manifest["files"][name]["record_count"] == 0
            assert b"Kept Entity" in archive.read("l2/entities.jsonl")
    finally:
        discard_snapshot(snapshot)


def _seed_restorable_layers_and_operational_rows(paths: RuntimePaths) -> None:
    with sqlite3.connect(paths.memory_db_path) as connection:
        connection.executescript(
            """
            INSERT INTO entity_catalog(
                entity_id, canonical_name, entity_type, created_at, updated_at
            ) VALUES ('entity-keep', 'Kept Entity', 'person', 1, 1);
            INSERT INTO knowledge_graph(
                triple_id, subject_id, subject_type, predicate, object_id, object_type,
                evidence_event_ids, first_observed_at, last_observed_at, created_at, updated_at
            ) VALUES (
                'edge-keep', 'entity-keep', 'person', 'knows', 'entity-other', 'person',
                '["event-1"]', 1, 1, 1, 1
            );
            INSERT INTO summaries(
                summary_id, summary_type, summary_category, period_start, period_end,
                content, source_event_ids, source_event_count, created_at, updated_at
            ) VALUES (
                'summary-keep', 'daily', 'general', 1, 2, 'Kept summary',
                '["event-1"]', 1, 1, 1
            );
            INSERT INTO procedural_skills(
                skill_id, skill_name, skill_category, skill_type,
                source_event_ids, created_at, updated_at
            ) VALUES (
                'skill-keep', 'Kept skill', 'general', 'procedure', '["event-1"]', 1, 1
            );
            INSERT INTO memory_corrections(
                correction_id, request_id, actor_id, target_kind, target_id,
                slot_key, claim_fingerprint, correction_kind, before_json,
                replacement_json, state, created_at
            ) VALUES (
                'correction-keep', 'request-keep', 'user:self', 'edge', 'edge-keep',
                'slot-keep', 'claim-keep', 'record_error', '{"value":"old"}',
                '{"value":"new"}', 'active', 1
            );
            INSERT INTO memory_derivation_dependencies(
                artifact_kind, artifact_id, source_kind, source_id,
                subject_key, source_revision, created_at
            ) VALUES ('summary', 'summary-keep', 'edge', 'edge-keep', 'entity-keep', 1, 1);

            INSERT INTO l2_projection_jobs(
                event_id, source, event_type, status, created_at, updated_at
            ) VALUES ('operational-event', 'test', 'test', 'pending', 1, 1);
            INSERT INTO l2_event_entity_link_outbox(
                event_id, revision, batch_key, lease_token, attempt_count,
                clear_generation, desired_links_json, state, created_at, updated_at
            ) VALUES (
                'operational-event', 1, 'batch-1', 'lease-1', 1, 0,
                '[]', 'pending', 1, 1
            );
            INSERT INTO embedding_rebuild_jobs(
                job_id, status, requested_layers_json, created_at, updated_at
            ) VALUES ('embedding-job', 'running', '["l2"]', 1, 1);
            INSERT INTO embedding_rebuild_job_layers(
                job_id, layer, status, updated_at
            ) VALUES ('embedding-job', 'l2', 'running', 1);
            INSERT INTO memory_derivation_jobs(
                job_id, correction_id, job_kind, target_key, target_revision,
                status, created_at, updated_at
            ) VALUES (
                'derivation-job', 'correction-keep', 'l3_insight', 'summary-keep', 1,
                'pending', 1, 1
            );
            INSERT INTO place_geocode_cache(grid_key, city, cached_at)
            VALUES ('cache-grid', 'Private City', 1);
            INSERT INTO l3_summary_chunks(
                chunk_id, summary_id, chunk_index, chunk_text, char_start,
                char_end, token_estimate, created_at, updated_at
            ) VALUES ('summary-cache', 'summary-keep', 0, 'cache text', 0, 10, 2, 1, 1);
            INSERT INTO l4_skill_chunks(
                chunk_id, skill_id, chunk_index, chunk_text, char_start,
                char_end, token_estimate, created_at, updated_at
            ) VALUES ('skill-cache', 'skill-keep', 0, 'cache text', 0, 10, 2, 1, 1);
            """
        )
        connection.commit()


@pytest.mark.asyncio
async def test_restorable_snapshot_keeps_l0_governance_and_assets_but_excludes_chat(
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    migrate_memory_databases(paths)
    digest, orphan_digest = seed_memory(paths)
    memory = FakeUnifiedMemory()

    snapshot = await create_memory_snapshot(
        runtime_paths=paths,
        archive_dir=paths.memory_dir / "archive",
        unified_memory=memory,
        include_l0=True,
    )
    try:
        assert memory.guard_entries == 1
        assert memory.l0.checkpoint_calls == 1
        l1_path = Path(snapshot.root) / "databases" / "l1_events.db"
        shared_path = Path(snapshot.root) / "databases" / "memory.db"
        with sqlite3.connect(l1_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM fact_events").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM chat_sessions").fetchone()[0] == 0
        with sqlite3.connect(shared_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM l0_sessions").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM l0_attention_items").fetchone()[0] == 1
            assert connection.execute("SELECT summary FROM l0_attention_items").fetchone()[0] == (
                "short term secret"
            )
            assert (
                connection.execute(
                    "SELECT source_ref FROM l0_forgotten_attention_source_refs"
                ).fetchone()[0]
                == "turn:forgotten"
            )
            assert (
                connection.execute("SELECT content FROM history_import_source_records").fetchone()[
                    0
                ]
                == ""
            )
            assert connection.execute(
                "SELECT raw_state, projection_state FROM history_import_job_records"
            ).fetchone() == ("stored", "projected")
        assert b"private chat" not in l1_path.read_bytes()
        assert b"short term secret" in shared_path.read_bytes()
        assert b"raw imported transcript secret" not in shared_path.read_bytes()
        asset_paths = {
            item.archive_path for item in snapshot.files if item.purpose == "manual_entry_asset"
        }
        assert asset_paths == {f"assets/manual_entries/{digest[:2]}/{digest}.png"}
        assert orphan_digest.decode("ascii") not in "\n".join(asset_paths)
    finally:
        discard_snapshot(snapshot)


@pytest.mark.asyncio
async def test_snapshot_redacts_shared_history_source_without_losing_delete_ownership(
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    migrate_memory_databases(paths)
    seed_memory(paths)
    with sqlite3.connect(paths.memory_db_path) as connection:
        connection.execute(
            """
            UPDATE history_import_jobs
            SET source_ids_json = '["source-secret"]',
                included_source_ids_json = '["source-secret"]',
                self_participant_ids_json = '["self-secret"]',
                status = 'completed', importer_plugin_id = 'plugin-secret',
                importer_id = 'importer-secret', importer_format_version = 'secret-v1'
            WHERE job_id = 'import-1'
            """
        )
        connection.execute(
            """
            UPDATE history_import_source_records
            SET source_id = 'source-secret', source_kind = 'chat',
                speaker_id = 'self-secret', speaker_name = 'Alice Secret',
                message_key = 'message-secret', source_name = 'account-secret.json',
                content = 'shared imported transcript secret'
            WHERE source_record_key = 'source-1'
            """
        )
        connection.execute(
            """
            INSERT INTO history_import_jobs(
                job_id, source_type, source_fingerprint, source_ids_json,
                included_source_ids_json, detected_kind, status,
                self_participant_ids_json, created_at, updated_at
            ) VALUES (
                'import-2', 'chat_export', 'fingerprint-secret-2', '["source-secret"]',
                '["source-secret"]', 'chat', 'completed', '["self-secret"]', 2, 2
            )
            """
        )
        connection.execute(
            """
            INSERT INTO history_import_job_records(
                job_record_id, job_id, source_record_key, raw_state,
                projection_state, source_order, created_at, updated_at
            ) VALUES (
                'job-record-2', 'import-2', 'source-1', 'stored',
                'projected', 0, 2, 2
            )
            """
        )
        connection.commit()

    snapshot = await create_memory_snapshot(
        runtime_paths=paths,
        archive_dir=paths.memory_dir / "archive",
        unified_memory=FakeUnifiedMemory(),
        include_l0=True,
    )
    try:
        shared_path = Path(snapshot.root) / "databases" / "memory.db"
        raw_snapshot = shared_path.read_bytes()
        for secret in (
            b"source-secret",
            b"self-secret",
            b"Alice Secret",
            b"account-secret.json",
            b"shared imported transcript secret",
            b"plugin-secret",
            b"importer-secret",
            b"secret-v1",
        ):
            assert secret not in raw_snapshot

        with sqlite3.connect(shared_path) as connection:
            source = connection.execute(
                """
                SELECT source_record_key, source_id, speaker_id, source_name,
                       speaker_name, content, source_kind
                FROM history_import_source_records
                """
            ).fetchone()
            assert source is not None
            assert source[0].startswith("backup-record-")
            assert source[1].startswith("backup-source-")
            assert source[2].startswith("backup-participant-")
            assert source[3:6] == ("", "", "")
            assert source[6] == "restored_memory"
            jobs = connection.execute(
                """
                SELECT status, source_ids_json, included_source_ids_json,
                       self_participant_ids_json, importer_plugin_id, importer_id,
                       importer_format_version
                FROM history_import_jobs
                ORDER BY job_id
                """
            ).fetchall()
            assert len(jobs) == 2
            assert jobs[0][0] == jobs[1][0] == "completed"
            assert jobs[0][1:4] == jobs[1][1:4]
            assert json.loads(jobs[0][1]) == [source[1]]
            assert json.loads(jobs[0][2]) == [source[1]]
            assert json.loads(jobs[0][3]) == [source[2]]
            assert jobs[0][4:] == jobs[1][4:] == (None, None, None)

        store = HistoryImportStore(db_path=str(shared_path))
        assert await store.list_unreferenced_event_ids_for_delete(job_id="import-1") == []
        await store.mark_deleted(job_id="import-1")
        assert await store.list_unreferenced_event_ids_for_delete(job_id="import-2") == [
            "import-event-1"
        ]
        with sqlite3.connect(shared_path) as connection:
            assert (
                connection.execute("SELECT COUNT(*) FROM history_import_source_records").fetchone()[
                    0
                ]
                == 1
            )
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM history_import_job_records WHERE job_id = 'import-2'"
                ).fetchone()[0]
                == 1
            )
    finally:
        discard_snapshot(snapshot)


@pytest.mark.asyncio
async def test_backup_package_has_versioned_manifest_and_encrypted_round_trip(
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    migrate_memory_databases(paths)
    digest, _orphan_digest = seed_memory(paths)
    _seed_restorable_layers_and_operational_rows(paths)
    snapshot = await create_memory_snapshot(
        runtime_paths=paths,
        archive_dir=paths.memory_dir / "archive",
        unified_memory=FakeUnifiedMemory(),
        include_l0=True,
    )
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    try:
        output_path, manifest = build_memory_backup(
            snapshot=snapshot,
            output_directory=output_dir,
            encryption="password",
            password="correct horse battery staple",
        )
        assert is_encrypted_backup(output_path) is True
        assert manifest.format_version == 1
        assert manifest.encrypted is True
        assert manifest.scope[0] == "l0"
        assert manifest.counts["l0_sessions"] == 1
        assert manifest.counts["l0_attention_items"] == 1
        assert f"assets/manual_entries/{digest[:2]}/{digest}.png" in {
            record.path for record in manifest.files
        }

        payload_path = tmp_path / "payload.zip"
        decrypt_backup_payload(output_path, payload_path, "correct horse battery staple")
        packaged_l1_path = tmp_path / "packaged-l1.db"
        packaged_memory_path = tmp_path / "packaged-memory.db"
        with zipfile.ZipFile(payload_path) as archive:
            stored_manifest = json.loads(archive.read("manifest.json"))
            packaged_l1_path.write_bytes(archive.read("databases/l1_events.db"))
            packaged_memory_path.write_bytes(archive.read("databases/memory.db"))
            assert stored_manifest["format"] == "magi-memory-backup"
            assert stored_manifest["scope"] == [
                "l0",
                "l1",
                "l2",
                "l3",
                "l4",
                "archives",
                "manual_entry_assets",
            ]
        with sqlite3.connect(packaged_l1_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM fact_events").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM chat_sessions").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM l1_event_chunks").fetchone()[0] == 0
        with sqlite3.connect(packaged_memory_path) as connection:
            for table in storage_module.PORTABILITY_OPERATIONAL_TABLES:
                assert connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM l3_summary_chunks").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM l4_skill_chunks").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM l0_sessions").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM l0_attention_items").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM entity_catalog").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM knowledge_graph").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM summaries").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM procedural_skills").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM memory_corrections").fetchone()[0] == 1
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM memory_derivation_dependencies"
                ).fetchone()[0]
                == 1
            )
            assert (
                connection.execute("SELECT content FROM history_import_source_records").fetchone()[
                    0
                ]
                == ""
            )
        with pytest.raises(MemoryPortabilityError) as wrong_password:
            decrypt_backup_payload(output_path, tmp_path / "wrong.zip", "wrong password")
        assert wrong_password.value.code == "password_or_integrity_invalid"
        assert not (tmp_path / "wrong.zip").exists()

        with pytest.raises(MemoryPortabilityError) as empty_password:
            build_memory_backup(
                snapshot=snapshot,
                output_directory=output_dir,
                encryption="password",
                password="   ",
            )
        assert empty_password.value.code == "password_required"
    finally:
        discard_snapshot(snapshot)


@pytest.mark.asyncio
async def test_snapshot_space_budget_covers_all_copies_and_vacuum_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    migrate_memory_databases(paths)
    seed_memory(paths)
    archive_dir = paths.memory_dir / "archive"
    archive_dir.mkdir(parents=True)
    archive_path = archive_dir / "2026-08-01.db"
    with sqlite3.connect(archive_path) as connection:
        connection.execute("CREATE TABLE archived_rows (id TEXT PRIMARY KEY, payload TEXT)")
        connection.execute("INSERT INTO archived_rows VALUES ('row-1', 'archive payload')")
        connection.commit()

    l1_bytes = storage_module._database_snapshot_bytes(paths.l1_memory_db_path)
    memory_bytes = storage_module._database_snapshot_bytes(paths.memory_db_path)
    archive_bytes = storage_module._database_snapshot_bytes(archive_path)
    asset_bytes = sum(
        source.stat().st_size
        for source, _relative_path in storage_module._collect_referenced_asset_paths(
            paths.memory_db_path,
            paths.manual_entry_assets_dir,
        )
    )
    required_bytes = (
        l1_bytes + memory_bytes + archive_bytes + asset_bytes + max(l1_bytes, memory_bytes)
    )
    assert storage_module._snapshot_required_bytes(paths, archive_dir) == required_bytes

    monkeypatch.setattr(
        storage_module.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=required_bytes - 1),
    )
    with pytest.raises(MemoryPortabilityError) as insufficient:
        await create_memory_snapshot(
            runtime_paths=paths,
            archive_dir=archive_dir,
            unified_memory=FakeUnifiedMemory(),
            include_l0=True,
        )
    assert insufficient.value.code == "insufficient_space"
    assert not list(paths.memory_portability_dir.glob("snapshot-*"))

    monkeypatch.setattr(
        storage_module.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=required_bytes),
    )
    snapshot = await create_memory_snapshot(
        runtime_paths=paths,
        archive_dir=archive_dir,
        unified_memory=FakeUnifiedMemory(),
        include_l0=True,
    )
    discard_snapshot(snapshot)


@pytest.mark.asyncio
async def test_backup_aggregates_payload_and_partial_space_on_shared_filesystem(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    migrate_memory_databases(paths)
    seed_memory(paths)
    snapshot = await create_memory_snapshot(
        runtime_paths=paths,
        archive_dir=paths.memory_dir / "archive",
        unified_memory=FakeUnifiedMemory(),
        include_l0=True,
    )
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    checks: list[tuple[Path, int]] = []
    monkeypatch.setattr(
        backup_module,
        "_require_free_space",
        lambda directory, required: checks.append((Path(directory), int(required))),
    )
    try:
        expected_payload_bytes = (
            sum(Path(item.source_path).stat().st_size for item in snapshot.files) + 1024 * 1024
        )
        build_memory_backup(
            snapshot=snapshot,
            output_directory=output_dir,
            encryption="none",
            password=None,
        )
        assert checks == [(Path(snapshot.root), expected_payload_bytes * 2)]
    finally:
        discard_snapshot(snapshot)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failing_write", "error_number"),
    [
        ("_open_private_exclusive", errno.ENOSPC),
        ("_copy_exclusive", getattr(errno, "EDQUOT", errno.ENOSPC)),
    ],
)
async def test_backup_maps_write_time_capacity_failures_to_insufficient_space(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failing_write: str,
    error_number: int,
) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    migrate_memory_databases(paths)
    seed_memory(paths)
    snapshot = await create_memory_snapshot(
        runtime_paths=paths,
        archive_dir=paths.memory_dir / "archive",
        unified_memory=FakeUnifiedMemory(),
        include_l0=True,
    )
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    def no_space(*_args: object, **_kwargs: object) -> None:
        raise OSError(error_number, "capacity exhausted")

    monkeypatch.setattr(backup_module, failing_write, no_space)
    try:
        with pytest.raises(MemoryPortabilityError) as failure:
            build_memory_backup(
                snapshot=snapshot,
                output_directory=output_dir,
                encryption="none",
                password=None,
            )
        assert failure.value.code == "insufficient_space"
        assert list(output_dir.iterdir()) == []
        assert not (Path(snapshot.root) / "backup-payload.zip").exists()
    finally:
        discard_snapshot(snapshot)


@pytest.mark.asyncio
async def test_backup_rejects_oversized_member_before_manifest_validation(
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    migrate_memory_databases(paths)
    seed_memory(paths)
    snapshot = await create_memory_snapshot(
        runtime_paths=paths,
        archive_dir=paths.memory_dir / "archive",
        unified_memory=FakeUnifiedMemory(),
        include_l0=True,
    )
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    oversized = Path(snapshot.root) / "oversized-asset.png"
    with oversized.open("wb") as handle:
        handle.truncate(backup_module.MAX_BACKUP_MEMBER_BYTES + 1)
    snapshot.files.append(
        snapshot.files[0].model_copy(
            update={
                "source_path": oversized,
                "archive_path": f"assets/manual_entries/00/{'0' * 64}.png",
                "purpose": "manual_entry_asset",
            }
        )
    )
    try:
        with pytest.raises(MemoryPortabilityError) as failure:
            build_memory_backup(
                snapshot=snapshot,
                output_directory=output_dir,
                encryption="none",
                password=None,
            )
        assert failure.value.code == "backup_too_large"
        assert list(output_dir.iterdir()) == []
    finally:
        discard_snapshot(snapshot)


@pytest.mark.asyncio
async def test_readable_export_uses_jsonl_and_never_exports_internal_jobs(
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    migrate_memory_databases(paths)
    seed_memory(paths)
    memory = FakeUnifiedMemory()
    snapshot = await create_memory_snapshot(
        runtime_paths=paths,
        archive_dir=paths.memory_dir / "archive",
        unified_memory=memory,
        include_l0=True,
    )
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    try:
        output_path, manifest = build_readable_export(
            snapshot=snapshot,
            output_directory=output_dir,
            include_l0=True,
        )
        assert memory.l0.checkpoint_calls == 1
        assert manifest["restorable"] is False
        with zipfile.ZipFile(output_path) as archive:
            names = set(archive.namelist())
            assert "l1/events.jsonl" in names
            assert "l2/manual_entries.jsonl" in names
            assert "l0/attention_items.jsonl" in names
            assert not any("embedding_rebuild_jobs" in name for name in names)
            first_event = json.loads(archive.read("l1/events.jsonl").splitlines()[0])
            assert first_event["content"] == "hello"
    finally:
        discard_snapshot(snapshot)
