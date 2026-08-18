"""Journaled replace-only cutover engine for validated memory restore candidates."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
import os
from pathlib import Path, PurePosixPath
import re
import stat
import threading
from typing import Literal

from ...utils.runtime import RuntimePaths
from .backup import build_memory_backup
from .errors import MemoryPortabilityError
from .fs_helpers import (
    SQLITE_SIDECAR_SUFFIXES,
    copy_private_file,
    create_private_directory,
    ensure_free_space,
    fingerprint_file,
    fsync_directory,
    fsync_tree,
    iter_private_tree_files,
    remove_owned_path,
    require_real_directory,
    require_regular_single_link,
    sqlite_backup_private,
    tree_fingerprint,
)
from .models import (
    MAX_BACKUP_FILE_COUNT,
    MAX_BACKUP_UNCOMPRESSED_BYTES,
    BackupManifest,
)
from .recovery import (
    FileFingerprint,
    RestoreJournal,
    TreeFingerprint,
    commit_restore_journal,
    create_restore_journal,
    read_restore_journal,
    register_active_memory_restore,
    rollback_restore_journal,
    update_restore_phase,
    write_restore_journal,
)
from .storage import create_memory_snapshot, discard_snapshot

RestorePurpose = Literal["l1", "memory", "archive", "manual_entry_asset"]
RestoreFailpoint = Callable[[str], None]

_ARCHIVE_DB_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}\.db$")
_ARCHIVE_OWNED_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}\.db(?:-wal|-shm|-journal)?$")
_ASSET_PATH = re.compile(r"^(?P<shard>[0-9a-f]{2})/(?P<digest>[0-9a-f]{64})\.(?:gif|jpg|png|webp)$")
_VALIDATED_FILE_KEYS = frozenset({"path", "purpose", "size_bytes", "sha256"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SPACE_MARGIN_BYTES = 32 * 1024 * 1024
_ENGINE_LOCK = threading.RLock()


@dataclass(frozen=True, slots=True)
class RestoreCandidateFile:
    """Post-inspection integrity anchor for one extracted candidate member."""

    path: str
    purpose: RestorePurpose
    size_bytes: int
    sha256: str

    @classmethod
    def from_mapping(cls, raw: object) -> "RestoreCandidateFile":
        if not isinstance(raw, Mapping) or not _VALIDATED_FILE_KEYS.issubset(raw):
            raise ValueError("invalid validated restore member")
        path = raw["path"]
        purpose = raw["purpose"]
        size_bytes = raw["size_bytes"]
        sha256 = raw["sha256"]
        if not isinstance(path, str) or not path or len(path) > 1024:
            raise ValueError("invalid restore member path")
        if purpose not in {"l1", "memory", "archive", "manual_entry_asset"}:
            raise ValueError("invalid restore member purpose")
        if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes < 0:
            raise ValueError("invalid restore member size")
        if not isinstance(sha256, str) or _SHA256.fullmatch(sha256) is None:
            raise ValueError("invalid restore member digest")
        return cls(
            path=path,
            purpose=purpose,
            size_bytes=size_bytes,
            sha256=sha256,
        )


@dataclass(frozen=True, slots=True)
class ValidatedRestoreCandidate:
    """Narrow adapter between restore preflight and the filesystem transaction."""

    candidate_root: Path
    payload_root: Path
    archive_target: Path
    manifest: BackupManifest
    files: tuple[RestoreCandidateFile, ...]

    @classmethod
    def from_preflight(
        cls,
        *,
        candidate_root: Path,
        metadata: Mapping[str, object],
        manifest: BackupManifest,
    ) -> "ValidatedRestoreCandidate":
        """Build the cutover input from preflight's persisted post-migration hashes."""

        staged_files = metadata.get("staged_files")
        archive_target = metadata.get("archive_target")
        if not isinstance(staged_files, list) or not isinstance(archive_target, str):
            raise MemoryPortabilityError(
                "candidate_integrity_missing",
                "The inspected restore candidate is missing its integrity anchors.",
            )
        try:
            files = tuple(RestoreCandidateFile.from_mapping(item) for item in staged_files)
        except ValueError as exc:
            raise MemoryPortabilityError(
                "candidate_integrity_invalid",
                "The inspected restore candidate has invalid integrity anchors.",
            ) from exc
        return cls(
            candidate_root=Path(candidate_root),
            payload_root=Path(candidate_root) / "payload",
            archive_target=Path(archive_target),
            manifest=manifest,
            files=files,
        )


