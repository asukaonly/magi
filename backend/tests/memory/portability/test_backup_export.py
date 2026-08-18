from __future__ import annotations

from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import zipfile

import pytest

from magi.db.runner import MIGRATION_TARGETS, run_upgrade_head
from magi.memory.portability.backup import build_memory_backup
from magi.memory.portability.crypto import decrypt_backup_payload, is_encrypted_backup
from magi.memory.portability.errors import MemoryPortabilityError
from magi.memory.portability.export import build_readable_export
from magi.memory.portability.storage import create_memory_snapshot, discard_snapshot
from magi.utils.runtime import RuntimePaths


class _FakeL0:
    def __init__(self) -> None:
        self.checkpoint_calls = 0

    async def checkpoint_all(self) -> None:
        self.checkpoint_calls += 1


class _FakeUnifiedMemory:
    def __init__(self) -> None:
        self.guard_entries = 0
        self.l0 = _FakeL0()

    @asynccontextmanager
    async def memory_maintenance_guard(self):
        self.guard_entries += 1
        yield


def _migrate_memory_databases(paths: RuntimePaths) -> None:
    selected = tuple(
        target for target in MIGRATION_TARGETS if target.name in {"l1", "memory_shared"}
    )
    run_upgrade_head(paths, targets=selected)


def _seed_memory(paths: RuntimePaths) -> tuple[str, bytes]:
    asset_bytes = b"referenced-private-image"
    digest = hashlib.sha256(asset_bytes).hexdigest()
    asset_ref = f"manual-entry-asset://{digest}.png"
    asset_path = paths.manual_entry_assets_dir / digest[:2] / f"{digest}.png"
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path.write_bytes(asset_bytes)

    orphan_bytes = b"orphan-private-image"
    orphan_digest = hashlib.sha256(orphan_bytes).hexdigest()
    orphan_path = paths.manual_entry_assets_dir / orphan_digest[:2] / f"{orphan_digest}.png"
    orphan_path.parent.mkdir(parents=True, exist_ok=True)
    orphan_path.write_bytes(orphan_bytes)

    with sqlite3.connect(paths.l1_memory_db_path) as connection:
        connection.execute("""
            INSERT INTO fact_events(
                event_id, timestamp, created_at, event_type, source, memory_domain,
                content, author_type, content_type
            ) VALUES ('event-1', 1, 1, 'manual_entry', 'manual_entry', 1, 'hello', 1, 1)
            """)
        connection.execute("""
            INSERT INTO chat_sessions(
                session_id, user_id, title, title_overridden, summary, created_at,
                updated_at, last_message_preview, last_user_message_preview, message_count
            ) VALUES ('chat-secret', 'user', 'private chat', 0, '', 1, 1, '', '', 0)
            """)
        connection.commit()

    with sqlite3.connect(paths.memory_db_path) as connection:
        connection.execute("""
            INSERT INTO l0_sessions(
                session_id, user_id, status, started_at, last_active_at, metadata
            ) VALUES ('session-1', 'user', 'active', 1, 1, '{"secret":"short term"}')
            """)
        connection.execute("""
            INSERT INTO l0_attention_items(
                item_id, session_id, kind, summary, status, salience, confidence,
                evidence_mode, first_seen_at, last_reinforced_at, metadata
            ) VALUES (
                'attention-1', 'session-1', 'topic', 'short term secret', 'active',
                1, 1, 'explicit', 1, 1, '{}'
            )
            """)
        connection.execute("""
            INSERT INTO l0_forgotten_attention_source_refs(source_ref, created_at)
            VALUES ('turn:forgotten', 1)
            """)
        connection.execute(
            """
            INSERT INTO manual_entries(entry_id, created_at, event_at, body, attachments_json)
            VALUES ('entry-1', 1, 1, 'a memory', ?)
            """,
            (json.dumps([asset_ref]),),
        )
        connection.execute("""
            INSERT INTO history_import_jobs(
                job_id, source_type, source_fingerprint, detected_kind, status,
                created_at, updated_at
            ) VALUES ('import-1', 'chat_export', 'fingerprint', 'chat', 'succeeded', 1, 1)
            """)
        connection.execute("""
            INSERT INTO history_import_source_records(
                source_record_key, file_fingerprint, source_name, parsed_session_key,
                session_id, session_seq, speaker_name, content, event_at,
                timestamp_confidence, timestamp_anchor_source, calendar_timezone_id,
                event_id, created_at
            ) VALUES (
                'source-1', 'file-1', 'import.json', 'parsed-1', 'import-session', 1,
                'speaker', 'raw imported transcript secret', 1, 'exact', 'source',
                'UTC', 'import-event-1', 1
            )
            """)
        connection.execute("""
            INSERT INTO history_import_job_records(
                job_record_id, job_id, source_record_key, raw_state, projection_state,
                created_at, updated_at
            ) VALUES ('job-record-1', 'import-1', 'source-1', 'stored', 'projected', 1, 1)
            """)
        connection.commit()
    return digest, orphan_digest.encode("ascii")


