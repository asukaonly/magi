"""Durable journal and startup recovery for memory restore cutovers."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import re
import stat
import threading
from typing import Iterator, Mapping
import uuid

from ...bootstrap.context import RuntimeBootstrapContext
from ...bootstrap.lifecycle import LifecycleModule
from ...core.logger import get_logger
from ...utils.runtime import RuntimePaths
from .errors import MemoryPortabilityError
from .fs_helpers import (
    copy_private_file,
    copy_private_tree,
    fingerprint_file,
    fsync_directory,
    open_private_exclusive,
    remove_owned_path,
    remove_sqlite_family,
    require_real_directory,
    tree_fingerprint,
)

logger = get_logger(__name__)

RESTORE_JOURNAL_FORMAT = "magi-memory-restore-journal"
RESTORE_JOURNAL_VERSION = 1
RESTORE_JOURNAL_NAME = "memory-restore.pending.json"
MAX_RESTORE_JOURNAL_BYTES = 1024 * 1024

_PHASES = frozenset(
    {
        "preparing",
        "prepared",
        "cutting_l1",
        "cutting_memory",
        "cutting_archives",
        "cutting_assets",
        "cutover_complete",
        "rolling_back",
        "rolled_back",
        "committed",
    }
)
_ARCHIVE_DB_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}\.db$")
_ARCHIVE_OWNED_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}\.db(?:-wal|-shm|-journal)?$")
_TRANSACTION_ID = re.compile(r"^[0-9a-f]{32}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TEMP_JOURNAL = re.compile(
    r"^\.memory-restore-journal-(?P<transaction>[0-9a-f]{32})-" r"(?P<nonce>[0-9a-f]{32})\.tmp$"
)
_ORPHAN_DIR = re.compile(
    r"^\.magi-memory-restore-[0-9a-f]{32}-"
    r"(?:db|archive|assets)-(?:stage|rollback|discard|restore)$"
)
_SNAPSHOT_DIR = re.compile(r"^snapshot-[a-z0-9_]{8}$")
_SAFETY_BACKUP = re.compile(r"^pre-restore-[0-9a-f]{32}-\d{8}T\d{6}Z-[0-9a-f]{32}\.magibackup$")
_SAFETY_BACKUP_PARTIAL = re.compile(
    r"^\.pre-restore-[0-9a-f]{32}-\d{8}T\d{6}Z-" r"[0-9a-f]{32}\.magibackup\.partial$"
)
_PATH_KEYS = frozenset(
    {
        "l1_db",
        "memory_db",
        "archive_dir",
        "asset_dir",
        "db_stage",
        "db_rollback",
        "db_discard",
        "archive_stage",
        "archive_rollback",
        "archive_discard",
        "asset_stage",
        "asset_rollback",
        "asset_discard",
    }
)
_FILE_FINGERPRINT_KEYS = frozenset({"size_bytes", "sha256"})
_TREE_FINGERPRINT_KEYS = frozenset({"file_count", "total_bytes", "sha256"})
_JOURNAL_KEYS = frozenset(
    {
        "format",
        "version",
        "transaction_id",
        "owner_pid",
        "phase",
        "paths",
        "archive_device",
        "archive_inode",
        "asset_dir_existed",
        "safety_backup_path",
        "staged_l1",
        "staged_memory",
        "staged_archives",
        "staged_assets",
        "rollback_l1",
        "rollback_memory",
        "rollback_archives",
        "rollback_assets",
    }
)

_JOURNAL_LOCK = threading.RLock()
_ACTIVE_LOCK = threading.RLock()
_ACTIVE_TRANSACTIONS: dict[str, int] = {}


@dataclass(frozen=True, slots=True)
class FileFingerprint:
    """Content-free integrity fields for one staged regular file."""

    size_bytes: int
    sha256: str

    @classmethod
    def from_mapping(cls, raw: object) -> "FileFingerprint":
        if not isinstance(raw, Mapping) or set(raw) != _FILE_FINGERPRINT_KEYS:
            raise ValueError("invalid file fingerprint")
        size = raw["size_bytes"]
        digest = raw["sha256"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ValueError("invalid file size")
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise ValueError("invalid file digest")
        return cls(size_bytes=size, sha256=digest)

    def to_dict(self) -> dict[str, object]:
        return {"size_bytes": self.size_bytes, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class TreeFingerprint:
    """Aggregate integrity fields for one staged regular-file tree."""

    file_count: int
    total_bytes: int
    sha256: str

    @classmethod
    def from_mapping(cls, raw: object) -> "TreeFingerprint":
        if not isinstance(raw, Mapping) or set(raw) != _TREE_FINGERPRINT_KEYS:
            raise ValueError("invalid tree fingerprint")
        count = raw["file_count"]
        total = raw["total_bytes"]
        digest = raw["sha256"]
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
            or isinstance(total, bool)
            or not isinstance(total, int)
            or total < 0
        ):
            raise ValueError("invalid tree size")
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise ValueError("invalid tree digest")
        return cls(file_count=count, total_bytes=total, sha256=digest)

    def to_dict(self) -> dict[str, object]:
        return {
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class RestoreJournal:
    """Strict content-free state needed to finish or roll back one cutover."""

    transaction_id: str
    owner_pid: int
    phase: str
    paths: dict[str, str]
    archive_device: int
    archive_inode: int
    asset_dir_existed: bool
    safety_backup_path: str | None = None
    staged_l1: FileFingerprint | None = None
    staged_memory: FileFingerprint | None = None
    staged_archives: TreeFingerprint | None = None
    staged_assets: TreeFingerprint | None = None
    rollback_l1: FileFingerprint | None = None
    rollback_memory: FileFingerprint | None = None
    rollback_archives: TreeFingerprint | None = None
    rollback_assets: TreeFingerprint | None = None

    @classmethod
    def from_mapping(cls, raw: object) -> "RestoreJournal":
        if not isinstance(raw, Mapping) or set(raw) != _JOURNAL_KEYS:
            raise ValueError("invalid restore journal fields")
        version = raw["version"]
        if (
            raw["format"] != RESTORE_JOURNAL_FORMAT
            or isinstance(version, bool)
            or not isinstance(version, int)
            or version != RESTORE_JOURNAL_VERSION
        ):
            raise ValueError("unsupported restore journal")
        transaction_id = raw["transaction_id"]
        owner_pid = raw["owner_pid"]
        phase = raw["phase"]
        paths = raw["paths"]
        archive_device = raw["archive_device"]
        archive_inode = raw["archive_inode"]
        asset_dir_existed = raw["asset_dir_existed"]
        safety_backup_path = raw["safety_backup_path"]
        if not isinstance(transaction_id, str) or _TRANSACTION_ID.fullmatch(transaction_id) is None:
            raise ValueError("invalid restore transaction identifier")
        if isinstance(owner_pid, bool) or not isinstance(owner_pid, int) or owner_pid <= 0:
            raise ValueError("invalid restore owner process")
        if not isinstance(phase, str) or phase not in _PHASES:
            raise ValueError("invalid restore phase")
        if not isinstance(paths, Mapping) or set(paths) != _PATH_KEYS:
            raise ValueError("invalid restore paths")
        normalized_paths: dict[str, str] = {}
        for key, value in paths.items():
            if not isinstance(value, str) or not value or len(value) > 4096:
                raise ValueError("invalid restore path")
            candidate = Path(value)
            if not candidate.is_absolute() or "\x00" in value:
                raise ValueError("invalid restore path")
            normalized_paths[str(key)] = value
        if (
            isinstance(archive_device, bool)
            or not isinstance(archive_device, int)
            or archive_device < 0
            or isinstance(archive_inode, bool)
            or not isinstance(archive_inode, int)
            or archive_inode < 0
            or not isinstance(asset_dir_existed, bool)
        ):
            raise ValueError("invalid restore target identity")
        if safety_backup_path is not None and (
            not isinstance(safety_backup_path, str)
            or not Path(safety_backup_path).is_absolute()
            or len(safety_backup_path) > 4096
            or "\x00" in safety_backup_path
        ):
            raise ValueError("invalid safety backup path")

        def optional_file(key: str) -> FileFingerprint | None:
            value = raw[key]
            return None if value is None else FileFingerprint.from_mapping(value)

        def optional_tree(key: str) -> TreeFingerprint | None:
            value = raw[key]
            return None if value is None else TreeFingerprint.from_mapping(value)

        journal = cls(
            transaction_id=transaction_id,
            owner_pid=owner_pid,
            phase=phase,
            paths=normalized_paths,
            archive_device=archive_device,
            archive_inode=archive_inode,
            asset_dir_existed=asset_dir_existed,
            safety_backup_path=safety_backup_path,
            staged_l1=optional_file("staged_l1"),
            staged_memory=optional_file("staged_memory"),
            staged_archives=optional_tree("staged_archives"),
            staged_assets=optional_tree("staged_assets"),
            rollback_l1=optional_file("rollback_l1"),
            rollback_memory=optional_file("rollback_memory"),
            rollback_archives=optional_tree("rollback_archives"),
            rollback_assets=optional_tree("rollback_assets"),
        )
        if journal.phase != "preparing":
            journal.require_complete()
        return journal

    def require_complete(self) -> None:
        fields = (
            self.safety_backup_path,
            self.staged_l1,
            self.staged_memory,
            self.staged_archives,
            self.staged_assets,
            self.rollback_l1,
            self.rollback_memory,
            self.rollback_archives,
            self.rollback_assets,
        )
        if any(value is None for value in fields):
            raise ValueError("restore journal is incomplete")

    def to_dict(self) -> dict[str, object]:
        def file_value(value: FileFingerprint | None) -> object:
            return None if value is None else value.to_dict()

        def tree_value(value: TreeFingerprint | None) -> object:
            return None if value is None else value.to_dict()

        return {
            "format": RESTORE_JOURNAL_FORMAT,
            "version": RESTORE_JOURNAL_VERSION,
            "transaction_id": self.transaction_id,
            "owner_pid": self.owner_pid,
            "phase": self.phase,
            "paths": dict(self.paths),
            "archive_device": self.archive_device,
            "archive_inode": self.archive_inode,
            "asset_dir_existed": self.asset_dir_existed,
            "safety_backup_path": self.safety_backup_path,
            "staged_l1": file_value(self.staged_l1),
            "staged_memory": file_value(self.staged_memory),
            "staged_archives": tree_value(self.staged_archives),
            "staged_assets": tree_value(self.staged_assets),
            "rollback_l1": file_value(self.rollback_l1),
            "rollback_memory": file_value(self.rollback_memory),
            "rollback_archives": tree_value(self.rollback_archives),
            "rollback_assets": tree_value(self.rollback_assets),
        }


def journal_path(runtime_paths: RuntimePaths) -> Path:
    """Return the singleton restore journal path for one runtime root."""

    return runtime_paths.memory_portability_dir / RESTORE_JOURNAL_NAME


def create_restore_journal(runtime_paths: RuntimePaths, journal: RestoreJournal) -> None:
    """Create the first durable journal record with an exclusive singleton claim."""

    with _JOURNAL_LOCK:
        directory = require_real_directory(
            runtime_paths.memory_portability_dir,
            label="memory portability directory",
        )
        target = journal_path(runtime_paths)
        temporary = _write_journal_temporary(directory, journal)
        placeholder_fd = -1
        claimed = False
        installed = False
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            placeholder_fd = os.open(target, flags, 0o600)
            claimed = True
            os.fsync(placeholder_fd)
            os.close(placeholder_fd)
            placeholder_fd = -1
            os.replace(temporary, target)
            installed = True
            fsync_directory(directory)
        except FileExistsError as exc:
            temporary.unlink(missing_ok=True)
            raise MemoryPortabilityError(
                "restore_transaction_pending",
                "Another memory restore transaction requires recovery.",
                status_code=409,
            ) from exc
        except BaseException:
            temporary.unlink(missing_ok=True)
            if claimed and not installed:
                target.unlink(missing_ok=True)
                fsync_directory(directory)
            raise
        finally:
            if placeholder_fd >= 0:
                os.close(placeholder_fd)


def write_restore_journal(runtime_paths: RuntimePaths, journal: RestoreJournal) -> None:
    """Atomically replace and synchronize one existing restore journal."""

    with _JOURNAL_LOCK:
        target = journal_path(runtime_paths)
        current = read_restore_journal(runtime_paths)
        if current is None or current.transaction_id != journal.transaction_id:
            raise MemoryPortabilityError(
                "restore_transaction_changed",
                "The durable restore transaction no longer matches this operation.",
                status_code=409,
            )
        temporary = _write_journal_temporary(target.parent, journal)
        try:
            os.replace(temporary, target)
            fsync_directory(target.parent)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise


def read_restore_journal(runtime_paths: RuntimePaths) -> RestoreJournal | None:
    """Read the singleton journal, adopting one fully written initial temp if needed."""

    with _JOURNAL_LOCK:
        directory = require_real_directory(
            runtime_paths.memory_portability_dir,
            label="memory portability directory",
        )
        target = journal_path(runtime_paths)
        temporaries = _journal_temporaries(directory)
        try:
            details = target.lstat()
        except FileNotFoundError:
            if not temporaries:
                return None
            if len(temporaries) != 1:
                raise _journal_invalid("Multiple restore journal candidates were found.")
            journal = _read_journal_file(temporaries[0])
            os.replace(temporaries[0], target)
            fsync_directory(directory)
            return journal
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1
            or (os.name != "nt" and stat.S_IMODE(details.st_mode) & 0o077)
        ):
            raise _journal_invalid("The restore journal is not a private regular file.")
        if details.st_size == 0:
            if len(temporaries) != 1:
                raise _journal_invalid("The restore journal claim is incomplete.")
            journal = _read_journal_file(temporaries[0])
            os.replace(temporaries[0], target)
            fsync_directory(directory)
            return journal
        journal = _read_journal_file(target)
        for temporary in temporaries:
            temporary.unlink(missing_ok=True)
        if temporaries:
            fsync_directory(directory)
        return journal


def delete_restore_journal(runtime_paths: RuntimePaths, transaction_id: str) -> None:
    """Delete the journal only when it still belongs to the expected transaction."""

    with _JOURNAL_LOCK:
        current = read_restore_journal(runtime_paths)
        if current is None:
            return
        if current.transaction_id != transaction_id:
            raise MemoryPortabilityError(
                "restore_transaction_changed",
                "The durable restore transaction no longer matches this operation.",
                status_code=409,
            )
        journal_path(runtime_paths).unlink()
        fsync_directory(runtime_paths.memory_portability_dir)


@contextmanager
def register_active_memory_restore(transaction_id: str) -> Iterator[None]:
    """Mark one same-process cutover active while the new runtime is validated."""

    normalized = str(transaction_id or "")
    if _TRANSACTION_ID.fullmatch(normalized) is None:
        raise ValueError("Invalid restore transaction identifier")
    with _ACTIVE_LOCK:
        _ACTIVE_TRANSACTIONS[normalized] = _ACTIVE_TRANSACTIONS.get(normalized, 0) + 1
    try:
        yield
    finally:
        with _ACTIVE_LOCK:
            remaining = _ACTIVE_TRANSACTIONS.get(normalized, 0) - 1
            if remaining > 0:
                _ACTIVE_TRANSACTIONS[normalized] = remaining
            else:
                _ACTIVE_TRANSACTIONS.pop(normalized, None)


def recover_pending_memory_restore(runtime_paths: RuntimePaths) -> str:
    """Recover one interrupted cutover before database migrations open live files."""

    with _JOURNAL_LOCK:
        journal = read_restore_journal(runtime_paths)
        if journal is None:
            _cleanup_default_orphans(runtime_paths)
            return "none"
        _validate_journal_paths(journal, runtime_paths)
        with _ACTIVE_LOCK:
            active = _ACTIVE_TRANSACTIONS.get(journal.transaction_id, 0) > 0
        if journal.owner_pid == os.getpid() and active:
            return "active"
        if journal.phase == "committed":
            _cleanup_transaction_artifacts(journal)
            delete_restore_journal(runtime_paths, journal.transaction_id)
            _cleanup_default_orphans(runtime_paths)
            return "committed"
        if journal.phase in {"preparing", "prepared"}:
            _cleanup_transaction_artifacts(journal)
            delete_restore_journal(runtime_paths, journal.transaction_id)
            _cleanup_default_orphans(runtime_paths)
            return "aborted"
        if journal.phase == "rolled_back":
            _cleanup_transaction_artifacts(journal)
            delete_restore_journal(runtime_paths, journal.transaction_id)
            _cleanup_default_orphans(runtime_paths)
            return "rolled_back"
        _rollback_journal(journal, runtime_paths)
        completed = replace(journal, phase="rolled_back", owner_pid=os.getpid())
        write_restore_journal(runtime_paths, completed)
        _cleanup_transaction_artifacts(completed)
        delete_restore_journal(runtime_paths, completed.transaction_id)
        _cleanup_default_orphans(runtime_paths)
        return "rolled_back"


def clear_memory_portability_private_data(runtime_paths: RuntimePaths) -> dict[str, int]:
    """Clear private candidates, operation state, snapshots, and safety backups.

    A pending restore owns plaintext rollback data and may be validating new
    live databases, so full-memory clear must never race it.
    """

    with _JOURNAL_LOCK:
        if read_restore_journal(runtime_paths) is not None:
            raise MemoryPortabilityError(
                "restore_transaction_pending",
                "Memory portability data cannot be cleared during a restore transaction.",
                status_code=409,
            )
        counts = {"candidates": 0, "snapshots": 0, "operations": 0, "safety_backups": 0}
        portability_root = require_real_directory(
            runtime_paths.memory_portability_dir,
            label="memory portability directory",
        )
        for owned_name, count_key in (("candidates", "candidates"), ("operations", "operations")):
            owned_path = portability_root / owned_name
            if owned_path.exists() or owned_path.is_symlink():
                remove_owned_path(owned_path)
                counts[count_key] += 1
            owned_path.mkdir(mode=0o700, exist_ok=True)
            if os.name != "nt":
                owned_path.chmod(0o700)
        for entry in list(portability_root.iterdir()):
            if _SNAPSHOT_DIR.fullmatch(entry.name) is not None:
                remove_owned_path(entry)
                counts["snapshots"] += 1
            elif _TEMP_JOURNAL.fullmatch(entry.name) is not None:
                remove_owned_path(entry)

        backups_root = require_real_directory(
            runtime_paths.memory_backups_dir,
            label="memory safety backup directory",
        )
        for entry in list(backups_root.iterdir()):
            if (
                _SAFETY_BACKUP.fullmatch(entry.name) is None
                and _SAFETY_BACKUP_PARTIAL.fullmatch(entry.name) is None
            ):
                continue
            details = entry.lstat()
            if stat.S_ISDIR(details.st_mode) and not stat.S_ISLNK(details.st_mode):
                raise _journal_invalid("A safety backup path conflicts with a directory.")
            entry.unlink()
            counts["safety_backups"] += 1
        fsync_directory(portability_root)
        fsync_directory(backups_root)
        return counts


def rollback_restore_journal(runtime_paths: RuntimePaths, transaction_id: str) -> None:
    """Idempotently roll back one owned transaction and remove its private artifacts."""

    with _JOURNAL_LOCK:
        journal = read_restore_journal(runtime_paths)
        if journal is None:
            return
        if journal.transaction_id != transaction_id:
            raise MemoryPortabilityError(
                "restore_transaction_changed",
                "The durable restore transaction no longer matches this operation.",
                status_code=409,
            )
        _validate_journal_paths(journal, runtime_paths)
        if journal.phase == "committed":
            raise MemoryPortabilityError(
                "restore_already_committed",
                "A committed memory restore cannot be rolled back automatically.",
                status_code=409,
            )
        if journal.phase == "rolled_back":
            _cleanup_transaction_artifacts(journal)
            delete_restore_journal(runtime_paths, transaction_id)
            return
        if journal.phase in {"preparing", "prepared"}:
            _cleanup_transaction_artifacts(journal)
            delete_restore_journal(runtime_paths, transaction_id)
            return
        rolling = replace(journal, phase="rolling_back", owner_pid=os.getpid())
        write_restore_journal(runtime_paths, rolling)
        _rollback_journal(rolling, runtime_paths)
        rolled_back = replace(rolling, phase="rolled_back")
        write_restore_journal(runtime_paths, rolled_back)
        _cleanup_transaction_artifacts(rolled_back)
        delete_restore_journal(runtime_paths, transaction_id)


def commit_restore_journal(runtime_paths: RuntimePaths, transaction_id: str) -> None:
    """Commit only a fully cut-over transaction, then discard plaintext rollback state."""

    with _JOURNAL_LOCK:
        journal = read_restore_journal(runtime_paths)
        if journal is None or journal.transaction_id != transaction_id:
            raise MemoryPortabilityError(
                "restore_transaction_changed",
                "The durable restore transaction no longer matches this operation.",
                status_code=409,
            )
        _validate_journal_paths(journal, runtime_paths)
        if journal.phase == "committed":
            _cleanup_transaction_artifacts(journal)
            delete_restore_journal(runtime_paths, transaction_id)
            return
        if journal.phase != "cutover_complete":
            raise MemoryPortabilityError(
                "restore_not_ready_to_commit",
                "The memory restore has not completed its cutover validation window.",
                status_code=409,
            )
        committed = replace(journal, phase="committed", owner_pid=os.getpid())
        write_restore_journal(runtime_paths, committed)
        _cleanup_transaction_artifacts(committed)
        delete_restore_journal(runtime_paths, transaction_id)


def update_restore_phase(
    runtime_paths: RuntimePaths,
    transaction_id: str,
    phase: str,
) -> RestoreJournal:
    """Persist one cutover phase before its corresponding live mutation."""

    if phase not in _PHASES:
        raise ValueError("Invalid restore phase")
    current = read_restore_journal(runtime_paths)
    if current is None or current.transaction_id != transaction_id:
        raise MemoryPortabilityError(
            "restore_transaction_changed",
            "The durable restore transaction no longer matches this operation.",
            status_code=409,
        )
    updated = replace(current, phase=phase, owner_pid=os.getpid())
    write_restore_journal(runtime_paths, updated)
    return updated


class MemoryRestoreRecoveryModule(LifecycleModule):
    """Recover an interrupted memory cutover before Alembic opens restored databases."""

    def __init__(self, context: RuntimeBootstrapContext):
        super().__init__(
            name="runtime_memory_restore_recovery",
            dependencies=("runtime_core_dependencies",),
        )
        self._context = context

    async def init(self) -> None:
        runtime_paths = self._context.core.runtime_paths
        if runtime_paths is None:
            raise RuntimeError("runtime paths is not initialized")
        result = await asyncio.to_thread(recover_pending_memory_restore, runtime_paths)
        if result != "none":
            logger.info("Memory restore startup recovery completed", result=result)


def _write_journal_temporary(directory: Path, journal: RestoreJournal) -> Path:
    payload = json.dumps(
        journal.to_dict(),
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(payload) > MAX_RESTORE_JOURNAL_BYTES:
        raise MemoryPortabilityError(
            "restore_journal_invalid",
            "The memory restore journal exceeds its supported size.",
            status_code=500,
        )
    temporary = directory / (
        f".memory-restore-journal-{journal.transaction_id}-{uuid.uuid4().hex}.tmp"
    )
    with open_private_exclusive(temporary) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return temporary


def _journal_temporaries(directory: Path) -> list[Path]:
    return sorted(
        (entry for entry in directory.iterdir() if _TEMP_JOURNAL.fullmatch(entry.name) is not None),
        key=lambda item: item.name,
    )


def _read_journal_file(path: Path) -> RestoreJournal:
    try:
        details = path.lstat()
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1
            or details.st_size <= 0
            or details.st_size > MAX_RESTORE_JOURNAL_BYTES
        ):
            raise ValueError("invalid restore journal file")
        payload = json.loads(path.read_text(encoding="utf-8"))
        return RestoreJournal.from_mapping(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise _journal_invalid("The memory restore journal is invalid or incomplete.") from exc


def _journal_invalid(message: str) -> MemoryPortabilityError:
    return MemoryPortabilityError(
        "restore_journal_invalid",
        message,
        status_code=500,
    )


def _validate_journal_paths(journal: RestoreJournal, runtime_paths: RuntimePaths) -> None:
    tx = journal.transaction_id
    paths = {key: Path(value) for key, value in journal.paths.items()}

    def absolute(path: Path) -> Path:
        return Path(os.path.abspath(os.fspath(path)))

    expected_exact = {
        "l1_db": absolute(runtime_paths.l1_memory_db_path),
        "memory_db": absolute(runtime_paths.memory_db_path),
        "asset_dir": absolute(runtime_paths.manual_entry_assets_dir),
        "db_stage": absolute(runtime_paths.memory_dir / f".magi-memory-restore-{tx}-db-stage"),
        "db_rollback": absolute(
            runtime_paths.memory_dir / f".magi-memory-restore-{tx}-db-rollback"
        ),
        "db_discard": absolute(runtime_paths.memory_dir / f".magi-memory-restore-{tx}-db-discard"),
        "asset_stage": absolute(
            runtime_paths.manual_entry_assets_dir.parent / f".magi-memory-restore-{tx}-assets-stage"
        ),
        "asset_rollback": absolute(
            runtime_paths.manual_entry_assets_dir.parent
            / f".magi-memory-restore-{tx}-assets-rollback"
        ),
        "asset_discard": absolute(
            runtime_paths.manual_entry_assets_dir.parent
            / f".magi-memory-restore-{tx}-assets-discard"
        ),
    }
    for key, expected in expected_exact.items():
        if absolute(paths[key]) != expected:
            raise _journal_invalid("The restore journal contains an unexpected owned path.")

    archive_dir = absolute(paths["archive_dir"])
    archive_details = require_real_directory(
        archive_dir,
        label="configured memory archive directory",
    ).lstat()
    if (
        int(archive_details.st_dev) != journal.archive_device
        or int(archive_details.st_ino) != journal.archive_inode
    ):
        raise _journal_invalid("The configured memory archive directory changed during restore.")
    for key, suffix in (
        ("archive_stage", "stage"),
        ("archive_rollback", "rollback"),
        ("archive_discard", "discard"),
    ):
        expected = archive_dir / f".magi-memory-restore-{tx}-archive-{suffix}"
        if absolute(paths[key]) != expected:
            raise _journal_invalid("The restore journal contains an unexpected archive path.")

    if journal.safety_backup_path is not None:
        safety_path = absolute(Path(journal.safety_backup_path))
        safety_root = absolute(runtime_paths.memory_backups_dir)
        if (
            safety_path.parent != safety_root
            or _SAFETY_BACKUP.fullmatch(safety_path.name) is None
            or not safety_path.name.startswith(f"pre-restore-{tx}-")
        ):
            raise _journal_invalid("The restore journal contains an unexpected safety backup path.")


def _rollback_journal(journal: RestoreJournal, runtime_paths: RuntimePaths) -> None:
    journal.require_complete()
    _validate_journal_paths(journal, runtime_paths)
    paths = {key: Path(value) for key, value in journal.paths.items()}
    assert journal.rollback_l1 is not None
    assert journal.rollback_memory is not None
    assert journal.rollback_archives is not None
    assert journal.rollback_assets is not None
    _require_file_fingerprint(paths["db_rollback"] / "l1_events.db", journal.rollback_l1)
    _require_file_fingerprint(paths["db_rollback"] / "memory.db", journal.rollback_memory)
    _require_tree_fingerprint(
        paths["archive_rollback"],
        journal.rollback_archives,
        path_validator=_archive_path_is_valid,
    )
    _require_tree_fingerprint(paths["asset_rollback"], journal.rollback_assets)

    _restore_asset_tree(journal, paths)
    _restore_archive_set(journal, paths)
    _restore_database(
        rollback=paths["db_rollback"] / "memory.db",
        live=paths["memory_db"],
        expected=journal.rollback_memory,
        transaction_id=journal.transaction_id,
        restore_directory=paths["db_discard"],
    )
    _restore_database(
        rollback=paths["db_rollback"] / "l1_events.db",
        live=paths["l1_db"],
        expected=journal.rollback_l1,
        transaction_id=journal.transaction_id,
        restore_directory=paths["db_discard"],
    )


def _restore_database(
    *,
    rollback: Path,
    live: Path,
    expected: FileFingerprint,
    transaction_id: str,
    restore_directory: Path,
) -> None:
    temporary = restore_directory / f"rollback-{transaction_id}-{live.name}.tmp"
    remove_owned_path(temporary)
    copy_private_file(
        rollback,
        temporary,
        expected_size=expected.size_bytes,
        expected_sha256=expected.sha256,
    )
    remove_sqlite_family(live)
    os.replace(temporary, live)
    if os.name != "nt":
        live.chmod(0o600)
    fsync_directory(live.parent)


def _restore_archive_set(journal: RestoreJournal, paths: dict[str, Path]) -> None:
    archive_dir = require_real_directory(paths["archive_dir"], label="memory archive directory")
    for entry in list(archive_dir.iterdir()):
        if _ARCHIVE_OWNED_NAME.fullmatch(entry.name) is None:
            continue
        details = entry.lstat()
        if stat.S_ISDIR(details.st_mode) and not stat.S_ISLNK(details.st_mode):
            raise _journal_invalid("A managed archive target conflicts with a directory.")
        entry.unlink()
    for rollback, relative_path in _iter_tree(paths["archive_rollback"]):
        if not _archive_path_is_valid(relative_path.as_posix()):
            raise _journal_invalid("The archive rollback tree contains an unexpected path.")
        destination = archive_dir / relative_path.name
        copy_private_file(rollback, destination)
    fsync_directory(archive_dir)


def _restore_asset_tree(journal: RestoreJournal, paths: dict[str, Path]) -> None:
    live = paths["asset_dir"]
    remove_owned_path(live)
    if journal.asset_dir_existed:
        temporary = live.parent / f".magi-memory-restore-{journal.transaction_id}-assets-restore"
        remove_owned_path(temporary)
        copy_private_tree(paths["asset_rollback"], temporary)
        os.replace(temporary, live)
        if os.name != "nt":
            live.chmod(0o700)
        fsync_directory(live.parent)


def _cleanup_transaction_artifacts(journal: RestoreJournal) -> None:
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
        remove_owned_path(Path(journal.paths[key]))


def _cleanup_default_orphans(runtime_paths: RuntimePaths) -> None:
    for root in (runtime_paths.memory_dir, runtime_paths.manual_entry_assets_dir.parent):
        try:
            entries = list(root.iterdir())
        except FileNotFoundError:
            continue
        for entry in entries:
            if _ORPHAN_DIR.fullmatch(entry.name) is not None:
                remove_owned_path(entry)
    portability_root = runtime_paths.memory_portability_dir
    try:
        entries = list(portability_root.iterdir())
    except FileNotFoundError:
        return
    for entry in entries:
        if _SNAPSHOT_DIR.fullmatch(entry.name) is not None:
            remove_owned_path(entry)
    # Candidate cleanup preserves valid unexpired inspections and removes only
    # invalid, incomplete, linked, or expired UUID-owned directories.
    from .preflight import cleanup_expired_candidates

    cleanup_expired_candidates(runtime_paths)


def _require_file_fingerprint(path: Path, expected: FileFingerprint) -> None:
    size, digest = fingerprint_file(path)
    if size != expected.size_bytes or digest != expected.sha256:
        raise _journal_invalid("A rollback file failed its integrity check.")


def _require_tree_fingerprint(
    path: Path,
    expected: TreeFingerprint,
    *,
    path_validator=None,
) -> None:
    actual = TreeFingerprint(*tree_fingerprint(path, path_validator=path_validator))
    if actual != expected:
        raise _journal_invalid("A rollback file tree failed its integrity check.")


def _iter_tree(root: Path):
    from .fs_helpers import iter_private_tree_files

    return iter_private_tree_files(root)


def _archive_path_is_valid(relative_path: str) -> bool:
    return "/" not in relative_path and _ARCHIVE_DB_NAME.fullmatch(relative_path) is not None


__all__ = [
    "FileFingerprint",
    "MemoryRestoreRecoveryModule",
    "RestoreJournal",
    "TreeFingerprint",
    "clear_memory_portability_private_data",
    "commit_restore_journal",
    "create_restore_journal",
    "delete_restore_journal",
    "journal_path",
    "read_restore_journal",
    "recover_pending_memory_restore",
    "register_active_memory_restore",
    "rollback_restore_journal",
    "update_restore_phase",
    "write_restore_journal",
]