class RestoreTransaction:
    """Prepared restore transaction whose cutover is externally lifecycle-managed."""

    def __init__(
        self,
        *,
        runtime_paths: RuntimePaths,
        journal: RestoreJournal,
        failpoint: RestoreFailpoint | None,
    ) -> None:
        self._runtime_paths = runtime_paths
        self._prepared_journal = journal
        self._failpoint = failpoint

    @property
    def transaction_id(self) -> str:
        return self._prepared_journal.transaction_id

    @property
    def safety_backup_path(self) -> Path:
        path = self._prepared_journal.safety_backup_path
        if path is None:
            raise RuntimeError("restore transaction has no safety backup")
        return Path(path)

    @contextmanager
    def activation_guard(self) -> Iterator[None]:
        """Keep same-process startup recovery from undoing runtime validation."""

        with register_active_memory_restore(self.transaction_id):
            yield

    def cutover(self) -> None:
        """Replace only the validated memory-owned files; never start runtime services."""

        with _ENGINE_LOCK:
            current = self._require_owned_journal(expected_phase="prepared")
            current.require_complete()
            try:
                self._verify_staged_artifacts(current)
                self._run_failpoint("before_cutover")
                current = update_restore_phase(
                    self._runtime_paths,
                    self.transaction_id,
                    "cutting_l1",
                )
                self._promote_database(current, role="l1")
                self._run_failpoint("after_l1_cutover")

                current = update_restore_phase(
                    self._runtime_paths,
                    self.transaction_id,
                    "cutting_memory",
                )
                self._promote_database(current, role="memory")
                self._run_failpoint("after_memory_cutover")

                current = update_restore_phase(
                    self._runtime_paths,
                    self.transaction_id,
                    "cutting_archives",
                )
                self._promote_archives(current)
                self._run_failpoint("after_archive_cutover")

                current = update_restore_phase(
                    self._runtime_paths,
                    self.transaction_id,
                    "cutting_assets",
                )
                self._promote_assets(current)
                self._run_failpoint("after_asset_cutover")

                update_restore_phase(
                    self._runtime_paths,
                    self.transaction_id,
                    "cutover_complete",
                )
                self._run_failpoint("after_cutover_complete")
            except Exception:
                try:
                    rollback_restore_journal(self._runtime_paths, self.transaction_id)
                except Exception as rollback_error:
                    raise MemoryPortabilityError(
                        "restore_rollback_failed",
                        "Memory restore failed and automatic rollback could not complete.",
                        status_code=500,
                    ) from rollback_error
                raise

    def rollback(self) -> None:
        """Restore the exact pre-cutover logical snapshot and remove transaction state."""

        with _ENGINE_LOCK:
            rollback_restore_journal(self._runtime_paths, self.transaction_id)

    def commit(self) -> None:
        """Commit after the caller validates runtime startup and persists rebuild work."""

        with _ENGINE_LOCK:
            commit_restore_journal(self._runtime_paths, self.transaction_id)

    def close(self) -> None:
        """Roll back an uncommitted transaction; committed transactions are already closed."""

        with _ENGINE_LOCK:
            current = read_restore_journal(self._runtime_paths)
            if current is None:
                return
            if current.transaction_id != self.transaction_id:
                raise MemoryPortabilityError(
                    "restore_transaction_changed",
                    "The durable restore transaction no longer matches this operation.",
                    status_code=409,
                )
            if current.phase == "committed":
                commit_restore_journal(self._runtime_paths, self.transaction_id)
            else:
                rollback_restore_journal(self._runtime_paths, self.transaction_id)

    def _require_owned_journal(self, *, expected_phase: str) -> RestoreJournal:
        current = read_restore_journal(self._runtime_paths)
        if (
            current is None
            or current.transaction_id != self.transaction_id
            or current.paths != self._prepared_journal.paths
            or current.phase != expected_phase
        ):
            raise MemoryPortabilityError(
                "restore_transaction_changed",
                "The durable restore transaction is not in the expected phase.",
                status_code=409,
            )
        return current

    def _verify_staged_artifacts(self, journal: RestoreJournal) -> None:
        paths = {key: Path(value) for key, value in journal.paths.items()}
        assert journal.staged_l1 is not None
        assert journal.staged_memory is not None
        assert journal.staged_archives is not None
        assert journal.staged_assets is not None
        _require_file_fingerprint(paths["db_stage"] / "l1_events.db", journal.staged_l1)
        _require_file_fingerprint(paths["db_stage"] / "memory.db", journal.staged_memory)
        _require_tree_fingerprint(
            paths["archive_stage"],
            journal.staged_archives,
            path_validator=_archive_relative_path_valid,
        )
        _require_tree_fingerprint(
            paths["asset_stage"],
            journal.staged_assets,
            path_validator=_asset_relative_path_valid,
        )

    def _promote_database(self, journal: RestoreJournal, *, role: Literal["l1", "memory"]) -> None:
        paths = {key: Path(value) for key, value in journal.paths.items()}
        name = "l1_events.db" if role == "l1" else "memory.db"
        live = paths["l1_db"] if role == "l1" else paths["memory_db"]
        staged = paths["db_stage"] / name
        discard = paths["db_discard"]
        for current in (live, *(Path(f"{live}{suffix}") for suffix in SQLITE_SIDECAR_SUFFIXES)):
            try:
                details = current.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISDIR(details.st_mode) and not stat.S_ISLNK(details.st_mode):
                raise MemoryPortabilityError(
                    "restore_target_invalid",
                    "A live memory database target conflicts with a directory.",
                    status_code=500,
                )
            os.replace(current, discard / current.name)
        self._run_failpoint(f"after_{role}_discard")
        os.replace(staged, live)
        if os.name != "nt":
            live.chmod(0o600)
        fsync_directory(discard)
        fsync_directory(live.parent)

    def _promote_archives(self, journal: RestoreJournal) -> None:
        paths = {key: Path(value) for key, value in journal.paths.items()}
        archive_dir = require_real_directory(paths["archive_dir"], label="memory archive directory")
        discard = paths["archive_discard"]
        for entry in sorted(archive_dir.iterdir(), key=lambda item: item.name):
            if _ARCHIVE_OWNED_NAME.fullmatch(entry.name) is None:
                continue
            details = entry.lstat()
            if stat.S_ISDIR(details.st_mode) and not stat.S_ISLNK(details.st_mode):
                raise MemoryPortabilityError(
                    "restore_target_invalid",
                    "A managed archive target conflicts with a directory.",
                    status_code=500,
                )
            os.replace(entry, discard / entry.name)
        self._run_failpoint("after_archive_discard")
        for staged, relative_path in iter_private_tree_files(paths["archive_stage"]):
            if not _archive_relative_path_valid(relative_path.as_posix()):
                raise MemoryPortabilityError(
                    "restore_staging_invalid",
                    "The staged archive set contains an unexpected path.",
                    status_code=500,
                )
            os.replace(staged, archive_dir / relative_path.name)
            if os.name != "nt":
                (archive_dir / relative_path.name).chmod(0o600)
        fsync_directory(discard)
        fsync_directory(archive_dir)

    def _promote_assets(self, journal: RestoreJournal) -> None:
        paths = {key: Path(value) for key, value in journal.paths.items()}
        live = paths["asset_dir"]
        discard = paths["asset_discard"] / "manual_entries"
        try:
            details = live.lstat()
        except FileNotFoundError:
            details = None
        if details is not None:
            if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
                raise MemoryPortabilityError(
                    "restore_target_invalid",
                    "The manual-entry asset target is not a real directory.",
                    status_code=500,
                )
            os.replace(live, discard)
        self._run_failpoint("after_asset_discard")
        os.replace(paths["asset_stage"], live)
        if os.name != "nt":
            live.chmod(0o700)
        fsync_directory(paths["asset_discard"])
        fsync_directory(live.parent)

    def _run_failpoint(self, name: str) -> None:
        if self._failpoint is not None:
            self._failpoint(name)


