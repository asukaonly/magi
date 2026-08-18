"""Build versioned memory backup packages from consistent private snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
from typing import BinaryIO, Literal
import uuid
import zipfile

from .crypto import encrypt_backup_payload
from .errors import MemoryPortabilityError
from .models import (
    BACKUP_LIMITATIONS,
    BackupFileRecord,
    BackupManifest,
    SnapshotBundle,
    utc_now_iso,
)
from .storage import sha256_file


def build_memory_backup(
    *,
    snapshot: SnapshotBundle,
    output_directory: Path,
    encryption: Literal["password", "none"],
    password: str | None,
    filename_prefix: str = "magi-memory-backup",
) -> tuple[Path, BackupManifest]:
    """Package a snapshot into one atomic, optionally encrypted backup file."""

    output_directory = _require_output_directory(output_directory)
    if not re.fullmatch(r"[a-z0-9-]{1,64}", filename_prefix):
        raise MemoryPortabilityError(
            "backup_filename_invalid",
            "The backup filename prefix is invalid.",
            status_code=500,
        )
    if encryption == "password":
        if not password or not str(password).strip():
            raise MemoryPortabilityError(
                "password_required",
                "A non-empty password is required for encrypted backup output.",
            )
        encrypted = True
    elif encryption == "none":
        if password is not None:
            raise MemoryPortabilityError(
                "password_not_allowed",
                "A password cannot be supplied for an unencrypted backup.",
            )
        encrypted = False
    else:
        raise MemoryPortabilityError(
            "encryption_mode_invalid",
            "The requested backup encryption mode is invalid.",
        )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    unique_suffix = uuid.uuid4().hex
    output_path = output_directory / f"{filename_prefix}-{timestamp}-{unique_suffix}.magibackup"
    if output_path.parent != output_directory:
        raise MemoryPortabilityError(
            "backup_filename_invalid",
            "The backup output path is invalid.",
            status_code=500,
        )
    partial_path = output_directory / f".{output_path.name}.partial"
    payload_path = Path(snapshot.root) / "backup-payload.zip"

    records = [
        BackupFileRecord(
            path=item.archive_path,
            purpose=item.purpose,
            size_bytes=Path(item.source_path).stat().st_size,
            sha256=sha256_file(Path(item.source_path)),
        )
        for item in sorted(snapshot.files, key=lambda candidate: candidate.archive_path)
    ]
    manifest = BackupManifest(
        backup_id=str(uuid.uuid4()),
        created_at=utc_now_iso(),
        magi_version=_magi_version(),
        encrypted=encrypted,
        scope=["l1", "l2", "l3", "l4", "archives", "manual_entry_assets"],
        schema_revisions={
            "l1": snapshot.schema_revisions["l1"],
            "memory_shared": snapshot.schema_revisions["memory_shared"],
        },
        archive_schema_version=1,
        limitations=list(BACKUP_LIMITATIONS),
        files=records,
        counts={key: int(value) for key, value in snapshot.counts.items()},
    )
    estimated_bytes = sum(record.size_bytes for record in records) + 1024 * 1024
    _require_free_space(output_directory, estimated_bytes)

    try:
        _write_payload_zip(snapshot, manifest, payload_path)
        if encrypted:
            encrypt_backup_payload(payload_path, partial_path, str(password))
        else:
            _copy_exclusive(payload_path, partial_path)
        partial_path.chmod(0o600)
        os.replace(partial_path, output_path)
        _fsync_directory(output_directory)
        return output_path, manifest
    except MemoryPortabilityError:
        partial_path.unlink(missing_ok=True)
        raise
    except OSError as exc:
        partial_path.unlink(missing_ok=True)
        raise MemoryPortabilityError(
            "backup_write_failed",
            "The backup file could not be written to the selected directory.",
            status_code=500,
        ) from exc
    finally:
        payload_path.unlink(missing_ok=True)


def _write_payload_zip(
    snapshot: SnapshotBundle,
    manifest: BackupManifest,
    payload_path: Path,
) -> None:
    try:
        with (
            _open_private_exclusive(payload_path) as payload_handle,
            zipfile.ZipFile(
                payload_handle,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=6,
                allowZip64=True,
            ) as archive,
        ):
            manifest_bytes = json.dumps(
                manifest.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            _write_bytes(archive, "manifest.json", manifest_bytes)
            source_by_archive_path = {
                item.archive_path: Path(item.source_path) for item in snapshot.files
            }
            for record in manifest.files:
                _write_file(archive, record.path, source_by_archive_path[record.path])
    except (OSError, zipfile.BadZipFile) as exc:
        raise MemoryPortabilityError(
            "backup_package_failed",
            "The memory snapshot could not be packaged.",
            status_code=500,
        ) from exc


def _write_bytes(archive: zipfile.ZipFile, archive_path: str, content: bytes) -> None:
    info = zipfile.ZipInfo(archive_path)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100600 << 16
    archive.writestr(info, content)


def _write_file(archive: zipfile.ZipFile, archive_path: str, source: Path) -> None:
    info = zipfile.ZipInfo(archive_path)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100600 << 16
    with (
        source.open("rb") as input_handle,
        archive.open(info, "w", force_zip64=True) as output_handle,
    ):
        shutil.copyfileobj(input_handle, output_handle, length=1024 * 1024)


def _copy_exclusive(source: Path, destination: Path) -> None:
    with source.open("rb") as input_handle, _open_private_exclusive(destination) as output_handle:
        shutil.copyfileobj(input_handle, output_handle, length=1024 * 1024)
        output_handle.flush()
        os.fsync(output_handle.fileno())


def _open_private_exclusive(path: Path) -> BinaryIO:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(Path(path), flags, 0o600)
    return os.fdopen(descriptor, "wb")


def _require_output_directory(path: Path) -> Path:
    expanded = Path(path).expanduser()
    try:
        resolved = expanded.resolve(strict=True)
        if not resolved.is_dir():
            raise OSError("not a directory")
    except OSError as exc:
        raise MemoryPortabilityError(
            "output_directory_invalid",
            "The selected output directory is unavailable.",
        ) from exc
    return resolved


def _require_free_space(directory: Path, required_bytes: int) -> None:
    try:
        free_bytes = shutil.disk_usage(directory).free
    except OSError as exc:
        raise MemoryPortabilityError(
            "free_space_unknown",
            "Available space could not be checked for the selected directory.",
        ) from exc
    if free_bytes < max(int(required_bytes), 8 * 1024 * 1024):
        raise MemoryPortabilityError(
            "insufficient_space",
            "The selected directory does not have enough free space.",
        )


def _magi_version() -> str:
    try:
        return importlib.metadata.version("magi")
    except importlib.metadata.PackageNotFoundError:
        return "development"


def _fsync_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    directory_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = ["build_memory_backup"]
