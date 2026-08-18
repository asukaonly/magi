from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import zipfile

from alembic.util import CommandError
import pytest
import sqlite_vec

from magi.db.runner import (
    MigrationExecutionError,
    migration_head,
    run_upgrade_database,
)
from magi.memory.portability import preflight as preflight_module
from magi.memory.portability.backup import build_memory_backup
from magi.memory.portability.errors import MemoryPortabilityError
from magi.memory.portability.models import SnapshotBundle, SnapshotFile
from magi.memory.portability.preflight import (
    inspect_memory_backup,
    load_restore_candidate,
)
from magi.memory.portability.storage import (
    count_snapshot_records,
    create_memory_snapshot,
    database_revision,
    discard_snapshot,
)
from magi.utils.runtime import RuntimePaths

from ._helpers import FakeUnifiedMemory, migrate_memory_databases, seed_memory


def _load_sqlite_vec(connection: sqlite3.Connection) -> None:
    connection.enable_load_extension(True)
    try:
        connection.load_extension(sqlite_vec.loadable_path())
    finally:
        connection.enable_load_extension(False)


def _create_archive_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE archived_l1_events (
                event_id TEXT PRIMARY KEY,
                archived_date TEXT NOT NULL,
                archived_at REAL NOT NULL,
                event_timestamp REAL NOT NULL,
                event_type TEXT NOT NULL,
                source TEXT NOT NULL,
                session_id TEXT,
                user_id TEXT,
                payload_json TEXT NOT NULL
            );
            CREATE INDEX idx_archived_l1_events_date
                ON archived_l1_events(archived_date, event_timestamp);
            CREATE TABLE archived_l3_summaries (
                summary_id TEXT PRIMARY KEY,
                archived_date TEXT NOT NULL,
                archived_at REAL NOT NULL,
                period_start REAL NOT NULL,
                period_end REAL NOT NULL,
                summary_type TEXT NOT NULL,
                summary_category TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE INDEX idx_archived_l3_summaries_date
                ON archived_l3_summaries(archived_date, period_end);
            INSERT INTO archived_l1_events VALUES (
                'archive-event', '2026-08-01', 1, 1, 'manual_entry',
                'manual_entry', NULL, NULL, '{}'
            );
            INSERT INTO archived_l3_summaries VALUES (
                'archive-summary', '2026-08-01', 1, 1, 2, 'daily', 'general', '{}'
            );
            """
        )
        connection.commit()


def _replace_archive_l1_table_without_primary_key(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        DROP INDEX idx_archived_l1_events_date;
        ALTER TABLE archived_l1_events RENAME TO archived_l1_events_old;
        CREATE TABLE archived_l1_events (
            event_id TEXT,
            archived_date TEXT NOT NULL,
            archived_at REAL NOT NULL,
            event_timestamp REAL NOT NULL,
            event_type TEXT NOT NULL,
            source TEXT NOT NULL,
            session_id TEXT,
            user_id TEXT,
            payload_json TEXT NOT NULL
        );
        INSERT INTO archived_l1_events
        SELECT * FROM archived_l1_events_old;
        DROP TABLE archived_l1_events_old;
        CREATE INDEX idx_archived_l1_events_date
        ON archived_l1_events(archived_date, event_timestamp);
        """
    )


async def _build_backup(
    tmp_path: Path,
    *,
    encryption: str = "none",
    password: str | None = None,
) -> tuple[RuntimePaths, Path, object]:
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
    try:
        output_path, manifest = build_memory_backup(
            snapshot=snapshot,
            output_directory=output_dir,
            encryption=encryption,
            password=password,
        )
    finally:
        discard_snapshot(snapshot)
    return paths, output_path, manifest