async def prepare_memory_restore(
    *,
    candidate: ValidatedRestoreCandidate,
    runtime_paths: RuntimePaths,
    failpoint: RestoreFailpoint | None = None,
) -> RestoreTransaction:
    """Prepare safety backup, exact rollback, same-filesystem staging, and journal.

    The caller must fully shut down the runtime before invoking this function.
    This function never initializes or shuts down runtime services itself.
    """

    with _ENGINE_LOCK:
        if read_restore_journal(runtime_paths) is not None:
            raise MemoryPortabilityError(
                "restore_transaction_pending",
                "Another memory restore transaction requires recovery.",
                status_code=409,
            )
        expected = await asyncio.to_thread(_verify_candidate, candidate)
        archive_target = require_real_directory(
            candidate.archive_target,
            label="configured memory archive directory",
        )
        asset_parent = _ensure_private_parent(runtime_paths.manual_entry_assets_dir.parent)
        _preflight_restore_space(
            candidate=candidate,
            expected=expected,
            runtime_paths=runtime_paths,
            archive_target=archive_target,
            asset_parent=asset_parent,
        )

        transaction_id = os.urandom(16).hex()
        paths = _transaction_paths(runtime_paths, archive_target, transaction_id)
        archive_details = archive_target.lstat()
        asset_existed = _asset_directory_exists(runtime_paths.manual_entry_assets_dir)
        initial = RestoreJournal(
            transaction_id=transaction_id,
            owner_pid=os.getpid(),
            phase="preparing",
            paths={key: str(value) for key, value in paths.items()},
            archive_device=int(archive_details.st_dev),
            archive_inode=int(archive_details.st_ino),
            asset_dir_existed=asset_existed,
        )
        create_restore_journal(runtime_paths, initial)

    try:
        _run_failpoint(failpoint, "after_journal_preparing")
        safety_backup_path = await _create_safety_backup(
            runtime_paths=runtime_paths,
            archive_target=archive_target,
            transaction_id=transaction_id,
        )
        preparing = replace(initial, safety_backup_path=str(safety_backup_path))
        write_restore_journal(runtime_paths, preparing)
        _run_failpoint(failpoint, "after_safety_backup")

        prepared = await asyncio.to_thread(
            _stage_restore_transaction,
            candidate,
            expected,
            runtime_paths,
            preparing,
        )
        _run_failpoint(failpoint, "after_restore_staging")
        write_restore_journal(runtime_paths, prepared)
        _run_failpoint(failpoint, "after_journal_prepared")
        return RestoreTransaction(
            runtime_paths=runtime_paths,
            journal=prepared,
            failpoint=failpoint,
        )
    except Exception:
        rollback_restore_journal(runtime_paths, transaction_id)
        raise


