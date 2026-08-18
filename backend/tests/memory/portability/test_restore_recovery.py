from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import uuid

import pytest

from magi.db.runner import MIGRATION_TARGETS, run_upgrade_head
from magi.memory.portability import recovery as recovery_module
from magi.memory.portability import restore as restore_module
from magi.memory.portability.errors import MemoryPortabilityError
from magi.memory.portability.fs_helpers import fingerprint_file
from magi.memory.portability.models import (
    BACKUP_COUNT_KEYS,
    BACKUP_LIMITATIONS,
    BackupFileRecord,
    BackupManifest,
    utc_now_iso,
)
from magi.memory.portability.operations import MemoryPortabilityOperationStore
from magi.memory.portability.recovery import (
    clear_memory_portability_private_data,
    journal_path,
    read_restore_journal,
    recover_pending_memory_restore,
)
from magi.memory.portability.restore import (
    ValidatedRestoreCandidate,
    prepare_memory_restore,
)
from magi.memory.portability.storage import database_revision
from magi.utils.runtime import RuntimePaths


class SimulatedProcessCrash(BaseException):
    """Escape ordinary exception cleanup to model an abrupt process stop."""


@pytest.mark.asyncio
async def test_pre_restore_safety_backup_includes_persisted_l0(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = RuntimePaths(tmp_path / "runtime")
    archive_target = paths.memory_dir / "archive"
    archive_target.mkdir(parents=True, exist_ok=True)
    captured: dict[str, object] = {}
    snapshot = object()

    async def create_snapshot(**values: object) -> object:
        captured.update(values)
        return snapshot

    def build_backup(**values: object) -> tuple[Path, object]:
        assert values["snapshot"] is snapshot
        output = paths.memory_backups_dir / "pre-restore-test.magibackup"
        output.write_bytes(b"private safety backup")
        if os.name != "nt":
            output.chmod(0o600)
        return output, object()

    monkeypatch.setattr(restore_module, "create_memory_snapshot", create_snapshot)
    monkeypatch.setattr(restore_module, "build_memory_backup", build_backup)
    monkeypatch.setattr(restore_module, "discard_snapshot", lambda _snapshot: None)

    output = await restore_module._create_safety_backup(
        runtime_paths=paths,
        archive_target=archive_target,
        transaction_id="0" * 32,
    )

    assert output.is_file()
    assert captured["include_l0"] is True


@dataclass(frozen=True)
class _RestoreScenario:
    runtime_paths: RuntimePaths
    archive_target: Path
    candidate: ValidatedRestoreCandidate
    old_asset_path: Path
    old_orphan_asset_path: Path
    new_asset_path: Path


def _migrate_memory_databases(paths: RuntimePaths) -> None:
    selected = tuple(
        target for target in MIGRATION_TARGETS if target.name in {"l1", "memory_shared"}
    )
    run_upgrade_head(paths, targets=selected)


def _write_private(path: Path, content: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_bytes(content)
    if os.name != "nt":
        path.parent.chmod(0o700)
        path.chmod(0o600)


def _write_running_restore_operation(paths: RuntimePaths, operation_id: str) -> None:
    operations_dir = paths.memory_portability_dir / "operations"
    operations_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    (operations_dir / f"{operation_id}.json").write_text(
        json.dumps(
            {
                "owner_pid": 999999,
                "operation": {
                    "operation_id": operation_id,
                    "kind": "restore",
                    "status": "running",
                    "phase": "cutover",
                    "progress_percent": 55,
                    "record_counts": {"l1_events": 1},
                    "output_path": None,
                    "file_size_bytes": None,
                    "created_at": "2026-08-18T00:00:00Z",
                    "completed_at": None,
                    "error_code": None,
                    "error_message": None,
                    "rollback_performed": False,
                    "safety_backup_path": None,
                    "index_rebuild_status": None,
                    "inspection": None,
                },
            }
        ),
        encoding="utf-8",
    )


def _seed_memory(paths: RuntimePaths, *, marker: str, asset_bytes: bytes) -> Path:
    digest = hashlib.sha256(asset_bytes).hexdigest()
    asset_ref = f"manual-entry-asset://{digest}.png"
    asset_path = paths.manual_entry_assets_dir / digest[:2] / f"{digest}.png"
    _write_private(asset_path, asset_bytes)
    with sqlite3.connect(paths.l1_memory_db_path) as connection:
        connection.execute(
            """
            INSERT INTO fact_events(
                event_id, timestamp, created_at, event_type, source, memory_domain,
                content, author_type, content_type
            ) VALUES (?, 1, 1, 'manual_entry', 'manual_entry', 1, ?, 1, 1)
            """,
            (f"event-{marker}", marker),
        )
        connection.commit()
    with sqlite3.connect(paths.memory_db_path) as connection:
        connection.execute(
            """
            INSERT INTO manual_entries(
                entry_id, created_at, event_at, body, attachments_json
            ) VALUES (?, 1, 1, ?, ?)
            """,
            (f"entry-{marker}", marker, json.dumps([asset_ref])),
        )
        connection.commit()
    return asset_path


def _write_archive(path: Path, marker: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE marker(value TEXT NOT NULL)")
        connection.execute("INSERT INTO marker(value) VALUES (?)", (marker,))
        connection.commit()
    if os.name != "nt":
        path.chmod(0o600)


def _copy_private(source: Path, destination: Path) -> None:
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    if os.name != "nt":
        destination.parent.chmod(0o700)
        destination.chmod(0o600)


def _record(path: Path, archive_path: str, purpose: str) -> BackupFileRecord:
    size, digest = fingerprint_file(path)
    return BackupFileRecord(
        path=archive_path,
        purpose=purpose,
        size_bytes=size,
        record_count=1 if purpose != "archive" else 0,
        sha256=digest,
    )


def _create_scenario(tmp_path: Path) -> _RestoreScenario:
    runtime_paths = RuntimePaths(tmp_path / "live-runtime")
    _migrate_memory_databases(runtime_paths)
    old_asset_path = _seed_memory(
        runtime_paths,
        marker="old",
        asset_bytes=b"old-visible-manual-entry-asset",
    )
    old_orphan_bytes = b"old-unreferenced-manual-entry-asset"
    old_orphan_digest = hashlib.sha256(old_orphan_bytes).hexdigest()
    old_orphan_asset_path = (
        runtime_paths.manual_entry_assets_dir / old_orphan_digest[:2] / f"{old_orphan_digest}.png"
    )
    _write_private(old_orphan_asset_path, old_orphan_bytes)

    archive_target = tmp_path / "custom-archive-target"
    archive_target.mkdir(mode=0o700)
    old_archive = archive_target / "2026-01-01.db"
    _write_archive(old_archive, "old")
    (archive_target / "README.txt").write_text("unmanaged", encoding="utf-8")

    source_paths = RuntimePaths(tmp_path / "candidate-runtime")
    _migrate_memory_databases(source_paths)
    new_asset_source = _seed_memory(
        source_paths,
        marker="new",
        asset_bytes=b"new-visible-manual-entry-asset",
    )
    new_archive_source = tmp_path / "candidate-archive.db"
    _write_archive(new_archive_source, "new")

    candidate_id = str(uuid.uuid4())
    candidate_root = runtime_paths.memory_portability_dir / "candidates" / candidate_id
    payload_root = candidate_root / "payload"
    payload_root.mkdir(mode=0o700, parents=True)
    if os.name != "nt":
        candidate_root.parent.chmod(0o700)
        candidate_root.chmod(0o700)
        payload_root.chmod(0o700)

    l1_payload = payload_root / "databases" / "l1_events.db"
    memory_payload = payload_root / "databases" / "memory.db"
    archive_payload = payload_root / "archives" / "2026-02-02.db"
    new_asset_digest = hashlib.sha256(new_asset_source.read_bytes()).hexdigest()
    new_asset_relative = Path(new_asset_digest[:2]) / f"{new_asset_digest}.png"
    new_asset_payload = payload_root / "assets" / "manual_entries" / new_asset_relative
    _copy_private(source_paths.l1_memory_db_path, l1_payload)
    _copy_private(source_paths.memory_db_path, memory_payload)
    _copy_private(new_archive_source, archive_payload)
    _copy_private(new_asset_source, new_asset_payload)

    files = [
        _record(l1_payload, "databases/l1_events.db", "l1"),
        _record(memory_payload, "databases/memory.db", "memory"),
        _record(archive_payload, "archives/2026-02-02.db", "archive"),
        _record(
            new_asset_payload,
            f"assets/manual_entries/{new_asset_relative.as_posix()}",
            "manual_entry_asset",
        ),
    ]
    counts = {key: 0 for key in BACKUP_COUNT_KEYS}
    counts.update(
        {
            "l1_events": 1,
            "manual_entries": 1,
            "archives": 1,
            "manual_entry_assets": 1,
        }
    )
    manifest = BackupManifest(
        backup_id=str(uuid.uuid4()),
        created_at=utc_now_iso(),
        magi_version="test",
        encrypted=False,
        scope=["l0", "l1", "l2", "l3", "l4", "archives", "manual_entry_assets"],
        schema_revisions={
            "l1": database_revision(l1_payload),
            "memory_shared": database_revision(memory_payload),
        },
        limitations=list(BACKUP_LIMITATIONS),
        files=files,
        counts=counts,
    )
    candidate = ValidatedRestoreCandidate.from_preflight(
        candidate_root=candidate_root,
        metadata={
            "archive_target": str(archive_target),
            "staged_files": [record.model_dump(mode="json") for record in files],
        },
        manifest=manifest,
    )
    return _RestoreScenario(
        runtime_paths=runtime_paths,
        archive_target=archive_target,
        candidate=candidate,
        old_asset_path=old_asset_path,
        old_orphan_asset_path=old_orphan_asset_path,
        new_asset_path=(runtime_paths.manual_entry_assets_dir / new_asset_relative),
    )


def _database_marker(path: Path, table: str, column: str) -> str:
    with sqlite3.connect(path) as connection:
        row = connection.execute(f'SELECT "{column}" FROM "{table}"').fetchone()
    assert row is not None
    return str(row[0])


def _archive_marker(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        row = connection.execute("SELECT value FROM marker").fetchone()
    assert row is not None
    return str(row[0])


def _assert_old_state(scenario: _RestoreScenario) -> None:
    paths = scenario.runtime_paths
    assert _database_marker(paths.l1_memory_db_path, "fact_events", "content") == "old"
    assert _database_marker(paths.memory_db_path, "manual_entries", "body") == "old"
    assert _archive_marker(scenario.archive_target / "2026-01-01.db") == "old"
    assert not (scenario.archive_target / "2026-02-02.db").exists()
    assert (scenario.archive_target / "README.txt").read_text(encoding="utf-8") == "unmanaged"
    assert scenario.old_asset_path.read_bytes() == b"old-visible-manual-entry-asset"
    assert scenario.old_orphan_asset_path.read_bytes() == b"old-unreferenced-manual-entry-asset"
    assert not scenario.new_asset_path.exists()


def _assert_new_state(scenario: _RestoreScenario) -> None:
    paths = scenario.runtime_paths
    assert _database_marker(paths.l1_memory_db_path, "fact_events", "content") == "new"
    assert _database_marker(paths.memory_db_path, "manual_entries", "body") == "new"
    assert not (scenario.archive_target / "2026-01-01.db").exists()
    assert _archive_marker(scenario.archive_target / "2026-02-02.db") == "new"
    assert (scenario.archive_target / "README.txt").read_text(encoding="utf-8") == "unmanaged"
    assert not scenario.old_asset_path.exists()
    assert not scenario.old_orphan_asset_path.exists()
    assert scenario.new_asset_path.read_bytes() == b"new-visible-manual-entry-asset"


@pytest.mark.asyncio
async def test_cutover_replaces_only_owned_sets_clears_sidecars_and_commits(
    tmp_path: Path,
) -> None:
    scenario = _create_scenario(tmp_path)
    transaction = await prepare_memory_restore(
        candidate=scenario.candidate,
        runtime_paths=scenario.runtime_paths,
    )
    prepared = read_restore_journal(scenario.runtime_paths)
    assert prepared is not None
    assert prepared.phase == "prepared"
    assert Path(prepared.paths["archive_stage"]).parent == scenario.archive_target
    assert Path(prepared.paths["db_stage"]).parent == scenario.runtime_paths.memory_dir
    assert transaction.safety_backup_path.is_file()
    if os.name != "nt":
        assert stat.S_IMODE(transaction.safety_backup_path.stat().st_mode) == 0o600

    Path(f"{scenario.runtime_paths.l1_memory_db_path}-wal").write_bytes(b"old-sidecar")
    Path(f"{scenario.runtime_paths.memory_db_path}-shm").write_bytes(b"old-sidecar")
    (scenario.archive_target / "2026-01-01.db-journal").write_bytes(b"old-sidecar")
    transaction.cutover()
    _assert_new_state(scenario)
    assert not Path(f"{scenario.runtime_paths.l1_memory_db_path}-wal").exists()
    assert not Path(f"{scenario.runtime_paths.memory_db_path}-shm").exists()
    assert not (scenario.archive_target / "2026-01-01.db-journal").exists()
    if os.name != "nt":
        assert stat.S_IMODE(scenario.runtime_paths.l1_memory_db_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(scenario.runtime_paths.memory_db_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(scenario.new_asset_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(scenario.runtime_paths.manual_entry_assets_dir.stat().st_mode) == 0o700

    transaction.commit()
    committed = read_restore_journal(scenario.runtime_paths)
    assert committed is not None
    assert committed.phase == "committed"
    transaction.finalize_commit()
    assert journal_path(scenario.runtime_paths).exists() is False
    assert transaction.safety_backup_path.is_file()
    for key in (
        "db_stage",
        "db_rollback",
        "db_discard",
        "archive_stage",
        "archive_rollback",
        "archive_discard",
        "asset_stage",
        "asset_rollback",
        "asset_discard",
    ):
        assert not Path(prepared.paths[key]).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target_failpoint",
    [
        "before_cutover",
        "after_l1_discard",
        "after_l1_cutover",
        "after_memory_discard",
        "after_memory_cutover",
        "after_archive_discard",
        "after_archive_cutover",
        "after_asset_discard",
        "after_asset_cutover",
        "after_cutover_complete",
    ],
)
async def test_ordinary_cutover_failure_rolls_back_every_stage(
    tmp_path: Path,
    target_failpoint: str,
) -> None:
    scenario = _create_scenario(tmp_path)

    def failpoint(name: str) -> None:
        if name == target_failpoint:
            raise RuntimeError(f"failpoint:{name}")

    transaction = await prepare_memory_restore(
        candidate=scenario.candidate,
        runtime_paths=scenario.runtime_paths,
        failpoint=failpoint,
    )
    with pytest.raises(RuntimeError, match=f"failpoint:{target_failpoint}"):
        transaction.cutover()
    _assert_old_state(scenario)
    assert read_restore_journal(scenario.runtime_paths) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target_failpoint",
    [
        "before_cutover",
        "after_l1_discard",
        "after_l1_cutover",
        "after_memory_discard",
        "after_memory_cutover",
        "after_archive_discard",
        "after_archive_cutover",
        "after_asset_discard",
        "after_asset_cutover",
        "after_cutover_complete",
    ],
)
async def test_startup_recovers_a_process_stop_at_every_cutover_stage(
    tmp_path: Path,
    target_failpoint: str,
) -> None:
    scenario = _create_scenario(tmp_path)

    def failpoint(name: str) -> None:
        if name == target_failpoint:
            raise SimulatedProcessCrash(name)

    transaction = await prepare_memory_restore(
        candidate=scenario.candidate,
        runtime_paths=scenario.runtime_paths,
        failpoint=failpoint,
    )
    with pytest.raises(SimulatedProcessCrash):
        transaction.cutover()
    expected = "aborted" if target_failpoint == "before_cutover" else "rolled_back"
    assert recover_pending_memory_restore(scenario.runtime_paths) == expected
    _assert_old_state(scenario)
    assert recover_pending_memory_restore(scenario.runtime_paths) == "none"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target_failpoint",
    [
        "after_journal_preparing",
        "after_safety_backup",
        "after_restore_staging",
        "after_journal_prepared",
    ],
)
async def test_startup_aborts_a_process_stop_at_every_prepare_stage(
    tmp_path: Path,
    target_failpoint: str,
) -> None:
    scenario = _create_scenario(tmp_path)

    def failpoint(name: str) -> None:
        if name == target_failpoint:
            raise SimulatedProcessCrash(name)

    with pytest.raises(SimulatedProcessCrash):
        await prepare_memory_restore(
            candidate=scenario.candidate,
            runtime_paths=scenario.runtime_paths,
            failpoint=failpoint,
        )
    assert recover_pending_memory_restore(scenario.runtime_paths) == "aborted"
    _assert_old_state(scenario)
    assert recover_pending_memory_restore(scenario.runtime_paths) == "none"


@pytest.mark.asyncio
async def test_active_guard_skips_only_the_registered_same_process_transaction(
    tmp_path: Path,
) -> None:
    scenario = _create_scenario(tmp_path)
    transaction = await prepare_memory_restore(
        candidate=scenario.candidate,
        runtime_paths=scenario.runtime_paths,
    )
    transaction.cutover()
    with transaction.activation_guard():
        assert recover_pending_memory_restore(scenario.runtime_paths) == "active"
        _assert_new_state(scenario)
    assert recover_pending_memory_restore(scenario.runtime_paths) == "rolled_back"
    _assert_old_state(scenario)


@pytest.mark.asyncio
async def test_space_error_happens_before_journal_safety_backup_or_live_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _create_scenario(tmp_path)

    def insufficient_space(_requirements) -> None:
        raise MemoryPortabilityError(
            "insufficient_space",
            "There is not enough free space to stage this restore.",
        )

    monkeypatch.setattr(restore_module, "ensure_free_space", insufficient_space)
    with pytest.raises(MemoryPortabilityError) as failure:
        await prepare_memory_restore(
            candidate=scenario.candidate,
            runtime_paths=scenario.runtime_paths,
        )
    assert failure.value.code == "insufficient_space"
    _assert_old_state(scenario)
    assert read_restore_journal(scenario.runtime_paths) is None
    assert list(scenario.runtime_paths.memory_backups_dir.iterdir()) == []


@pytest.mark.asyncio
async def test_confirm_revalidates_staged_hash_and_rolls_back_without_mutation(
    tmp_path: Path,
) -> None:
    scenario = _create_scenario(tmp_path)
    transaction = await prepare_memory_restore(
        candidate=scenario.candidate,
        runtime_paths=scenario.runtime_paths,
    )
    prepared = read_restore_journal(scenario.runtime_paths)
    assert prepared is not None
    staged_l1 = Path(prepared.paths["db_stage"]) / "l1_events.db"
    with staged_l1.open("ab") as handle:
        handle.write(b"tampered")
    with pytest.raises(MemoryPortabilityError) as failure:
        transaction.cutover()
    assert failure.value.code == "restore_staging_invalid"
    _assert_old_state(scenario)
    assert read_restore_journal(scenario.runtime_paths) is None


@pytest.mark.asyncio
async def test_recovery_is_idempotent_after_an_interrupted_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _create_scenario(tmp_path)
    transaction = await prepare_memory_restore(
        candidate=scenario.candidate,
        runtime_paths=scenario.runtime_paths,
    )
    transaction.cutover()
    original_restore_archives = recovery_module._restore_archive_set
    calls = 0

    def fail_once(journal, paths) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("interrupted rollback")
        original_restore_archives(journal, paths)

    monkeypatch.setattr(recovery_module, "_restore_archive_set", fail_once)
    with pytest.raises(RuntimeError, match="interrupted rollback"):
        recover_pending_memory_restore(scenario.runtime_paths)
    assert read_restore_journal(scenario.runtime_paths) is not None
    assert recover_pending_memory_restore(scenario.runtime_paths) == "rolled_back"
    _assert_old_state(scenario)
    assert recover_pending_memory_restore(scenario.runtime_paths) == "none"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["commit", "rollback"])
async def test_transaction_cleanup_can_be_retried_after_durable_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    scenario = _create_scenario(tmp_path)
    transaction = await prepare_memory_restore(
        candidate=scenario.candidate,
        runtime_paths=scenario.runtime_paths,
    )
    transaction.cutover()
    original_cleanup = recovery_module._cleanup_transaction_artifacts
    calls = 0

    def fail_once(journal) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("interrupted cleanup")
        original_cleanup(journal)

    monkeypatch.setattr(recovery_module, "_cleanup_transaction_artifacts", fail_once)
    if operation == "commit":
        transaction.commit()
        transaction.finalize_commit()
    else:
        with pytest.raises(RuntimeError, match="interrupted cleanup"):
            getattr(transaction, operation)()
    durable = read_restore_journal(scenario.runtime_paths)
    assert durable is not None
    assert durable.phase == ("committed" if operation == "commit" else "rolled_back")

    if operation == "commit":
        transaction.finalize_commit()
    else:
        transaction.rollback()
    assert read_restore_journal(scenario.runtime_paths) is None
    if operation == "commit":
        _assert_new_state(scenario)
    else:
        _assert_old_state(scenario)


@pytest.mark.asyncio
async def test_startup_allows_committed_restore_when_cleanup_is_still_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _create_scenario(tmp_path)
    transaction = await prepare_memory_restore(
        candidate=scenario.candidate,
        runtime_paths=scenario.runtime_paths,
    )
    transaction.cutover()

    def fail_cleanup(_journal) -> None:
        raise PermissionError("cleanup blocked")

    monkeypatch.setattr(recovery_module, "_cleanup_transaction_artifacts", fail_cleanup)
    transaction.commit()

    durable = read_restore_journal(scenario.runtime_paths)
    assert durable is not None
    assert durable.phase == "committed"
    assert recover_pending_memory_restore(scenario.runtime_paths) == "committed"
    assert read_restore_journal(scenario.runtime_paths) is not None
    _assert_new_state(scenario)


@pytest.mark.asyncio
async def test_startup_marks_restore_succeeded_after_crash_between_commit_and_job_write(
    tmp_path: Path,
) -> None:
    scenario = _create_scenario(tmp_path)
    operation_id = str(uuid.uuid4())
    _write_running_restore_operation(scenario.runtime_paths, operation_id)
    transaction = await prepare_memory_restore(
        candidate=scenario.candidate,
        runtime_paths=scenario.runtime_paths,
        operation_id=operation_id,
    )
    transaction.cutover()
    transaction.commit()

    assert recover_pending_memory_restore(scenario.runtime_paths) == "committed"
    recovered = MemoryPortabilityOperationStore(runtime_paths=scenario.runtime_paths).get(
        operation_id
    )
    assert recovered is not None
    assert recovered.status == "succeeded"
    assert recovered.error_code is None
    assert recovered.index_rebuild_status == "pending"
    _assert_new_state(scenario)


@pytest.mark.asyncio
async def test_startup_marks_interrupted_restore_as_rolled_back(
    tmp_path: Path,
) -> None:
    scenario = _create_scenario(tmp_path)
    operation_id = str(uuid.uuid4())
    _write_running_restore_operation(scenario.runtime_paths, operation_id)
    transaction = await prepare_memory_restore(
        candidate=scenario.candidate,
        runtime_paths=scenario.runtime_paths,
        operation_id=operation_id,
    )
    transaction.cutover()

    assert recover_pending_memory_restore(scenario.runtime_paths) == "rolled_back"
    recovered = MemoryPortabilityOperationStore(runtime_paths=scenario.runtime_paths).get(
        operation_id
    )
    assert recovered is not None
    assert recovered.status == "failed"
    assert recovered.error_code == "operation_interrupted"
    assert recovered.rollback_performed is True
    _assert_old_state(scenario)


@pytest.mark.asyncio
async def test_private_clear_refuses_active_restore_then_removes_owned_artifacts(
    tmp_path: Path,
) -> None:
    scenario = _create_scenario(tmp_path)
    operations = scenario.runtime_paths.memory_portability_dir / "operations"
    operations.mkdir(mode=0o700)
    (operations / "state.json").write_text("{}", encoding="utf-8")
    snapshot = scenario.runtime_paths.memory_portability_dir / "snapshot-abcd1234"
    snapshot.mkdir(mode=0o700)
    unrelated_backup = scenario.runtime_paths.memory_backups_dir / "keep.magibackup"
    unrelated_backup.write_bytes(b"keep")

    transaction = await prepare_memory_restore(
        candidate=scenario.candidate,
        runtime_paths=scenario.runtime_paths,
    )
    with pytest.raises(MemoryPortabilityError) as active_failure:
        clear_memory_portability_private_data(scenario.runtime_paths)
    assert active_failure.value.code == "restore_transaction_pending"
    safety_backup = transaction.safety_backup_path
    transaction.rollback()

    counts = clear_memory_portability_private_data(scenario.runtime_paths)
    assert counts == {
        "candidates": 1,
        "snapshots": 1,
        "operations": 1,
        "safety_backups": 1,
    }
    assert safety_backup.exists() is False
    assert unrelated_backup.read_bytes() == b"keep"
    assert list((scenario.runtime_paths.memory_portability_dir / "candidates").iterdir()) == []
    assert list((scenario.runtime_paths.memory_portability_dir / "operations").iterdir()) == []


def test_preflight_adapter_accepts_only_the_staged_files_contract(tmp_path: Path) -> None:
    scenario = _create_scenario(tmp_path)
    with pytest.raises(MemoryPortabilityError) as failure:
        ValidatedRestoreCandidate.from_preflight(
            candidate_root=scenario.candidate.candidate_root,
            metadata={
                "archive_target": str(scenario.archive_target),
                "validated_files": [
                    record.model_dump(mode="json") for record in scenario.candidate.manifest.files
                ],
            },
            manifest=scenario.candidate.manifest,
        )
    assert failure.value.code == "candidate_integrity_missing"