@pytest.mark.asyncio
async def test_preflight_stages_private_immutable_post_validation_files(tmp_path: Path) -> None:
    paths, backup_path, manifest = await _build_backup(tmp_path)
    archive_target = paths.memory_dir / "archive"
    archive_target.mkdir(parents=True, exist_ok=True)

    inspection = inspect_memory_backup(
        source_path=backup_path,
        password=None,
        runtime_paths=paths,
        archive_target=archive_target,
    )

    assert inspection.compatibility == "compatible"
    assert inspection.counts == manifest.counts
    assert inspection.scope[0] == "l0"
    assert inspection.counts["l0_sessions"] == 1
    assert inspection.counts["l0_attention_items"] == 1
    candidate_root, metadata, candidate_manifest = load_restore_candidate(
        runtime_paths=paths,
        candidate_id=str(inspection.candidate_id),
        fingerprint=inspection.fingerprint,
    )
    assert candidate_manifest == manifest
    assert "staged_files" in metadata
    assert "source_path" not in metadata
    assert "password" not in metadata
    assert not (candidate_root / "source.magibackup").exists()
    assert not (candidate_root / "payload.zip").exists()
    with sqlite3.connect(candidate_root / "payload" / "databases" / "memory.db") as connection:
        assert connection.execute("SELECT COUNT(*) FROM l0_sessions").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM l0_attention_items").fetchone()[0] == 1
        assert (
            connection.execute("SELECT source_turn_ids FROM l0_attention_items").fetchone()[0]
            == '["chat-turn-secret"]'
        )
    if os.name != "nt":
        assert candidate_root.stat().st_mode & 0o077 == 0
        assert (candidate_root / "candidate.json").stat().st_mode & 0o077 == 0

    for record in metadata["staged_files"]:
        staged_path = candidate_root / "payload" / record["path"]
        assert staged_path.stat().st_size == record["size_bytes"]
        assert hashlib.sha256(staged_path.read_bytes()).hexdigest() == record["sha256"]

    first_record = metadata["staged_files"][0]
    changed_path = candidate_root / "payload" / first_record["path"]
    changed_path.write_bytes(changed_path.read_bytes() + b"changed")
    with pytest.raises(MemoryPortabilityError) as changed:
        load_restore_candidate(
            runtime_paths=paths,
            candidate_id=str(inspection.candidate_id),
        )
    assert changed.value.code == "candidate_changed"
    assert not candidate_root.exists()