def _verify_candidate(
    candidate: ValidatedRestoreCandidate,
) -> dict[str, RestoreCandidateFile]:
    require_real_directory(candidate.candidate_root, label="restore candidate directory")
    payload_root = require_real_directory(candidate.payload_root, label="restore candidate payload")
    manifest_by_path = {record.path: record for record in candidate.manifest.files}
    expected_by_path = {record.path: record for record in candidate.files}
    if (
        not candidate.files
        or len(candidate.files) > MAX_BACKUP_FILE_COUNT
        or len(expected_by_path) != len(candidate.files)
        or set(expected_by_path) != set(manifest_by_path)
        or sum(record.size_bytes for record in candidate.files) > MAX_BACKUP_UNCOMPRESSED_BYTES
    ):
        raise MemoryPortabilityError(
            "candidate_integrity_invalid",
            "The inspected restore candidate has an invalid file inventory.",
        )
    for path, expected in expected_by_path.items():
        manifest_record = manifest_by_path[path]
        if expected.purpose != manifest_record.purpose or not _purpose_matches_path(expected):
            raise MemoryPortabilityError(
                "candidate_integrity_invalid",
                "The inspected restore candidate has an invalid file inventory.",
            )

    actual_paths: set[str] = set()
    for path, relative_path in iter_private_tree_files(payload_root):
        relative = relative_path.as_posix()
        actual_paths.add(relative)
        expected = expected_by_path.get(relative)
        if expected is None:
            raise MemoryPortabilityError(
                "candidate_changed",
                "The inspected restore candidate contains an unexpected file.",
            )
        size, digest = fingerprint_file(path)
        if size != expected.size_bytes or digest != expected.sha256:
            raise MemoryPortabilityError(
                "candidate_changed",
                "The inspected restore candidate changed after validation.",
            )
    if actual_paths != set(expected_by_path):
        raise MemoryPortabilityError(
            "candidate_changed",
            "The inspected restore candidate is missing a validated file.",
        )
    return expected_by_path