@pytest.mark.asyncio
async def test_snapshot_excludes_chat_and_disposable_l0_but_keeps_governance_and_referenced_assets(
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    _migrate_memory_databases(paths)
    digest, orphan_digest = _seed_memory(paths)
    memory = _FakeUnifiedMemory()

    snapshot = await create_memory_snapshot(
        runtime_paths=paths,
        archive_dir=paths.memory_dir / "archive",
        unified_memory=memory,
        include_l0=False,
    )
    try:
        assert memory.guard_entries == 1
        assert memory.l0.checkpoint_calls == 0
        l1_path = Path(snapshot.root) / "databases" / "l1_events.db"
        shared_path = Path(snapshot.root) / "databases" / "memory.db"
        with sqlite3.connect(l1_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM fact_events").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM chat_sessions").fetchone()[0] == 0
        with sqlite3.connect(shared_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM l0_sessions").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM l0_attention_items").fetchone()[0] == 0
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
        assert b"short term secret" not in shared_path.read_bytes()
        assert b"raw imported transcript secret" not in shared_path.read_bytes()
        asset_paths = {
            item.archive_path for item in snapshot.files if item.purpose == "manual_entry_asset"
        }
        assert asset_paths == {f"assets/manual_entries/{digest[:2]}/{digest}.png"}
        assert orphan_digest.decode("ascii") not in "\n".join(asset_paths)
    finally:
        discard_snapshot(snapshot)


@pytest.mark.asyncio
async def test_backup_package_has_versioned_manifest_and_encrypted_round_trip(
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    _migrate_memory_databases(paths)
    digest, _orphan_digest = _seed_memory(paths)
    snapshot = await create_memory_snapshot(
        runtime_paths=paths,
        archive_dir=paths.memory_dir / "archive",
        unified_memory=_FakeUnifiedMemory(),
        include_l0=False,
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
        assert f"assets/manual_entries/{digest[:2]}/{digest}.png" in {
            record.path for record in manifest.files
        }

        payload_path = tmp_path / "payload.zip"
        decrypt_backup_payload(output_path, payload_path, "correct horse battery staple")
        with zipfile.ZipFile(payload_path) as archive:
            stored_manifest = json.loads(archive.read("manifest.json"))
            assert stored_manifest["format"] == "magi-memory-backup"
            assert stored_manifest["scope"] == [
                "l1",
                "l2",
                "l3",
                "l4",
                "archives",
                "manual_entry_assets",
            ]
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
async def test_readable_export_uses_jsonl_and_never_exports_internal_jobs(
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    _migrate_memory_databases(paths)
    _seed_memory(paths)
    memory = _FakeUnifiedMemory()
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
            assert "l1/fact_events.jsonl" in names
            assert "memory/manual_entries.jsonl" in names
            assert "memory/l0_attention_items.jsonl" in names
            assert not any("embedding_rebuild_jobs" in name for name in names)
            first_event = json.loads(archive.read("l1/fact_events.jsonl").splitlines()[0])
            assert first_event["content"] == "hello"
    finally:
        discard_snapshot(snapshot)