@pytest.mark.asyncio
async def test_preflight_candidate_expiry_is_fingerprinted_and_destructive(tmp_path: Path) -> None:
    paths, backup_path, _manifest = await _build_backup(tmp_path)
    archive_target = paths.memory_dir / "archive"
    archive_target.mkdir(parents=True, exist_ok=True)
    inspection = inspect_memory_backup(
        source_path=backup_path,
        password=None,
        runtime_paths=paths,
        archive_target=archive_target,
    )
    candidate_root = paths.memory_portability_dir / "candidates" / str(inspection.candidate_id)
    metadata_path = candidate_root / "candidate.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["expires_at"] = "2000-01-01T00:00:00Z"
    canonical = dict(metadata)
    canonical.pop("fingerprint")
    metadata["fingerprint"] = hashlib.sha256(
        json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    metadata_path.write_text(
        json.dumps(
            metadata,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    if os.name != "nt":
        metadata_path.chmod(0o600)

    with pytest.raises(MemoryPortabilityError) as expired:
        load_restore_candidate(
            runtime_paths=paths,
            candidate_id=str(inspection.candidate_id),
        )
    assert expired.value.code == "candidate_expired"
    assert not candidate_root.exists()


@pytest.mark.asyncio
async def test_backup_writer_emits_non_zip64_file_counts(tmp_path: Path) -> None:
    _paths, backup_path, manifest = await _build_backup(tmp_path)

    with zipfile.ZipFile(backup_path) as archive:
        infos = archive.infolist()
        stored_manifest = json.loads(archive.read("manifest.json"))

    assert all(info.extract_version < 45 for info in infos)
    assert all(b"\x01\x00" not in info.extra for info in infos)
    by_path = {record.path: record for record in manifest.files}
    assert stored_manifest["files"] == [record.model_dump(mode="json") for record in manifest.files]
    assert by_path["databases/l1_events.db"].record_count == 1
    assert by_path["databases/memory.db"].record_count >= 3
    assert manifest.counts["l0_sessions"] == 1
    assert manifest.counts["l0_attention_items"] == 1
    assert all(record.record_count >= 0 for record in manifest.files)


def _rewrite_manifest(backup_path: Path, mutate) -> Path:
    with zipfile.ZipFile(backup_path) as source:
        members = {info.filename: source.read(info) for info in source.infolist()}
    payload = json.loads(members["manifest.json"])
    mutate(payload)
    members["manifest.json"] = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    rewritten = backup_path.with_name("rewritten.magibackup")
    with zipfile.ZipFile(
        rewritten,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        allowZip64=False,
    ) as destination:
        for name, content in members.items():
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100600 << 16
            destination.writestr(info, content)
    return rewritten


def _read_backup_members(backup_path: Path) -> list[tuple[str, bytes]]:
    with zipfile.ZipFile(backup_path) as source:
        return [(info.filename, source.read(info)) for info in source.infolist()]


def _write_backup_members(
    output_path: Path,
    members: list[tuple[str, bytes]],
    *,
    compression: int = zipfile.ZIP_DEFLATED,
    force_zip64: bool = False,
) -> Path:
    with zipfile.ZipFile(
        output_path,
        mode="w",
        compression=compression,
        allowZip64=True,
    ) as destination:
        for index, (name, content) in enumerate(members):
            info = zipfile.ZipInfo(name)
            info.compress_type = compression
            info.external_attr = 0o100600 << 16
            if force_zip64 and index == 0:
                with destination.open(info, mode="w", force_zip64=True) as handle:
                    handle.write(content)
            else:
                destination.writestr(info, content)
    return output_path


def _rewrite_database_member(
    *,
    backup_path: Path,
    tmp_path: Path,
    archive_path: str,
    mutate,
    schema_revision: str | None = None,
) -> Path:
    members = _read_backup_members(backup_path)
    member_map = dict(members)
    database_path = tmp_path / f"rewrite-{Path(archive_path).name}"
    database_path.write_bytes(member_map[archive_path])
    with sqlite3.connect(database_path) as connection:
        mutate(connection)
        connection.commit()
    member_map[archive_path] = database_path.read_bytes()
    manifest = json.loads(member_map["manifest.json"])
    if schema_revision is not None:
        manifest["schema_revisions"][
            "l1" if archive_path.endswith("l1_events.db") else "memory_shared"
        ] = schema_revision
    for record in manifest["files"]:
        if record["path"] == archive_path:
            content = member_map[archive_path]
            record["size_bytes"] = len(content)
            record["sha256"] = hashlib.sha256(content).hexdigest()
            break
    member_map["manifest.json"] = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    rewritten_members = [(name, member_map[name]) for name, _content in members]
    return _write_backup_members(tmp_path / "rewritten-db.magibackup", rewritten_members)


@pytest.mark.asyncio
async def test_preflight_rejects_per_file_record_count_tampering(tmp_path: Path) -> None:
    paths, backup_path, _manifest = await _build_backup(tmp_path)
    archive_target = paths.memory_dir / "archive"
    archive_target.mkdir(parents=True, exist_ok=True)
    tampered = _rewrite_manifest(
        backup_path,
        lambda payload: payload["files"][0].__setitem__(
            "record_count", payload["files"][0]["record_count"] + 1
        ),
    )

    with pytest.raises(MemoryPortabilityError) as error:
        inspect_memory_backup(
            source_path=tampered,
            password=None,
            runtime_paths=paths,
            archive_target=archive_target,
        )
    assert error.value.code == "backup_record_count_invalid"
    assert not any((paths.memory_portability_dir / "candidates").iterdir())

    tampered = _rewrite_manifest(
        backup_path,
        lambda payload: payload["counts"].__setitem__(
            "l0_attention_items", payload["counts"]["l0_attention_items"] + 1
        ),
    )
    with pytest.raises(MemoryPortabilityError) as error:
        inspect_memory_backup(
            source_path=tampered,
            password=None,
            runtime_paths=paths,
            archive_target=archive_target,
        )
    assert error.value.code == "backup_counts_invalid"


@pytest.mark.asyncio
async def test_preflight_reserves_space_for_database_migration_and_vacuum(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, backup_path, manifest = await _build_backup(tmp_path)
    archive_target = paths.memory_dir / "archive"
    archive_target.mkdir(parents=True, exist_ok=True)
    total_bytes = sum(record.size_bytes for record in manifest.files)
    largest_database = max(
        record.size_bytes for record in manifest.files if record.purpose in {"l1", "memory"}
    )
    expected_budget = (
        total_bytes
        + largest_database
        + max(
            total_bytes // 5,
            preflight_module.RESTORE_MIGRATION_MARGIN_BYTES,
        )
    )
    real_disk_usage = shutil.disk_usage
    calls: list[int] = []

    def constrained_disk_usage(directory: Path):
        usage = real_disk_usage(directory)
        calls.append(usage.free)
        if len(calls) == 1:
            return usage._replace(free=max(usage.free, expected_budget * 2))
        return usage._replace(free=expected_budget - 1)

    monkeypatch.setattr(
        "magi.memory.portability.backup.shutil.disk_usage",
        constrained_disk_usage,
    )
    with pytest.raises(MemoryPortabilityError) as error:
        inspect_memory_backup(
            source_path=backup_path,
            password=None,
            runtime_paths=paths,
            archive_target=archive_target,
        )
    assert error.value.code == "insufficient_space"
    assert len(calls) == 2
    assert not any((paths.memory_portability_dir / "candidates").iterdir())


@pytest.mark.asyncio
@pytest.mark.parametrize("revision", [None, "unknown_revision", "v999_future"])
async def test_preflight_returns_one_stable_error_for_unsupported_revisions(
    tmp_path: Path,
    revision: str | None,
) -> None:
    paths, backup_path, _manifest = await _build_backup(tmp_path)
    archive_target = paths.memory_dir / "archive"
    archive_target.mkdir(parents=True, exist_ok=True)

    def mutate(connection: sqlite3.Connection) -> None:
        connection.execute("DELETE FROM alembic_version")
        if revision is not None:
            connection.execute(
                "INSERT INTO alembic_version(version_num) VALUES (?)",
                (revision,),
            )

    rewritten = _rewrite_database_member(
        backup_path=backup_path,
        tmp_path=tmp_path,
        archive_path="databases/l1_events.db",
        mutate=mutate,
        schema_revision=revision,
    )
    with pytest.raises(MemoryPortabilityError) as error:
        inspect_memory_backup(
            source_path=rewritten,
            password=None,
            runtime_paths=paths,
            archive_target=archive_target,
        )
    assert error.value.code == "schema_revision_unsupported"
    assert revision is None or revision not in str(error.value)
    assert not any((paths.memory_portability_dir / "candidates").iterdir())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "statement",
    ["DROP INDEX idx_fact_events_timestamp", "DROP TABLE l1_events_fts"],
)
async def test_preflight_fails_closed_for_missing_schema_objects(
    tmp_path: Path,
    statement: str,
) -> None:
    paths, backup_path, _manifest = await _build_backup(tmp_path)
    archive_target = paths.memory_dir / "archive"
    archive_target.mkdir(parents=True, exist_ok=True)
    rewritten = _rewrite_database_member(
        backup_path=backup_path,
        tmp_path=tmp_path,
        archive_path="databases/l1_events.db",
        mutate=lambda connection: connection.execute(statement),
    )

    with pytest.raises(MemoryPortabilityError) as error:
        inspect_memory_backup(
            source_path=rewritten,
            password=None,
            runtime_paths=paths,
            archive_target=archive_target,
        )
    assert error.value.code == "database_schema_invalid"


@pytest.mark.asyncio
async def test_preflight_rejects_foreign_key_violations(tmp_path: Path) -> None:
    paths, backup_path, _manifest = await _build_backup(tmp_path)
    archive_target = paths.memory_dir / "archive"
    archive_target.mkdir(parents=True, exist_ok=True)

    def insert_orphan(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            INSERT INTO l1_source_facets(
                event_id, source, facet_name, text_value, created_at
            ) VALUES ('missing-event', 'manual_entry', 'orphan', 'invalid', 1)
            """
        )

    rewritten = _rewrite_database_member(
        backup_path=backup_path,
        tmp_path=tmp_path,
        archive_path="databases/l1_events.db",
        mutate=insert_orphan,
    )
    with pytest.raises(MemoryPortabilityError) as error:
        inspect_memory_backup(
            source_path=rewritten,
            password=None,
            runtime_paths=paths,
            archive_target=archive_target,
        )
    assert error.value.code == "database_invalid"


@pytest.mark.asyncio
async def test_preflight_requires_assets_to_exactly_match_database_references(
    tmp_path: Path,
) -> None:
    paths, backup_path, _manifest = await _build_backup(tmp_path)
    archive_target = paths.memory_dir / "archive"
    archive_target.mkdir(parents=True, exist_ok=True)
    members = _read_backup_members(backup_path)
    member_map = dict(members)
    manifest = json.loads(member_map["manifest.json"])
    removed_paths = {
        record["path"] for record in manifest["files"] if record["purpose"] == "manual_entry_asset"
    }
    assert removed_paths
    manifest["files"] = [
        record for record in manifest["files"] if record["path"] not in removed_paths
    ]
    member_map["manifest.json"] = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    rewritten = _write_backup_members(
        tmp_path / "missing-asset.magibackup",
        [(name, member_map[name]) for name, _content in members if name not in removed_paths],
    )

    with pytest.raises(MemoryPortabilityError) as error:
        inspect_memory_backup(
            source_path=rewritten,
            password=None,
            runtime_paths=paths,
            archive_target=archive_target,
        )
    assert error.value.code == "backup_assets_invalid"


@pytest.mark.asyncio
async def test_preflight_validates_archive_schema_and_per_file_row_count(tmp_path: Path) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    migrate_memory_databases(paths)
    seed_memory(paths)
    archive_dir = paths.memory_dir / "archive"
    archive_path = archive_dir / "2026-08-01.db"
    _create_archive_database(archive_path)
    snapshot = await create_memory_snapshot(
        runtime_paths=paths,
        archive_dir=archive_dir,
        unified_memory=FakeUnifiedMemory(),
        include_l0=True,
    )
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    try:
        backup_path, manifest = build_memory_backup(
            snapshot=snapshot,
            output_directory=output_dir,
            encryption="none",
            password=None,
        )
    finally:
        discard_snapshot(snapshot)
    archive_record = next(record for record in manifest.files if record.purpose == "archive")
    assert archive_record.record_count == 2

    inspection = inspect_memory_backup(
        source_path=backup_path,
        password=None,
        runtime_paths=paths,
        archive_target=archive_dir,
    )
    assert inspection.counts["archives"] == 1

    rewritten = _rewrite_database_member(
        backup_path=backup_path,
        tmp_path=tmp_path,
        archive_path="archives/2026-08-01.db",
        mutate=lambda connection: connection.execute("DROP INDEX idx_archived_l1_events_date"),
    )
    with pytest.raises(MemoryPortabilityError) as error:
        inspect_memory_backup(
            source_path=rewritten,
            password=None,
            runtime_paths=paths,
            archive_target=archive_dir,
        )
    assert error.value.code == "archive_schema_invalid"

    rewritten = _rewrite_database_member(
        backup_path=backup_path,
        tmp_path=tmp_path,
        archive_path="archives/2026-08-01.db",
        mutate=_replace_archive_l1_table_without_primary_key,
    )
    with pytest.raises(MemoryPortabilityError) as error:
        inspect_memory_backup(
            source_path=rewritten,
            password=None,
            runtime_paths=paths,
            archive_target=archive_dir,
        )
    assert error.value.code == "archive_schema_invalid"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "expected_code"),
    [
        ("path", "backup_member_invalid"),
        ("zip64", "backup_zip64_unsupported"),
        ("multidisk", "backup_archive_unsupported"),
        ("compression", "backup_archive_unsupported"),
    ],
)
async def test_preflight_rejects_unsafe_zip_features_before_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    expected_code: str,
) -> None:
    paths, backup_path, _manifest = await _build_backup(tmp_path)
    archive_target = paths.memory_dir / "archive"
    archive_target.mkdir(parents=True, exist_ok=True)
    members = _read_backup_members(backup_path)
    if kind == "path":
        members.append(("../escape", b"unsafe"))
        unsafe_path = _write_backup_members(tmp_path / "unsafe.magibackup", members)
    elif kind == "zip64":
        unsafe_path = _write_backup_members(
            tmp_path / "unsafe.magibackup",
            members,
            force_zip64=True,
        )
    elif kind == "multidisk":
        raw = bytearray(backup_path.read_bytes())
        end_offset = raw.rfind(b"PK\x05\x06")
        assert end_offset >= 0
        raw[end_offset + 4 : end_offset + 6] = (1).to_bytes(2, "little")
        unsafe_path = tmp_path / "unsafe.magibackup"
        unsafe_path.write_bytes(raw)
    else:
        unsafe_path = _write_backup_members(
            tmp_path / "unsafe.magibackup",
            members,
            compression=zipfile.ZIP_BZIP2,
        )
    if kind != "path":

        def forbidden_infolist(self):
            raise AssertionError("ZIP inventory must not run before raw directory validation")

        monkeypatch.setattr(zipfile.ZipFile, "infolist", forbidden_infolist)
    with pytest.raises(MemoryPortabilityError) as error:
        inspect_memory_backup(
            source_path=unsafe_path,
            password=None,
            runtime_paths=paths,
            archive_target=archive_target,
        )
    assert error.value.code == expected_code
    assert not (tmp_path / "escape").exists()


@pytest.mark.asyncio
async def test_encrypted_preflight_never_persists_password_or_source_path(
    tmp_path: Path,
) -> None:
    secret = "portable-password-secret"
    paths, backup_path, _manifest = await _build_backup(
        tmp_path,
        encryption="password",
        password=secret,
    )
    archive_target = paths.memory_dir / "archive"
    archive_target.mkdir(parents=True, exist_ok=True)

    with pytest.raises(MemoryPortabilityError) as missing:
        inspect_memory_backup(
            source_path=backup_path,
            password=None,
            runtime_paths=paths,
            archive_target=archive_target,
        )
    assert missing.value.code == "password_required"
    with pytest.raises(MemoryPortabilityError) as wrong:
        inspect_memory_backup(
            source_path=backup_path,
            password="wrong-password-secret",
            runtime_paths=paths,
            archive_target=archive_target,
        )
    assert wrong.value.code == "password_or_integrity_invalid"
    assert secret not in str(wrong.value)

    inspection = inspect_memory_backup(
        source_path=backup_path,
        password=secret,
        runtime_paths=paths,
        archive_target=archive_target,
    )
    candidate_root = paths.memory_portability_dir / "candidates" / str(inspection.candidate_id)
    serialized = (candidate_root / "candidate.json").read_text(encoding="utf-8")
    assert secret not in serialized
    assert "wrong-password-secret" not in serialized
    assert str(backup_path) not in serialized
    assert backup_path.name not in serialized
    assert not (candidate_root / "source.magibackup").exists()
    assert not (candidate_root / "payload.zip").exists()


def _build_old_revision_backup(tmp_path: Path) -> tuple[RuntimePaths, Path]:
    paths = RuntimePaths(tmp_path / "runtime")
    snapshot_root = tmp_path / "old-snapshot"
    database_dir = snapshot_root / "databases"
    database_dir.mkdir(parents=True)
    l1_path = database_dir / "l1_events.db"
    memory_path = database_dir / "memory.db"
    run_upgrade_database("l1", l1_path)
    run_upgrade_database(
        "memory_shared",
        memory_path,
        revision="v47_history_import_deletion_privacy",
    )
    counts = count_snapshot_records(l1_path, memory_path, [])
    counts["manual_entry_assets"] = 0
    snapshot = SnapshotBundle(
        root=snapshot_root,
        files=[
            SnapshotFile(
                source_path=l1_path,
                archive_path="databases/l1_events.db",
                purpose="l1",
            ),
            SnapshotFile(
                source_path=memory_path,
                archive_path="databases/memory.db",
                purpose="memory",
            ),
        ],
        schema_revisions={
            "l1": database_revision(l1_path),
            "memory_shared": database_revision(memory_path),
        },
        counts=counts,
    )
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    backup_path, _manifest = build_memory_backup(
        snapshot=snapshot,
        output_directory=output_dir,
        encryption="none",
        password=None,
    )
    return paths, backup_path


def test_staged_migration_runner_wraps_alembic_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for failure in (AssertionError("broken graph"), CommandError("broken command")):

        def fail_upgrade(_config, _revision, *, failure=failure):
            raise failure

        monkeypatch.setattr("magi.db.runner.command.upgrade", fail_upgrade)
        with pytest.raises(MigrationExecutionError):
            run_upgrade_database("l1", tmp_path / f"failed-{type(failure).__name__}.db")


@pytest.mark.asyncio
async def test_preflight_migrates_known_older_revision_in_private_staging(
    tmp_path: Path,
) -> None:
    paths, backup_path = _build_old_revision_backup(tmp_path)
    archive_target = paths.memory_dir / "archive"
    archive_target.mkdir(parents=True, exist_ok=True)

    inspection = inspect_memory_backup(
        source_path=backup_path,
        password=None,
        runtime_paths=paths,
        archive_target=archive_target,
    )
    assert inspection.compatibility == "upgrade_required"
    candidate_root, metadata, manifest = load_restore_candidate(
        runtime_paths=paths,
        candidate_id=str(inspection.candidate_id),
    )
    staged_memory = candidate_root / "payload" / "databases" / "memory.db"
    assert manifest.schema_revisions["memory_shared"] == "v47_history_import_deletion_privacy"
    assert database_revision(staged_memory) == migration_head("memory_shared")
    staged_record = next(
        record for record in metadata["staged_files"] if record["path"] == "databases/memory.db"
    )
    assert staged_record["sha256"] == hashlib.sha256(staged_memory.read_bytes()).hexdigest()


@pytest.mark.asyncio
async def test_preflight_exposes_stable_error_when_known_upgrade_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, backup_path = _build_old_revision_backup(tmp_path)
    archive_target = paths.memory_dir / "archive"
    archive_target.mkdir(parents=True, exist_ok=True)
    real_upgrade = run_upgrade_database

    def fail_candidate_upgrade(name: str, path: Path, *, revision: str = "head") -> None:
        if name == "memory_shared" and Path(path).name == "memory.db" and revision == "head":
            raise MigrationExecutionError("staged assertion failure")
        real_upgrade(name, path, revision=revision)

    monkeypatch.setattr(
        "magi.memory.portability.preflight.run_upgrade_database",
        fail_candidate_upgrade,
    )
    with pytest.raises(MemoryPortabilityError) as error:
        inspect_memory_backup(
            source_path=backup_path,
            password=None,
            runtime_paths=paths,
            archive_target=archive_target,
        )
    assert error.value.code == "schema_upgrade_failed"
    assert "assertion" not in str(error.value).lower()


def _seed_stale_search_indexes(paths: RuntimePaths) -> None:
    with sqlite3.connect(paths.l1_memory_db_path) as connection:
        _load_sqlite_vec(connection)
        connection.execute("UPDATE fact_events SET content = 'l1truth' WHERE event_id = 'event-1'")
        connection.execute(
            """
            INSERT INTO embedding_profiles(
                profile_id, provider_name, model_name, embedding_dim,
                text_builder_version, created_at
            ) VALUES ('profile-old', 'old-provider', 'old-model', 2, 'old-builder', 1)
            """
        )
        connection.execute(
            """
            INSERT INTO l1_event_embedding_state(
                event_id, embedding_status, embedding_profile_id,
                embedding_chunk_count, last_embedded_at, updated_at
            ) VALUES ('event-1', 3, 'profile-old', 1, 1, 1)
            """
        )
        connection.execute(
            """
            INSERT INTO l1_event_chunks(
                chunk_id, event_id, chunk_index, chunk_text, char_start,
                char_end, token_estimate, embedding_profile_id, created_at, updated_at
            ) VALUES ('l1-chunk-old', 'event-1', 0, 'stale chunk', 0, 11, 2,
                      'profile-old', 1, 1)
            """
        )
        connection.execute(
            "INSERT INTO l1_events_fts(event_id, content) VALUES ('ghost-l1', 'ghostterm')"
        )
        connection.commit()

    with sqlite3.connect(paths.memory_db_path) as connection:
        _load_sqlite_vec(connection)
        connection.execute(
            """
            INSERT INTO entity_catalog(
                entity_id, canonical_name, entity_type, embedding_status,
                embedding_profile_id, last_embedded_at, created_at, updated_at
            ) VALUES ('entity-1', 'Entity Truth', 'person', 'ready', 'old-profile', 1, 1, 1)
            """
        )
        connection.execute(
            """
            INSERT INTO knowledge_graph(
                triple_id, subject_id, subject_type, predicate, object_id, object_type,
                evidence_event_ids, first_observed_at, last_observed_at,
                embedding_status, embedding_profile_id, last_embedded_at,
                created_at, updated_at
            ) VALUES (
                'edge-1', 'entity-1', 'person', 'knows', 'entity-2', 'person',
                '["event-1"]', 1, 1, 'ready', 'old-profile', 1, 1, 1
            )
            """
        )
        connection.execute(
            """
            INSERT INTO episodes(
                episode_id, time_start, time_end, summary, label,
                embedding_status, embedding_profile_id, last_embedded_at,
                created_at, updated_at
            ) VALUES (
                'episode-1', 1, 2, 'episodetruth', 'episode label',
                'ready', 'old-profile', 1, 1, 1
            )
            """
        )
        connection.execute(
            """
            INSERT INTO summaries(
                summary_id, summary_type, summary_category, period_start, period_end,
                content, source_event_ids, source_event_count, embedding_status,
                embedding_profile_id, embedding_chunk_count, last_embedded_at,
                created_at, updated_at
            ) VALUES (
                'summary-1', 'daily', 'general', 1, 2, 'summarytruth', '["event-1"]',
                1, 'ready', 'old-profile', 1, 1, 1, 1
            )
            """
        )
        connection.execute(
            """
            INSERT INTO l3_summary_chunks(
                chunk_id, summary_id, chunk_index, chunk_text, char_start,
                char_end, token_estimate, created_at, updated_at
            ) VALUES ('l3-chunk-old', 'summary-1', 0, 'stale chunk', 0, 11, 2, 1, 1)
            """
        )
        connection.execute(
            """
            INSERT INTO procedural_skills(
                skill_id, skill_name, skill_category, skill_type,
                source_event_ids, embedding_status, embedding_profile_id,
                embedding_chunk_count, last_embedded_at, created_at, updated_at
            ) VALUES (
                'skill-1', 'skilltruth', 'general', 'procedure', '["event-1"]',
                'ready', 'old-profile', 1, 1, 1, 1
            )
            """
        )
        connection.execute(
            """
            INSERT INTO l4_skill_chunks(
                chunk_id, skill_id, chunk_index, chunk_text, char_start,
                char_end, token_estimate, created_at, updated_at
            ) VALUES ('l4-chunk-old', 'skill-1', 0, 'stale chunk', 0, 11, 2, 1, 1)
            """
        )
        connection.execute(
            "INSERT INTO episodes_fts(episode_id, summary) VALUES ('ghost-episode', 'ghostterm')"
        )
        connection.execute(
            "INSERT INTO l3_summaries_fts(summary_id, content) VALUES ('ghost-summary', 'ghostterm')"
        )
        connection.execute(
            "INSERT INTO l4_skills_fts(skill_id, content) VALUES ('ghost-skill', 'ghostterm')"
        )
        connection.execute(
            """
            CREATE TABLE l2_entity_vectors (
                vec_rowid INTEGER PRIMARY KEY,
                entity_id TEXT NOT NULL,
                embedding_model TEXT NOT NULL,
                embedding_dim INTEGER NOT NULL,
                vec_table TEXT NOT NULL,
                metadata TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(entity_id, embedding_model)
            )
            """
        )
        connection.execute(
            "CREATE INDEX idx_l2_entity_vectors_model ON l2_entity_vectors(embedding_model)"
        )
        connection.execute(
            """
            CREATE VIRTUAL TABLE "l2_entity_vec_aaaaaaaaaaaa"
            USING vec0(embedding float[2])
            """
        )
        connection.execute(
            """
            INSERT INTO l2_entity_vectors(
                vec_rowid, entity_id, embedding_model, embedding_dim,
                vec_table, metadata, created_at, updated_at
            ) VALUES (1, 'entity-1', 'old-model', 2,
                      'l2_entity_vec_aaaaaaaaaaaa', '{}', 1, 1)
            """
        )
        connection.execute(
            'INSERT INTO "l2_entity_vec_aaaaaaaaaaaa"(rowid, embedding) VALUES (?, ?)',
            (1, sqlite_vec.serialize_float32([0.1, 0.2])),
        )
        connection.commit()


@pytest.mark.asyncio
async def test_preflight_invalidates_vectors_and_rebuilds_all_fts_indexes(
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    migrate_memory_databases(paths)
    seed_memory(paths)
    _seed_stale_search_indexes(paths)
    snapshot = await create_memory_snapshot(
        runtime_paths=paths,
        archive_dir=paths.memory_dir / "archive",
        unified_memory=FakeUnifiedMemory(),
        include_l0=True,
    )
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    try:
        backup_path, manifest = build_memory_backup(
            snapshot=snapshot,
            output_directory=output_dir,
            encryption="none",
            password=None,
        )
    finally:
        discard_snapshot(snapshot)
    archive_target = paths.memory_dir / "archive"
    archive_target.mkdir(parents=True, exist_ok=True)

    inspection = inspect_memory_backup(
        source_path=backup_path,
        password=None,
        runtime_paths=paths,
        archive_target=archive_target,
    )
    candidate_root, metadata, _candidate_manifest = load_restore_candidate(
        runtime_paths=paths,
        candidate_id=str(inspection.candidate_id),
    )
    l1_path = candidate_root / "payload" / "databases" / "l1_events.db"
    memory_path = candidate_root / "payload" / "databases" / "memory.db"

    with sqlite3.connect(l1_path) as connection:
        assert connection.execute(
            """
            SELECT embedding_status, embedding_profile_id, embedding_chunk_count,
                   last_embedded_at
            FROM l1_event_embedding_state WHERE event_id = 'event-1'
            """
        ).fetchone() == (2, None, 0, None)
        assert connection.execute("SELECT COUNT(*) FROM l1_event_chunks").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM embedding_profiles").fetchone()[0] == 0
        assert connection.execute(
            "SELECT event_id FROM l1_events_fts WHERE l1_events_fts MATCH 'l1truth'"
        ).fetchall() == [("event-1",)]
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM l1_events_fts WHERE event_id = 'ghost-l1'"
            ).fetchone()[0]
            == 0
        )

    with sqlite3.connect(memory_path) as connection:
        _load_sqlite_vec(connection)
        assert connection.execute(
            "SELECT embedding_status, embedding_profile_id, last_embedded_at "
            "FROM entity_catalog WHERE entity_id = 'entity-1'"
        ).fetchone() == ("pending", None, None)
        assert connection.execute(
            "SELECT embedding_status, embedding_profile_id, last_embedded_at "
            "FROM knowledge_graph WHERE triple_id = 'edge-1'"
        ).fetchone() == ("pending", None, None)
        assert connection.execute(
            "SELECT embedding_status, embedding_profile_id, last_embedded_at "
            "FROM episodes WHERE episode_id = 'episode-1'"
        ).fetchone() == ("pending", None, None)
        assert connection.execute(
            "SELECT embedding_status, embedding_profile_id, embedding_chunk_count, "
            "last_embedded_at FROM summaries WHERE summary_id = 'summary-1'"
        ).fetchone() == ("pending", None, 0, None)
        assert connection.execute(
            "SELECT embedding_status, embedding_profile_id, embedding_chunk_count, "
            "last_embedded_at FROM procedural_skills WHERE skill_id = 'skill-1'"
        ).fetchone() == ("pending", None, 0, None)
        assert connection.execute("SELECT COUNT(*) FROM l3_summary_chunks").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM l4_skill_chunks").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM l2_entity_vectors").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'l2_entity_vec_aaaaaaaaaaaa'"
            ).fetchone()
            is None
        )
        assert connection.execute(
            "SELECT episode_id FROM episodes_fts WHERE episodes_fts MATCH 'episodetruth'"
        ).fetchall() == [("episode-1",)]
        assert connection.execute(
            "SELECT summary_id FROM l3_summaries_fts WHERE l3_summaries_fts MATCH 'summarytruth'"
        ).fetchall() == [("summary-1",)]
        assert connection.execute(
            "SELECT skill_id FROM l4_skills_fts WHERE l4_skills_fts MATCH 'skilltruth'"
        ).fetchall() == [("skill-1",)]
        assert connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM episodes_fts WHERE episode_id = 'ghost-episode'),
                (SELECT COUNT(*) FROM l3_summaries_fts WHERE summary_id = 'ghost-summary'),
                (SELECT COUNT(*) FROM l4_skills_fts WHERE skill_id = 'ghost-skill')
            """
        ).fetchone() == (0, 0, 0)

    original_by_path = {record.path: record for record in manifest.files}
    staged_by_path = {record["path"]: record for record in metadata["staged_files"]}
    assert (
        staged_by_path["databases/l1_events.db"]["sha256"]
        != original_by_path["databases/l1_events.db"].sha256
    )
    assert (
        staged_by_path["databases/memory.db"]["sha256"]
        != original_by_path["databases/memory.db"].sha256
    )