async def _create_safety_backup(
    *,
    runtime_paths: RuntimePaths,
    archive_target: Path,
    transaction_id: str,
) -> Path:
    snapshot = await create_memory_snapshot(
        runtime_paths=runtime_paths,
        archive_dir=archive_target,
        unified_memory=None,
        include_l0=False,
    )
    try:
        output_path, _manifest = await asyncio.to_thread(
            build_memory_backup,
            snapshot=snapshot,
            output_directory=runtime_paths.memory_backups_dir,
            encryption="none",
            password=None,
            filename_prefix=f"pre-restore-{transaction_id}",
        )
        details = require_regular_single_link(output_path, label="restore safety backup")
        if os.name != "nt" and stat.S_IMODE(details.st_mode) & 0o077:
            raise MemoryPortabilityError(
                "restore_safety_backup_invalid",
                "The pre-restore safety backup is not private.",
                status_code=500,
            )
        return output_path
    finally:
        discard_snapshot(snapshot)


def _stage_restore_transaction(
    candidate: ValidatedRestoreCandidate,
    expected: dict[str, RestoreCandidateFile],
    runtime_paths: RuntimePaths,
    journal: RestoreJournal,
) -> RestoreJournal:
    paths = {key: Path(value) for key, value in journal.paths.items()}
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
        create_private_directory(paths[key])

    rollback_l1 = FileFingerprint(
        *sqlite_backup_private(paths["l1_db"], paths["db_rollback"] / "l1_events.db")
    )
    rollback_memory = FileFingerprint(
        *sqlite_backup_private(paths["memory_db"], paths["db_rollback"] / "memory.db")
    )
    _snapshot_live_archives(paths["archive_dir"], paths["archive_rollback"])
    rollback_archives = TreeFingerprint(
        *tree_fingerprint(paths["archive_rollback"], path_validator=_archive_relative_path_valid)
    )
    if journal.asset_dir_existed:
        remove_owned_path(paths["asset_rollback"])
        from .fs_helpers import copy_private_tree

        copy_private_tree(paths["asset_dir"], paths["asset_rollback"])
    rollback_assets = TreeFingerprint(*tree_fingerprint(paths["asset_rollback"]))

    staged_l1 = _stage_candidate_file(
        candidate,
        expected["databases/l1_events.db"],
        paths["db_stage"] / "l1_events.db",
    )
    staged_memory = _stage_candidate_file(
        candidate,
        expected["databases/memory.db"],
        paths["db_stage"] / "memory.db",
    )
    for record in expected.values():
        if record.purpose == "archive":
            relative = PurePosixPath(record.path).name
            _stage_candidate_file(
                candidate,
                record,
                paths["archive_stage"] / relative,
            )
        elif record.purpose == "manual_entry_asset":
            relative = PurePosixPath(record.path).relative_to("assets/manual_entries")
            destination = paths["asset_stage"].joinpath(*relative.parts)
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if os.name != "nt":
                destination.parent.chmod(0o700)
            _stage_candidate_file(candidate, record, destination)

    fsync_tree(paths["db_stage"])
    fsync_tree(paths["db_rollback"])
    fsync_tree(paths["archive_stage"])
    fsync_tree(paths["archive_rollback"])
    fsync_tree(paths["asset_stage"])
    fsync_tree(paths["asset_rollback"])
    for parent in {
        paths["db_stage"].parent,
        paths["archive_stage"].parent,
        paths["asset_stage"].parent,
    }:
        fsync_directory(parent)
    staged_archives = TreeFingerprint(
        *tree_fingerprint(paths["archive_stage"], path_validator=_archive_relative_path_valid)
    )
    staged_assets = TreeFingerprint(
        *tree_fingerprint(paths["asset_stage"], path_validator=_asset_relative_path_valid)
    )
    return replace(
        journal,
        phase="prepared",
        staged_l1=staged_l1,
        staged_memory=staged_memory,
        staged_archives=staged_archives,
        staged_assets=staged_assets,
        rollback_l1=rollback_l1,
        rollback_memory=rollback_memory,
        rollback_archives=rollback_archives,
        rollback_assets=rollback_assets,
    )


def _stage_candidate_file(
    candidate: ValidatedRestoreCandidate,
    record: RestoreCandidateFile,
    destination: Path,
) -> FileFingerprint:
    source = candidate.payload_root.joinpath(*PurePosixPath(record.path).parts)
    size, digest = copy_private_file(
        source,
        destination,
        expected_size=record.size_bytes,
        expected_sha256=record.sha256,
    )
    return FileFingerprint(size_bytes=size, sha256=digest)


def _snapshot_live_archives(archive_dir: Path, rollback_dir: Path) -> None:
    for entry in sorted(archive_dir.iterdir(), key=lambda item: item.name):
        if _ARCHIVE_DB_NAME.fullmatch(entry.name) is None:
            continue
        require_regular_single_link(entry, label="memory archive database")
        sqlite_backup_private(entry, rollback_dir / entry.name)


def _preflight_restore_space(
    *,
    candidate: ValidatedRestoreCandidate,
    expected: dict[str, RestoreCandidateFile],
    runtime_paths: RuntimePaths,
    archive_target: Path,
    asset_parent: Path,
) -> None:
    live_db_bytes = _sqlite_family_bytes(runtime_paths.l1_memory_db_path) + _sqlite_family_bytes(
        runtime_paths.memory_db_path
    )
    live_archive_bytes = _managed_archive_bytes(archive_target)
    asset_dir = runtime_paths.manual_entry_assets_dir
    live_asset_bytes = 0
    if asset_dir.exists():
        _count, live_asset_bytes, _digest = tree_fingerprint(asset_dir)
    incoming_db_bytes = sum(
        record.size_bytes for record in expected.values() if record.purpose in {"l1", "memory"}
    )
    incoming_archive_bytes = sum(
        record.size_bytes for record in expected.values() if record.purpose == "archive"
    )
    incoming_asset_bytes = sum(
        record.size_bytes for record in expected.values() if record.purpose == "manual_entry_asset"
    )
    live_total = live_db_bytes + live_archive_bytes + live_asset_bytes
    ensure_free_space(
        (
            (
                runtime_paths.memory_portability_dir,
                (2 * live_total) + _SPACE_MARGIN_BYTES,
            ),
            (
                runtime_paths.memory_backups_dir,
                live_total + _SPACE_MARGIN_BYTES,
            ),
            (
                runtime_paths.memory_dir,
                (2 * live_db_bytes) + incoming_db_bytes + _SPACE_MARGIN_BYTES,
            ),
            (
                archive_target,
                max(
                    live_archive_bytes + incoming_archive_bytes,
                    2 * live_archive_bytes,
                )
                + _SPACE_MARGIN_BYTES,
            ),
            (
                asset_parent,
                max(
                    live_asset_bytes + incoming_asset_bytes,
                    2 * live_asset_bytes,
                )
                + _SPACE_MARGIN_BYTES,
            ),
        )
    )


def _transaction_paths(
    runtime_paths: RuntimePaths,
    archive_target: Path,
    transaction_id: str,
) -> dict[str, Path]:
    memory_root = Path(os.path.abspath(os.fspath(runtime_paths.memory_dir)))
    asset_parent = Path(os.path.abspath(os.fspath(runtime_paths.manual_entry_assets_dir.parent)))
    archive_target = Path(os.path.abspath(os.fspath(archive_target)))
    return {
        "l1_db": Path(os.path.abspath(os.fspath(runtime_paths.l1_memory_db_path))),
        "memory_db": Path(os.path.abspath(os.fspath(runtime_paths.memory_db_path))),
        "archive_dir": Path(os.path.abspath(os.fspath(archive_target))),
        "asset_dir": Path(os.path.abspath(os.fspath(runtime_paths.manual_entry_assets_dir))),
        "db_stage": memory_root / f".magi-memory-restore-{transaction_id}-db-stage",
        "db_rollback": memory_root / f".magi-memory-restore-{transaction_id}-db-rollback",
        "db_discard": memory_root / f".magi-memory-restore-{transaction_id}-db-discard",
        "archive_stage": archive_target / f".magi-memory-restore-{transaction_id}-archive-stage",
        "archive_rollback": archive_target
        / f".magi-memory-restore-{transaction_id}-archive-rollback",
        "archive_discard": archive_target
        / f".magi-memory-restore-{transaction_id}-archive-discard",
        "asset_stage": asset_parent / f".magi-memory-restore-{transaction_id}-assets-stage",
        "asset_rollback": asset_parent / f".magi-memory-restore-{transaction_id}-assets-rollback",
        "asset_discard": asset_parent / f".magi-memory-restore-{transaction_id}-assets-discard",
    }


def _purpose_matches_path(record: RestoreCandidateFile) -> bool:
    if record.purpose == "l1":
        return record.path == "databases/l1_events.db"
    if record.purpose == "memory":
        return record.path == "databases/memory.db"
    if record.purpose == "archive":
        return record.path.startswith("archives/") and _archive_relative_path_valid(
            record.path.removeprefix("archives/")
        )
    if record.purpose == "manual_entry_asset":
        if not record.path.startswith("assets/manual_entries/"):
            return False
        match = _ASSET_PATH.fullmatch(record.path.removeprefix("assets/manual_entries/"))
        return bool(
            match is not None
            and match.group("shard") == record.sha256[:2]
            and match.group("digest") == record.sha256
        )
    return False


def _archive_relative_path_valid(relative_path: str) -> bool:
    return "/" not in relative_path and _ARCHIVE_DB_NAME.fullmatch(relative_path) is not None


def _asset_relative_path_valid(relative_path: str) -> bool:
    return _ASSET_PATH.fullmatch(relative_path) is not None


def _require_file_fingerprint(path: Path, expected: FileFingerprint) -> None:
    size, digest = fingerprint_file(path)
    if size != expected.size_bytes or digest != expected.sha256:
        raise MemoryPortabilityError(
            "restore_staging_invalid",
            "A staged restore database failed its integrity check.",
            status_code=500,
        )


def _require_tree_fingerprint(
    path: Path,
    expected: TreeFingerprint,
    *,
    path_validator,
) -> None:
    actual = TreeFingerprint(*tree_fingerprint(path, path_validator=path_validator))
    if actual != expected:
        raise MemoryPortabilityError(
            "restore_staging_invalid",
            "A staged restore file tree failed its integrity check.",
            status_code=500,
        )


def _sqlite_family_bytes(path: Path) -> int:
    total = 0
    for candidate in (Path(path), *(Path(f"{path}{suffix}") for suffix in SQLITE_SIDECAR_SUFFIXES)):
        try:
            details = candidate.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
            raise MemoryPortabilityError(
                "restore_target_invalid",
                "A live memory database family contains an unsupported file.",
                status_code=500,
            )
        total += int(details.st_size)
    return total


def _managed_archive_bytes(archive_dir: Path) -> int:
    total = 0
    for entry in archive_dir.iterdir():
        if _ARCHIVE_OWNED_NAME.fullmatch(entry.name) is None:
            continue
        details = entry.lstat()
        if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
            raise MemoryPortabilityError(
                "restore_target_invalid",
                "The managed archive set contains an unsupported file.",
                status_code=500,
            )
        total += int(details.st_size)
    return total


def _ensure_private_parent(path: Path) -> Path:
    path = Path(os.path.abspath(os.fspath(path)))
    if not path.exists():
        path.mkdir(mode=0o700, parents=True, exist_ok=False)
        if os.name != "nt":
            path.chmod(0o700)
    return require_real_directory(path, label="manual-entry asset parent directory")


def _asset_directory_exists(path: Path) -> bool:
    try:
        details = Path(path).lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
        raise MemoryPortabilityError(
            "restore_target_invalid",
            "The manual-entry asset target is not a real directory.",
            status_code=500,
        )
    return True


def _run_failpoint(failpoint: RestoreFailpoint | None, name: str) -> None:
    if failpoint is not None:
        failpoint(name)


__all__ = [
    "RestoreCandidateFile",
    "RestoreTransaction",
    "ValidatedRestoreCandidate",
    "prepare_memory_restore",
]
