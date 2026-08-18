"""Strict restore inspection and immutable private candidate staging."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import struct
import uuid
import zipfile

from pydantic import ValidationError
import sqlite_vec

from ...db.runner import (
    MigrationExecutionError,
    MigrationRevisionError,
    migration_head,
    run_upgrade_database,
    validate_migration_revision,
)
from ...utils.file_io import atomic_write_text
from ...utils.runtime import RuntimePaths
from ..event_contracts import author_type_label, content_type_label
from ..hybrid_retrieval.fts_utils import tokenize_for_fts
from ..l3.retrieval.search import fts_backfill_row as l3_fts_backfill_row
from ..l3.source_event_governance import active_summary_predicate
from ..l4.retrieval.search import fts_backfill_row as l4_fts_backfill_row
from ..l4.source_event_governance import active_skill_predicate
from ..manual_entries.asset_store import MAX_UPLOAD_BYTES
from .backup import _fsync_file, _open_private_exclusive, _require_free_space
from .crypto import ENCRYPTED_BACKUP_MAGIC, decrypt_backup_payload, is_encrypted_backup
from .errors import BackupPasswordRequiredError, MemoryPortabilityError
from .models import (
    BACKUP_FORMAT,
    BACKUP_FORMAT_VERSION,
    MAX_BACKUP_FILE_COUNT,
    MAX_BACKUP_MANIFEST_BYTES,
    MAX_BACKUP_MEMBER_BYTES,
    MAX_BACKUP_UNCOMPRESSED_BYTES,
    BackupFileRecord,
    BackupInspection,
    BackupManifest,
    RestoreCandidateMetadata,
    utc_now_iso,
)
from .storage import (
    clear_portability_operational_state,
    count_snapshot_records,
    database_revision,
    referenced_manual_asset_archive_paths,
    sha256_file,
    snapshot_file_record_count,
)

MAX_BACKUP_CONTAINER_BYTES = MAX_BACKUP_UNCOMPRESSED_BYTES
MAX_MANIFEST_BYTES = MAX_BACKUP_MANIFEST_BYTES
MAX_ZIP_DIRECTORY_BYTES = 128 * 1024 * 1024
MAX_BACKUP_PATH_BYTES = 1024
MAX_BACKUP_PATH_DEPTH = 8
MAX_BACKUP_COMPONENT_BYTES = 255
MAX_COMPRESSION_RATIO = 1000
RESTORE_MIGRATION_MARGIN_BYTES = 32 * 1024 * 1024
RESTORE_CANDIDATE_TTL = timedelta(minutes=30)

_ZIP_END_RECORD = struct.Struct("<4s4H2LH")
_ZIP_END_SIGNATURE = b"PK\x05\x06"
_ZIP_CENTRAL_RECORD = struct.Struct("<4s6H3L5H2L")
_ZIP_CENTRAL_SIGNATURE = b"PK\x01\x02"
_ZIP_LOCAL_RECORD = struct.Struct("<4s5H3L2H")
_ZIP_LOCAL_SIGNATURE = b"PK\x03\x04"
_ZIP_MAX_COMMENT_BYTES = (1 << 16) - 1
_ZIP_SENTINEL_16 = (1 << 16) - 1
_ZIP_SENTINEL_32 = (1 << 32) - 1
_ZIP_ALLOWED_FLAGS = 0x800
_ZIP_ALLOWED_METHODS = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}

_ARCHIVE_SCHEMA_SQL = {
    "archived_l1_events": (
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
        )
        """,
        """
        CREATE INDEX idx_archived_l1_events_date
        ON archived_l1_events(archived_date, event_timestamp)
        """,
    ),
    "archived_l3_summaries": (
        """
        CREATE TABLE archived_l3_summaries (
            summary_id TEXT PRIMARY KEY,
            archived_date TEXT NOT NULL,
            archived_at REAL NOT NULL,
            period_start REAL NOT NULL,
            period_end REAL NOT NULL,
            summary_type TEXT NOT NULL,
            summary_category TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """,
        """
        CREATE INDEX idx_archived_l3_summaries_date
        ON archived_l3_summaries(archived_date, period_end)
        """,
    ),
}
_VECTOR_SPECS = {
    "l1": (("l1_event_chunk_vectors", "chunk_id", "l1_event_vec", True),),
    "memory_shared": (
        ("l2_entity_vectors", "entity_id", "l2_entity_vec", False),
        ("l2_edge_vectors", "entity_id", "l2_edge_vec", False),
        ("l3_summary_chunk_vectors", "chunk_id", "l3_summary_chunk_vec", False),
        ("l4_skill_chunk_vectors", "chunk_id", "l4_skill_chunk_vec", False),
    ),
}
_VECTOR_REGISTRY_COLUMNS = (
    "vec_rowid",
    "entity_column",
    "embedding_model",
    "embedding_dim",
    "vec_table",
    "metadata",
    "created_at",
    "updated_at",
)
_VECTOR_SHADOW_SUFFIXES = ("_chunks", "_info", "_rowids", "_vector_chunks00")
_VECTOR_SHADOW_COLUMNS = {
    "_chunks": ("chunk_id", "size", "validity", "rowids"),
    "_info": ("key", "value"),
    "_rowids": ("rowid", "id", "chunk_id", "chunk_offset"),
    "_vector_chunks00": ("rowid", "vectors"),
}
_MAX_VECTOR_DIMENSION = 65_536


def backup_requires_password(source_path: Path) -> bool:
    """Probe only the authenticated-envelope magic without retaining source data."""

    descriptor, _details = _open_external_regular_file(source_path)
    try:
        return os.read(descriptor, len(ENCRYPTED_BACKUP_MAGIC)) == ENCRYPTED_BACKUP_MAGIC
    finally:
        os.close(descriptor)


def inspect_memory_backup(
    *,
    source_path: Path,
    password: str | None,
    runtime_paths: RuntimePaths,
    archive_target: Path,
) -> BackupInspection:
    """Validate, migrate, and retain an immutable private restore candidate."""

    cleanup_expired_candidates(runtime_paths)
    if backup_requires_password(source_path) and password is None:
        raise BackupPasswordRequiredError()

    candidate_id = str(uuid.uuid4())
    candidates_root = runtime_paths.memory_portability_dir / "candidates"
    _ensure_private_directory(candidates_root)
    candidate_root = candidates_root / candidate_id
    candidate_root.mkdir(mode=0o700, exist_ok=False)
    if os.name != "nt":
        candidate_root.chmod(0o700)
    source_copy = candidate_root / "source.magibackup"
    payload_zip = candidate_root / "payload.zip"
    extracted_root = candidate_root / "payload"
    try:
        _copy_external_backup(source_path, source_copy)
        encrypted = is_encrypted_backup(source_copy)
        if encrypted:
            if password is None:
                raise BackupPasswordRequiredError()
            decrypt_backup_payload(source_copy, payload_zip, password)
        else:
            if password is not None:
                raise MemoryPortabilityError(
                    "password_not_allowed",
                    "The selected backup is not encrypted.",
                )
            _copy_private_file(source_copy, payload_zip, max_bytes=MAX_BACKUP_CONTAINER_BYTES)

        manifest = _validate_and_extract_payload(
            payload_zip=payload_zip,
            extracted_root=extracted_root,
            encrypted=encrypted,
        )
        compatibility = _validate_and_prepare_databases(extracted_root, manifest)
        archive_paths = _validate_archive_databases(extracted_root, manifest)
        asset_count = _validate_manual_assets(extracted_root, manifest)
        _validate_file_record_counts(extracted_root, manifest)
        actual_counts = count_snapshot_records(
            extracted_root / "databases" / "l1_events.db",
            extracted_root / "databases" / "memory.db",
            archive_paths,
        )
        actual_counts["manual_entry_assets"] = asset_count
        if actual_counts != manifest.counts:
            raise MemoryPortabilityError(
                "backup_counts_invalid",
                "The backup record counts do not match its validated contents.",
            )

        staged_files = _build_staged_inventory(extracted_root, manifest)
        inspected_at = utc_now_iso()
        expires_at = datetime.now(timezone.utc) + RESTORE_CANDIDATE_TTL
        expires_at_text = expires_at.isoformat(timespec="seconds").replace("+00:00", "Z")
        resolved_archive_target = _validate_archive_target(archive_target)
        source_copy.unlink(missing_ok=True)
        payload_zip.unlink(missing_ok=True)

        metadata_payload = {
            "format": "magi-memory-restore-candidate",
            "format_version": 1,
            "candidate_id": candidate_id,
            "fingerprint": "0" * 64,
            "inspected_at": inspected_at,
            "expires_at": expires_at_text,
            "archive_target": str(resolved_archive_target),
            "compatibility": compatibility,
            "manifest": manifest.model_dump(mode="json"),
            "staged_files": [record.model_dump(mode="json") for record in staged_files],
        }
        metadata_payload["fingerprint"] = _candidate_fingerprint(metadata_payload)
        metadata = RestoreCandidateMetadata.model_validate(metadata_payload)
        metadata_path = candidate_root / "candidate.json"
        atomic_write_text(
            metadata_path,
            json.dumps(
                metadata.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        if os.name != "nt":
            metadata_path.chmod(0o600)
        _fsync_file(metadata_path)

        warnings = [
            "restore_replaces_current_memory",
            "deleted_memories_may_return",
            *manifest.limitations,
        ]
        return BackupInspection(
            candidate_id=candidate_id,
            fingerprint=metadata.fingerprint,
            created_at=manifest.created_at,
            magi_version=manifest.magi_version,
            encrypted=manifest.encrypted,
            compatibility=compatibility,
            scope=list(manifest.scope),
            counts=dict(manifest.counts),
            warnings=warnings,
            expires_at=expires_at_text,
        )
    except BaseException as exc:
        shutil.rmtree(candidate_root, ignore_errors=True)
        if isinstance(exc, (KeyboardInterrupt, MemoryPortabilityError, SystemExit)):
            raise
        raise MemoryPortabilityError(
            "backup_inspection_failed",
            "The selected backup could not be inspected safely.",
        ) from exc


def load_restore_candidate(
    *,
    runtime_paths: RuntimePaths,
    candidate_id: str,
    fingerprint: str | None = None,
) -> tuple[Path, dict[str, object], BackupManifest]:
    """Load one unexpired candidate and reverify every staged file."""

    parsed_id = _parse_candidate_id(candidate_id)
    candidate_root = runtime_paths.memory_portability_dir / "candidates" / str(parsed_id)
    try:
        details = candidate_root.lstat()
    except OSError as exc:
        raise MemoryPortabilityError(
            "candidate_unavailable",
            "The inspected restore candidate is no longer available.",
            status_code=404,
        ) from exc
    if (
        stat.S_ISLNK(details.st_mode)
        or not stat.S_ISDIR(details.st_mode)
        or not _has_private_permissions(details)
    ):
        raise MemoryPortabilityError(
            "candidate_unavailable",
            "The inspected restore candidate is no longer available.",
            status_code=404,
        )

    try:
        raw_metadata = _read_regular_file(
            candidate_root / "candidate.json",
            max_bytes=MAX_MANIFEST_BYTES,
        )
        metadata = RestoreCandidateMetadata.model_validate_json(raw_metadata)
    except (OSError, ValidationError, ValueError) as exc:
        shutil.rmtree(candidate_root, ignore_errors=True)
        raise MemoryPortabilityError(
            "candidate_unavailable",
            "The inspected restore candidate is no longer available.",
            status_code=404,
        ) from exc
    try:
        if metadata.candidate_id != candidate_id:
            raise MemoryPortabilityError(
                "candidate_changed",
                "The restore candidate metadata changed after inspection.",
            )
        if fingerprint is not None and metadata.fingerprint != fingerprint:
            raise MemoryPortabilityError(
                "candidate_changed",
                "The restore candidate fingerprint does not match.",
            )
        if _candidate_fingerprint(metadata.model_dump(mode="json")) != metadata.fingerprint:
            raise MemoryPortabilityError(
                "candidate_changed",
                "The restore candidate metadata changed after inspection.",
            )
        expires_at = _parse_utc_timestamp(metadata.expires_at, label="candidate expiry")
        if expires_at <= datetime.now(timezone.utc):
            raise MemoryPortabilityError(
                "candidate_expired",
                "The inspected restore candidate has expired.",
            )
        _verify_staged_inventory(candidate_root / "payload", metadata.staged_files)
    except MemoryPortabilityError:
        shutil.rmtree(candidate_root, ignore_errors=True)
        raise
    return candidate_root, metadata.model_dump(mode="json"), metadata.manifest


def delete_restore_candidate(*, runtime_paths: RuntimePaths, candidate_id: str) -> None:
    """Delete one private inspected candidate by its generated UUID."""

    try:
        parsed_id = _parse_candidate_id(candidate_id)
    except MemoryPortabilityError:
        return
    shutil.rmtree(
        runtime_paths.memory_portability_dir / "candidates" / str(parsed_id),
        ignore_errors=True,
    )


def cleanup_expired_candidates(runtime_paths: RuntimePaths) -> int:
    """Remove only UUID-named candidate directories that are expired or invalid."""

    candidates_root = runtime_paths.memory_portability_dir / "candidates"
    try:
        root_details = candidates_root.lstat()
    except FileNotFoundError:
        return 0
    except OSError:
        return 0
    if stat.S_ISLNK(root_details.st_mode) or not stat.S_ISDIR(root_details.st_mode):
        return 0
    removed = 0
    for entry in candidates_root.iterdir():
        try:
            parsed_id = uuid.UUID(entry.name)
            details = entry.lstat()
        except (ValueError, OSError):
            continue
        if parsed_id.version != 4 or str(parsed_id) != entry.name:
            continue
        if stat.S_ISLNK(details.st_mode):
            entry.unlink(missing_ok=True)
            removed += 1
            continue
        if not stat.S_ISDIR(details.st_mode):
            continue
        try:
            raw = _read_regular_file(entry / "candidate.json", max_bytes=MAX_MANIFEST_BYTES)
            metadata = RestoreCandidateMetadata.model_validate_json(raw)
            expires_at = _parse_utc_timestamp(metadata.expires_at, label="candidate expiry")
        except (OSError, ValidationError, ValueError, MemoryPortabilityError):
            expires_at = datetime.min.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
    return removed


def _validate_and_extract_payload(
    *,
    payload_zip: Path,
    extracted_root: Path,
    encrypted: bool,
) -> BackupManifest:
    _validate_zip_directory(payload_zip)
    try:
        with zipfile.ZipFile(payload_zip, mode="r", allowZip64=False) as archive:
            infos = archive.infolist()
            if not infos or len(infos) > MAX_BACKUP_FILE_COUNT + 1:
                raise MemoryPortabilityError(
                    "backup_member_count_invalid",
                    "The backup contains an unsupported number of files.",
                )
            info_by_name = _validate_member_names(infos)
            manifest_info = info_by_name.get("manifest.json")
            if manifest_info is None or manifest_info.file_size > MAX_MANIFEST_BYTES:
                raise MemoryPortabilityError(
                    "manifest_invalid",
                    "The backup manifest is missing or too large.",
                )
            try:
                manifest_payload = json.loads(archive.read(manifest_info).decode("utf-8"))
            except (UnicodeDecodeError, ValueError, zipfile.BadZipFile) as exc:
                raise MemoryPortabilityError(
                    "manifest_invalid",
                    "The backup manifest is not valid UTF-8 JSON.",
                ) from exc
            if not isinstance(manifest_payload, dict):
                raise MemoryPortabilityError(
                    "manifest_invalid",
                    "The backup manifest is not a JSON object.",
                )
            if manifest_payload.get("format") != BACKUP_FORMAT:
                raise MemoryPortabilityError(
                    "backup_format_invalid",
                    "The selected file is not a Magi memory backup.",
                )
            if manifest_payload.get("format_version") != BACKUP_FORMAT_VERSION:
                raise MemoryPortabilityError(
                    "backup_version_unsupported",
                    "The backup format version is not supported by this Magi version.",
                )
            revisions = manifest_payload.get("schema_revisions")
            if not isinstance(revisions, dict) or any(
                not isinstance(value, str) or not value.strip() for value in revisions.values()
            ):
                raise MemoryPortabilityError(
                    "schema_revision_unsupported",
                    "The backup was created by an incompatible memory schema.",
                )
            try:
                manifest = BackupManifest.model_validate(manifest_payload)
            except ValidationError as exc:
                raise MemoryPortabilityError(
                    "manifest_invalid",
                    "The backup manifest does not satisfy the version-1 contract.",
                ) from exc
            if manifest.encrypted is not encrypted:
                raise MemoryPortabilityError(
                    "encryption_state_invalid",
                    "The backup encryption envelope does not match its manifest.",
                )
            records = {record.path: record for record in manifest.files}
            member_names = set(info_by_name) - {"manifest.json"}
            if member_names != set(records):
                raise MemoryPortabilityError(
                    "backup_members_invalid",
                    "The backup files do not match its manifest.",
                )
            total_bytes = sum(
                info.file_size for name, info in info_by_name.items() if name != "manifest.json"
            )
            if total_bytes > MAX_BACKUP_UNCOMPRESSED_BYTES:
                raise MemoryPortabilityError(
                    "backup_too_large",
                    "The backup expands beyond the supported size.",
                )
            largest_memory_database = max(
                record.size_bytes for record in manifest.files if record.purpose in {"l1", "memory"}
            )
            migration_margin = max(
                total_bytes // 5,
                RESTORE_MIGRATION_MARGIN_BYTES,
            )
            _require_free_space(
                extracted_root.parent,
                total_bytes + largest_memory_database + migration_margin,
            )
            extracted_root.mkdir(mode=0o700, exist_ok=False)
            if os.name != "nt":
                extracted_root.chmod(0o700)
            for archive_path in sorted(records):
                info = info_by_name[archive_path]
                record = records[archive_path]
                if info.file_size != record.size_bytes:
                    raise MemoryPortabilityError(
                        "backup_size_invalid",
                        "A backup file size does not match its manifest.",
                    )
                if record.purpose == "manual_entry_asset" and info.file_size > MAX_UPLOAD_BYTES:
                    raise MemoryPortabilityError(
                        "backup_asset_too_large",
                        "A managed memory asset in the backup is too large.",
                    )
                destination = extracted_root.joinpath(*PurePosixPath(archive_path).parts)
                _ensure_private_directory(destination.parent)
                actual_digest = _extract_member(archive, info, destination, record.size_bytes)
                if actual_digest != record.sha256:
                    raise MemoryPortabilityError(
                        "backup_checksum_invalid",
                        "A backup file failed its integrity check.",
                    )
            return manifest
    except MemoryPortabilityError:
        raise
    except (
        NotImplementedError,
        OSError,
        RuntimeError,
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
    ) as exc:
        raise MemoryPortabilityError(
            "backup_archive_invalid",
            "The backup payload is not a supported ZIP archive.",
        ) from exc


def _validate_zip_directory(archive_path: Path) -> None:
    """Bound and validate ZIP records before ``zipfile`` inventories members."""

    try:
        archive_size = archive_path.stat().st_size
        if archive_size <= 0 or archive_size > MAX_BACKUP_CONTAINER_BYTES:
            raise MemoryPortabilityError(
                "backup_too_large",
                "The selected backup exceeds the version-1 size limit.",
            )
        tail_size = min(archive_size, _ZIP_END_RECORD.size + _ZIP_MAX_COMMENT_BYTES)
        with archive_path.open("rb") as archive:
            archive.seek(archive_size - tail_size)
            tail = archive.read(tail_size)
            end_record = _find_zip_end_record(tail)
            if end_record is None:
                raise MemoryPortabilityError(
                    "backup_archive_invalid",
                    "The backup ZIP end record is invalid.",
                )
            end_offset_in_tail, values = end_record
            (
                _signature,
                disk_number,
                central_disk_number,
                entries_on_disk,
                total_entries,
                central_size,
                central_offset,
                _comment_size,
            ) = values
            if disk_number != 0 or central_disk_number != 0 or entries_on_disk != total_entries:
                raise MemoryPortabilityError(
                    "backup_archive_unsupported",
                    "Multi-disk ZIP backups are not supported.",
                )
            if (
                total_entries == _ZIP_SENTINEL_16
                or central_size == _ZIP_SENTINEL_32
                or central_offset == _ZIP_SENTINEL_32
            ):
                raise MemoryPortabilityError(
                    "backup_zip64_unsupported",
                    "ZIP64 backups are not supported by format version 1.",
                )
            if total_entries == 0 or total_entries > MAX_BACKUP_FILE_COUNT + 1:
                raise MemoryPortabilityError(
                    "backup_member_count_invalid",
                    "The backup contains an unsupported number of files.",
                )
            if central_size > MAX_ZIP_DIRECTORY_BYTES:
                raise MemoryPortabilityError(
                    "backup_archive_invalid",
                    "The backup ZIP directory exceeds its metadata limit.",
                )
            end_offset = archive_size - tail_size + end_offset_in_tail
            if central_offset + central_size != end_offset:
                raise MemoryPortabilityError(
                    "backup_archive_invalid",
                    "The backup ZIP directory has invalid bounds.",
                )
            archive.seek(central_offset)
            entries = _parse_zip_directory(archive, central_size=central_size)
            if len(entries) != total_entries:
                raise MemoryPortabilityError(
                    "backup_archive_invalid",
                    "The backup ZIP directory entry count is inconsistent.",
                )
            _validate_zip_local_records(
                archive,
                entries=entries,
                central_offset=central_offset,
            )
    except MemoryPortabilityError:
        raise
    except (OSError, struct.error) as exc:
        raise MemoryPortabilityError(
            "backup_archive_invalid",
            "The backup payload is not a valid ZIP archive.",
        ) from exc


def _find_zip_end_record(
    tail: bytes,
) -> tuple[int, tuple[bytes, int, int, int, int, int, int, int]] | None:
    search_end = len(tail)
    while True:
        offset = tail.rfind(_ZIP_END_SIGNATURE, 0, search_end)
        if offset < 0:
            return None
        if offset + _ZIP_END_RECORD.size <= len(tail):
            values = _ZIP_END_RECORD.unpack_from(tail, offset)
            if offset + _ZIP_END_RECORD.size + values[-1] == len(tail):
                return offset, values
        search_end = offset


def _parse_zip_directory(archive, *, central_size: int) -> list[dict[str, object]]:
    remaining = central_size
    entries: list[dict[str, object]] = []
    while remaining:
        if remaining < _ZIP_CENTRAL_RECORD.size:
            raise MemoryPortabilityError(
                "backup_archive_invalid",
                "The backup ZIP directory is truncated.",
            )
        header = archive.read(_ZIP_CENTRAL_RECORD.size)
        if len(header) != _ZIP_CENTRAL_RECORD.size:
            raise MemoryPortabilityError(
                "backup_archive_invalid",
                "The backup ZIP directory is truncated.",
            )
        values = _ZIP_CENTRAL_RECORD.unpack(header)
        if values[0] != _ZIP_CENTRAL_SIGNATURE:
            raise MemoryPortabilityError(
                "backup_archive_invalid",
                "The backup ZIP directory contains an invalid entry.",
            )
        (
            _signature,
            _version_made,
            version_needed,
            flags,
            method,
            _modified_time,
            _modified_date,
            crc32,
            compressed_size,
            file_size,
            name_size,
            extra_size,
            comment_size,
            disk_start,
            _internal_attr,
            _external_attr,
            local_offset,
        ) = values
        variable_size = name_size + extra_size + comment_size
        record_size = _ZIP_CENTRAL_RECORD.size + variable_size
        if record_size > remaining:
            raise MemoryPortabilityError(
                "backup_archive_invalid",
                "A backup ZIP directory entry exceeds its bounds.",
            )
        name = archive.read(name_size)
        extra = archive.read(extra_size)
        archive.seek(comment_size, os.SEEK_CUR)
        remaining -= record_size
        if disk_start != 0:
            raise MemoryPortabilityError(
                "backup_archive_unsupported",
                "Multi-disk ZIP backups are not supported.",
            )
        if flags & ~_ZIP_ALLOWED_FLAGS or method not in _ZIP_ALLOWED_METHODS:
            raise MemoryPortabilityError(
                "backup_archive_unsupported",
                "The backup ZIP uses an unsupported feature.",
            )
        if (
            compressed_size == _ZIP_SENTINEL_32
            or file_size == _ZIP_SENTINEL_32
            or local_offset == _ZIP_SENTINEL_32
            or _zip_extra_contains(extra, 0x0001)
            or version_needed >= 45
        ):
            raise MemoryPortabilityError(
                "backup_zip64_unsupported",
                "ZIP64 backups are not supported by format version 1.",
            )
        entries.append(
            {
                "name": name,
                "flags": flags,
                "method": method,
                "crc32": crc32,
                "compressed_size": compressed_size,
                "file_size": file_size,
                "local_offset": local_offset,
            }
        )
    return entries


def _validate_zip_local_records(
    archive,
    *,
    entries: list[dict[str, object]],
    central_offset: int,
) -> None:
    intervals: list[tuple[int, int]] = []
    for entry in entries:
        local_offset = int(entry["local_offset"])
        if local_offset < 0 or local_offset + _ZIP_LOCAL_RECORD.size > central_offset:
            raise MemoryPortabilityError(
                "backup_archive_invalid",
                "A backup ZIP member has invalid local bounds.",
            )
        archive.seek(local_offset)
        header = archive.read(_ZIP_LOCAL_RECORD.size)
        if len(header) != _ZIP_LOCAL_RECORD.size:
            raise MemoryPortabilityError(
                "backup_archive_invalid",
                "A backup ZIP local record is truncated.",
            )
        values = _ZIP_LOCAL_RECORD.unpack(header)
        if values[0] != _ZIP_LOCAL_SIGNATURE:
            raise MemoryPortabilityError(
                "backup_archive_invalid",
                "A backup ZIP local record is invalid.",
            )
        (
            _signature,
            version_needed,
            flags,
            method,
            _modified_time,
            _modified_date,
            crc32,
            compressed_size,
            file_size,
            name_size,
            extra_size,
        ) = values
        name = archive.read(name_size)
        extra = archive.read(extra_size)
        if (
            version_needed >= 45
            or compressed_size == _ZIP_SENTINEL_32
            or file_size == _ZIP_SENTINEL_32
            or _zip_extra_contains(extra, 0x0001)
        ):
            raise MemoryPortabilityError(
                "backup_zip64_unsupported",
                "ZIP64 backups are not supported by format version 1.",
            )
        if (
            flags != entry["flags"]
            or method != entry["method"]
            or crc32 != entry["crc32"]
            or compressed_size != entry["compressed_size"]
            or file_size != entry["file_size"]
            or name != entry["name"]
        ):
            raise MemoryPortabilityError(
                "backup_archive_invalid",
                "A backup ZIP local record does not match its directory.",
            )
        end = (
            local_offset
            + _ZIP_LOCAL_RECORD.size
            + name_size
            + extra_size
            + int(entry["compressed_size"])
        )
        if end > central_offset:
            raise MemoryPortabilityError(
                "backup_archive_invalid",
                "A backup ZIP member exceeds its local bounds.",
            )
        intervals.append((local_offset, end))
    intervals.sort()
    expected_offset = 0
    for start, end in intervals:
        if start != expected_offset or end < start:
            raise MemoryPortabilityError(
                "backup_archive_invalid",
                "The backup ZIP member layout is inconsistent.",
            )
        expected_offset = end
    if expected_offset != central_offset:
        raise MemoryPortabilityError(
            "backup_archive_invalid",
            "The backup ZIP member layout is inconsistent.",
        )


def _zip_extra_contains(extra: bytes, target_id: int) -> bool:
    offset = 0
    while offset < len(extra):
        if offset + 4 > len(extra):
            raise MemoryPortabilityError(
                "backup_archive_invalid",
                "A backup ZIP extra field is truncated.",
            )
        field_id, field_size = struct.unpack_from("<HH", extra, offset)
        offset += 4
        if offset + field_size > len(extra):
            raise MemoryPortabilityError(
                "backup_archive_invalid",
                "A backup ZIP extra field exceeds its bounds.",
            )
        if field_id == target_id:
            return True
        offset += field_size
    return False


def _validate_member_names(infos: list[zipfile.ZipInfo]) -> dict[str, zipfile.ZipInfo]:
    by_name: dict[str, zipfile.ZipInfo] = {}
    folded_names: set[str] = set()
    file_paths: set[str] = set()
    total_bytes = 0
    for info in infos:
        name = str(info.filename)
        path = PurePosixPath(name)
        try:
            encoded_name = name.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise MemoryPortabilityError(
                "backup_member_invalid",
                "The backup contains a non-portable archive path.",
            ) from exc
        parts = path.parts
        mode = info.external_attr >> 16
        if (
            not name
            or "\\" in name
            or "\x00" in name
            or any(ord(character) < 32 for character in name)
            or path.is_absolute()
            or path.as_posix() != name
            or any(part in {"", ".", ".."} for part in parts)
            or len(encoded_name) > MAX_BACKUP_PATH_BYTES
            or len(parts) > MAX_BACKUP_PATH_DEPTH
            or any(len(part.encode("utf-8")) > MAX_BACKUP_COMPONENT_BYTES for part in parts)
            or info.is_dir()
            or (mode and stat.S_IFMT(mode) != stat.S_IFREG)
            or info.flag_bits & ~_ZIP_ALLOWED_FLAGS
            or info.compress_type not in _ZIP_ALLOWED_METHODS
            or info.file_size < 0
            or info.file_size > MAX_BACKUP_MEMBER_BYTES
            or info.compress_size < 0
        ):
            raise MemoryPortabilityError(
                "backup_member_invalid",
                "The backup contains an unsafe archive member.",
            )
        if info.file_size > 0 and info.compress_size == 0:
            raise MemoryPortabilityError(
                "backup_compression_invalid",
                "A backup member has invalid compressed bounds.",
            )
        if (
            info.file_size > 1024 * 1024
            and info.file_size > info.compress_size * MAX_COMPRESSION_RATIO
        ):
            raise MemoryPortabilityError(
                "backup_compression_invalid",
                "A backup member has an unsafe compression ratio.",
            )
        folded = name.casefold()
        if name in by_name or folded in folded_names:
            raise MemoryPortabilityError(
                "backup_member_duplicate",
                "The backup contains duplicate file paths.",
            )
        for index in range(1, len(parts)):
            if "/".join(parts[:index]).casefold() in file_paths:
                raise MemoryPortabilityError(
                    "backup_member_invalid",
                    "A backup path is nested below another file.",
                )
        if any(existing.startswith(f"{folded}/") for existing in folded_names):
            raise MemoryPortabilityError(
                "backup_member_invalid",
                "A backup file conflicts with an existing path.",
            )
        by_name[name] = info
        folded_names.add(folded)
        file_paths.add(folded)
        total_bytes += info.file_size
        if total_bytes > MAX_BACKUP_UNCOMPRESSED_BYTES + MAX_MANIFEST_BYTES:
            raise MemoryPortabilityError(
                "backup_too_large",
                "The backup expands beyond the supported size.",
            )
    return by_name


def _extract_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    destination: Path,
    expected_bytes: int,
) -> str:
    digest = hashlib.sha256()
    written = 0
    try:
        with (
            archive.open(info, "r") as input_handle,
            _open_private_exclusive(destination) as output_handle,
        ):
            while chunk := input_handle.read(1024 * 1024):
                written += len(chunk)
                if written > expected_bytes:
                    raise MemoryPortabilityError(
                        "backup_size_invalid",
                        "A backup file expanded beyond its declared size.",
                    )
                digest.update(chunk)
                output_handle.write(chunk)
            output_handle.flush()
            os.fsync(output_handle.fileno())
    except MemoryPortabilityError:
        destination.unlink(missing_ok=True)
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        destination.unlink(missing_ok=True)
        raise MemoryPortabilityError(
            "backup_member_invalid",
            "A backup file could not be extracted safely.",
        ) from exc
    if written != expected_bytes:
        destination.unlink(missing_ok=True)
        raise MemoryPortabilityError(
            "backup_size_invalid",
            "A backup file size does not match its manifest.",
        )
    return digest.hexdigest()


def _validate_and_prepare_databases(
    extracted_root: Path,
    manifest: BackupManifest,
) -> str:
    needs_upgrade = False
    database_paths = {
        "l1": extracted_root / "databases" / "l1_events.db",
        "memory_shared": extracted_root / "databases" / "memory.db",
    }
    for target_name, database_path in database_paths.items():
        _validate_database_integrity(database_path)
        try:
            stamped_revision = database_revision(database_path)
        except MemoryPortabilityError as exc:
            raise MemoryPortabilityError(
                "schema_revision_unsupported",
                "The backup was created by an incompatible memory schema.",
            ) from exc
        if stamped_revision != manifest.schema_revisions[target_name]:
            raise MemoryPortabilityError(
                "schema_revision_mismatch",
                "A memory database revision does not match the backup manifest.",
            )
        try:
            validate_migration_revision(target_name, stamped_revision)
            head = migration_head(target_name)
            _validate_schema_against_revision(
                database_path,
                target_name=target_name,
                revision=stamped_revision,
            )
        except MigrationRevisionError as exc:
            raise MemoryPortabilityError(
                "schema_revision_unsupported",
                "The backup was created by an incompatible memory schema.",
            ) from exc
        except MigrationExecutionError as exc:
            raise MemoryPortabilityError(
                "schema_validation_failed",
                "The backup database schema could not be validated safely.",
            ) from exc
        if stamped_revision != head:
            needs_upgrade = True
            try:
                run_upgrade_database(target_name, database_path)
            except MigrationExecutionError as exc:
                raise MemoryPortabilityError(
                    "schema_upgrade_failed",
                    "The backup could not be upgraded safely in private staging.",
                ) from exc
        _validate_database_integrity(database_path)
        try:
            migrated_revision = database_revision(database_path)
        except MemoryPortabilityError as exc:
            raise MemoryPortabilityError(
                "schema_upgrade_failed",
                "The staged memory database did not reach the installed schema head.",
            ) from exc
        if migrated_revision != head:
            raise MemoryPortabilityError(
                "schema_upgrade_failed",
                "The staged memory database did not reach the installed schema head.",
            )
        _validate_schema_against_revision(
            database_path,
            target_name=target_name,
            revision=head,
        )

    _validate_excluded_memory_rows(database_paths)
    _invalidate_embedding_indexes(database_paths)
    _rebuild_full_text_indexes(database_paths)
    for target_name, database_path in database_paths.items():
        _validate_database_integrity(database_path)
        _validate_schema_against_revision(
            database_path,
            target_name=target_name,
            revision=migration_head(target_name),
        )
    return "upgrade_required" if needs_upgrade else "compatible"


def _validate_schema_against_revision(
    database_path: Path,
    *,
    target_name: str,
    revision: str,
) -> None:
    reference_path = database_path.parent / f".schema-{target_name}-{uuid.uuid4().hex}.db"
    try:
        run_upgrade_database(target_name, reference_path, revision=revision)
        with _open_sqlite(reference_path) as reference, _open_sqlite(database_path) as candidate:
            allowed_dynamic = _validate_dynamic_vector_schema(candidate, target_name=target_name)
            expected = _schema_inventory(reference)
            actual = _schema_inventory(candidate)
            unexpected = set(actual) - set(expected) - allowed_dynamic
            missing = set(expected) - set(actual)
            if unexpected or missing:
                raise MemoryPortabilityError(
                    "database_schema_invalid",
                    "A memory database contains an unsupported schema.",
                )
            for key, expected_signature in expected.items():
                if actual.get(key) != expected_signature:
                    raise MemoryPortabilityError(
                        "database_schema_invalid",
                        "A memory database contains an unsupported schema.",
                    )
    except MemoryPortabilityError:
        raise
    except MigrationExecutionError as exc:
        raise MemoryPortabilityError(
            "schema_validation_failed",
            "The backup database schema could not be validated safely.",
        ) from exc
    except sqlite3.DatabaseError as exc:
        raise MemoryPortabilityError(
            "database_schema_invalid",
            "A memory database contains an unsupported schema.",
        ) from exc
    finally:
        for suffix in ("", "-shm", "-wal"):
            Path(f"{reference_path}{suffix}").unlink(missing_ok=True)


def _schema_inventory(connection: sqlite3.Connection) -> dict[tuple[str, str], tuple[str, str]]:
    inventory: dict[tuple[str, str], tuple[str, str]] = {}
    rows = connection.execute(
        """
        SELECT type, name, tbl_name, sql
        FROM sqlite_master
        WHERE name NOT LIKE 'sqlite_autoindex_%'
          AND name NOT IN ('sqlite_sequence', 'sqlite_stat1', 'sqlite_stat4')
        ORDER BY type, name
        """
    ).fetchall()
    for row in rows:
        object_type = str(row[0])
        name = str(row[1])
        table_name = str(row[2])
        sql = _normalize_schema_sql(str(row[3] or ""))
        inventory[(object_type, name)] = (table_name, sql)
    return inventory


def _normalize_schema_sql(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def _validate_dynamic_vector_schema(
    connection: sqlite3.Connection,
    *,
    target_name: str,
) -> set[tuple[str, str]]:
    allowed: set[tuple[str, str]] = set()
    objects = {
        (str(row[0]), str(row[1])): (str(row[2]), str(row[3] or ""))
        for row in connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master"
        ).fetchall()
    }
    for registry, entity_column, vec_prefix, partitioned in _VECTOR_SPECS[target_name]:
        registry_key = ("table", registry)
        index_name = f"idx_{registry}_model"
        root_pattern = re.compile(rf"{re.escape(vec_prefix)}_[0-9a-f]{{12}}")
        root_names = {
            name
            for (object_type, name), (_table, sql) in objects.items()
            if object_type == "table"
            and root_pattern.fullmatch(name)
            and _normalize_schema_sql(sql).startswith("create virtual table")
        }
        prefixed_names = {
            name for (_object_type, name) in objects if name.startswith(f"{vec_prefix}_")
        }
        expected_prefixed = set(root_names)
        for root_name in root_names:
            expected_prefixed.update(f"{root_name}{suffix}" for suffix in _VECTOR_SHADOW_SUFFIXES)
        if prefixed_names != expected_prefixed:
            raise MemoryPortabilityError(
                "database_schema_invalid",
                "A memory vector index contains an unsupported schema.",
            )
        if registry_key not in objects:
            if root_names:
                raise MemoryPortabilityError(
                    "database_schema_invalid",
                    "A memory vector index is missing its registry.",
                )
            continue

        columns = tuple(
            str(row[1]) for row in connection.execute(f'PRAGMA table_info("{registry}")')
        )
        expected_columns = tuple(
            entity_column if column == "entity_column" else column
            for column in _VECTOR_REGISTRY_COLUMNS
        )
        if columns != expected_columns:
            raise MemoryPortabilityError(
                "database_schema_invalid",
                "A memory vector registry contains an unsupported schema.",
            )
        if ("index", index_name) not in objects:
            raise MemoryPortabilityError(
                "database_schema_invalid",
                "A memory vector registry is missing its model index.",
            )
        index_columns = tuple(
            str(row[2]) for row in connection.execute(f'PRAGMA index_info("{index_name}")')
        )
        if index_columns != ("embedding_model",):
            raise MemoryPortabilityError(
                "database_schema_invalid",
                "A memory vector registry contains an unsupported index.",
            )
        registry_rows = connection.execute(
            f'SELECT embedding_dim, vec_table FROM "{registry}"'
        ).fetchall()
        registered_tables = {str(row[1]) for row in registry_rows}
        if not registered_tables.issubset(root_names):
            raise MemoryPortabilityError(
                "database_schema_invalid",
                "A memory vector registry references an invalid vector table.",
            )
        for root_name in root_names:
            sql = _normalize_schema_sql(objects[("table", root_name)][1])
            match = re.fullmatch(
                rf'create virtual table "?{re.escape(root_name)}"? using vec0\('
                rf"embedding float\[(?P<dimension>[0-9]{{1,5}})\]"
                rf"(?P<partition>, user_id text partition key)?\)",
                sql,
            )
            if match is None:
                raise MemoryPortabilityError(
                    "database_schema_invalid",
                    "A memory vector table contains an unsupported schema.",
                )
            dimension = int(match.group("dimension"))
            if dimension < 1 or dimension > _MAX_VECTOR_DIMENSION:
                raise MemoryPortabilityError(
                    "database_schema_invalid",
                    "A memory vector table contains an unsupported dimension.",
                )
            has_partition = match.group("partition") is not None
            if has_partition is not partitioned:
                raise MemoryPortabilityError(
                    "database_schema_invalid",
                    "A memory vector table contains an unsupported partition schema.",
                )
            if any(str(row[1]) == root_name and int(row[0]) != dimension for row in registry_rows):
                raise MemoryPortabilityError(
                    "database_schema_invalid",
                    "A memory vector registry dimension does not match its table.",
                )
            for suffix, expected_shadow_columns in _VECTOR_SHADOW_COLUMNS.items():
                shadow_name = f"{root_name}{suffix}"
                shadow_columns = tuple(
                    str(row[1]) for row in connection.execute(f'PRAGMA table_info("{shadow_name}")')
                )
                if shadow_columns != expected_shadow_columns:
                    raise MemoryPortabilityError(
                        "database_schema_invalid",
                        "A memory vector table contains an unsupported shadow schema.",
                    )
        allowed.add(registry_key)
        allowed.add(("index", index_name))
        for name in expected_prefixed:
            allowed.add(("table", name))
    return allowed


def _validate_database_integrity(path: Path) -> None:
    try:
        with _open_sqlite(path) as connection:
            integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
            foreign_key_row = connection.execute("PRAGMA foreign_key_check").fetchone()
    except (OSError, sqlite3.DatabaseError) as exc:
        raise MemoryPortabilityError(
            "database_invalid",
            "A database in the backup is invalid or corrupt.",
        ) from exc
    if integrity_rows != [("ok",)] or foreign_key_row is not None:
        raise MemoryPortabilityError(
            "database_invalid",
            "A database in the backup failed its integrity checks.",
        )


def _open_sqlite(path: Path) -> sqlite3.Connection:
    absolute = Path(path).resolve(strict=True)
    connection = sqlite3.connect(absolute)
    try:
        connection.enable_load_extension(True)
        connection.load_extension(sqlite_vec.loadable_path())
    finally:
        connection.enable_load_extension(False)
    return connection


def _validate_excluded_memory_rows(database_paths: dict[str, Path]) -> None:
    checks = {
        "l1": ("chat_sessions",),
    }
    try:
        for target_name, tables in checks.items():
            with _open_sqlite(database_paths[target_name]) as connection:
                existing = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                for table in tables:
                    if table in existing:
                        row = connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
                        if row is None or int(row[0]) != 0:
                            raise MemoryPortabilityError(
                                "backup_scope_invalid",
                                "The backup contains excluded chat records.",
                            )
        _validate_redacted_history_imports(database_paths["memory_shared"])
    except MemoryPortabilityError:
        raise
    except sqlite3.DatabaseError as exc:
        raise MemoryPortabilityError(
            "database_schema_invalid",
            "A required memory table could not be validated.",
        ) from exc


def _validate_redacted_history_imports(memory_path: Path) -> None:
    with _open_sqlite(memory_path) as connection:
        sensitive = connection.execute(
            """
            SELECT 1
            FROM history_import_source_records
            WHERE content != '' OR source_name != '' OR speaker_name != ''
               OR source_id NOT LIKE 'backup-source-%'
               OR (speaker_id != '' AND speaker_id NOT LIKE 'backup-participant-%')
            LIMIT 1
            """
        ).fetchone()
        if sensitive is not None:
            raise MemoryPortabilityError(
                "backup_scope_invalid",
                "The backup contains raw history-import provenance.",
            )
        job_rows = connection.execute(
            """
            SELECT status, source_ids_json, included_source_ids_json,
                   self_participant_ids_json, importer_plugin_id, importer_id,
                   importer_format_version
            FROM history_import_jobs
            WHERE deleted_at IS NULL
            """
        ).fetchall()
        for row in job_rows:
            if str(row[0]) != "completed" or any(value is not None for value in row[4:7]):
                raise MemoryPortabilityError(
                    "backup_scope_invalid",
                    "The backup contains active history-import execution state.",
                )
            for raw_value, prefix in (
                (row[1], "backup-source-"),
                (row[2], "backup-source-"),
                (row[3], "backup-participant-"),
            ):
                try:
                    values = json.loads(str(raw_value or "[]"))
                except (TypeError, ValueError) as exc:
                    raise MemoryPortabilityError(
                        "backup_scope_invalid",
                        "The backup contains invalid history-import ownership metadata.",
                    ) from exc
                if not isinstance(values, list) or any(
                    not isinstance(value, str) or not value.startswith(prefix) for value in values
                ):
                    raise MemoryPortabilityError(
                        "backup_scope_invalid",
                        "The backup contains invalid history-import ownership metadata.",
                    )


def _invalidate_embedding_indexes(database_paths: dict[str, Path]) -> None:
    l1_path = database_paths["l1"]
    memory_path = database_paths["memory_shared"]
    try:
        with _open_sqlite(l1_path) as connection:
            connection.execute("PRAGMA secure_delete = ON")
            _drop_vector_tables(connection, target_name="l1")
            connection.execute("DELETE FROM l1_event_chunks")
            connection.execute("DELETE FROM embedding_profiles")
            connection.execute(
                """
                UPDATE l1_event_embedding_state
                SET embedding_status = 2, embedding_profile_id = NULL,
                    embedding_chunk_count = 0, last_embedded_at = NULL
                """
            )
            connection.commit()
        with _open_sqlite(memory_path) as connection:
            connection.execute("PRAGMA secure_delete = ON")
            clear_portability_operational_state(connection)
            _drop_vector_tables(connection, target_name="memory_shared")
            connection.execute("DELETE FROM l3_summary_chunks")
            connection.execute("DELETE FROM l4_skill_chunks")
            connection.execute("DELETE FROM embedding_rebuild_job_layers")
            connection.execute("DELETE FROM embedding_rebuild_jobs")
            connection.execute(
                """
                UPDATE entity_catalog
                SET embedding_status = 'pending', embedding_profile_id = NULL,
                    last_embedded_at = NULL
                """
            )
            connection.execute(
                """
                UPDATE knowledge_graph
                SET embedding_status = 'pending', embedding_profile_id = NULL,
                    last_embedded_at = NULL
                """
            )
            connection.execute(
                """
                UPDATE episodes
                SET embedding_status = 'pending', embedding_profile_id = NULL,
                    last_embedded_at = NULL
                """
            )
            connection.execute(
                """
                UPDATE summaries
                SET embedding_status = 'pending', embedding_profile_id = NULL,
                    embedding_chunk_count = 0, last_embedded_at = NULL
                """
            )
            connection.execute(
                """
                UPDATE procedural_skills
                SET embedding_status = 'pending', embedding_profile_id = NULL,
                    embedding_chunk_count = 0, last_embedded_at = NULL
                """
            )
            connection.commit()
    except sqlite3.DatabaseError as exc:
        raise MemoryPortabilityError(
            "index_invalidation_failed",
            "Stale memory indexes could not be invalidated safely.",
        ) from exc


def _drop_vector_tables(connection: sqlite3.Connection, *, target_name: str) -> None:
    allowed = _validate_dynamic_vector_schema(connection, target_name=target_name)
    table_names = {name for object_type, name in allowed if object_type == "table"}
    for registry, _entity_column, vec_prefix, _partitioned in _VECTOR_SPECS[target_name]:
        roots = sorted(
            name
            for name in table_names
            if re.fullmatch(rf"{re.escape(vec_prefix)}_[0-9a-f]{{12}}", name)
        )
        for table_name in roots:
            connection.execute(f'DROP TABLE "{table_name}"')
        if ("table", registry) in allowed:
            connection.execute(f'DELETE FROM "{registry}"')


def _rebuild_full_text_indexes(database_paths: dict[str, Path]) -> None:
    try:
        with _open_sqlite(database_paths["l1"]) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("DELETE FROM l1_events_fts")
            rows = connection.execute(
                """
                SELECT event_id, content, author_type, content_type
                FROM fact_events
                WHERE deleted_at IS NULL
                ORDER BY id
                """
            ).fetchall()
            connection.executemany(
                "INSERT INTO l1_events_fts(event_id, content) VALUES (?, ?)",
                [
                    (
                        str(row["event_id"]),
                        tokenize_for_fts(
                            _compose_l1_search_text(
                                str(row["content"] or ""),
                                author_type_label(row["author_type"]),
                                content_type_label(row["content_type"]),
                            )
                        ),
                    )
                    for row in rows
                ],
            )
            _require_fts_count(connection, "l1_events_fts", len(rows))
            connection.commit()
            connection.execute("VACUUM")

        with _open_sqlite(database_paths["memory_shared"]) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("DELETE FROM episodes_fts")
            episode_rows = connection.execute(
                "SELECT episode_id, summary, label, user_label FROM episodes ORDER BY episode_id"
            ).fetchall()
            connection.executemany(
                """
                INSERT INTO episodes_fts(episode_id, summary, label, user_label)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        str(row["episode_id"]),
                        str(row["summary"] or ""),
                        str(row["label"] or ""),
                        str(row["user_label"] or ""),
                    )
                    for row in episode_rows
                ],
            )

            connection.execute("DELETE FROM l3_summaries_fts")
            summary_rows = connection.execute(
                f"SELECT * FROM summaries WHERE {active_summary_predicate()} ORDER BY summary_id"
            ).fetchall()
            connection.executemany(
                "INSERT INTO l3_summaries_fts(summary_id, content) VALUES (?, ?)",
                [l3_fts_backfill_row(row) for row in summary_rows],
            )

            connection.execute("DELETE FROM l4_skills_fts")
            skill_rows = connection.execute(
                f"""
                SELECT skills.skill_id, skills.skill_name,
                       skills.skill_category, skills.optimized_prompt
                FROM procedural_skills AS skills
                WHERE {active_skill_predicate('skills')}
                ORDER BY skills.skill_id
                """
            ).fetchall()
            connection.executemany(
                "INSERT INTO l4_skills_fts(skill_id, content) VALUES (?, ?)",
                [l4_fts_backfill_row(row) for row in skill_rows],
            )
            _require_fts_count(connection, "episodes_fts", len(episode_rows))
            _require_fts_count(connection, "l3_summaries_fts", len(summary_rows))
            _require_fts_count(connection, "l4_skills_fts", len(skill_rows))
            connection.commit()
            connection.execute("VACUUM")
    except MemoryPortabilityError:
        raise
    except (TypeError, ValueError, sqlite3.DatabaseError) as exc:
        raise MemoryPortabilityError(
            "index_rebuild_failed",
            "Memory full-text indexes could not be rebuilt safely.",
        ) from exc


def _compose_l1_search_text(content: str, author_type: str, content_type: str) -> str:
    text = str(content or "").strip()
    labels = " ".join(
        part for part in (str(author_type or "").strip(), str(content_type or "").strip()) if part
    )
    if text and labels:
        return f"{text} {labels}"
    return text or labels


def _require_fts_count(connection: sqlite3.Connection, table: str, expected: int) -> None:
    row = connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
    if row is None or int(row[0]) != expected:
        raise MemoryPortabilityError(
            "index_rebuild_failed",
            "A memory full-text index did not rebuild completely.",
        )


def _validate_archive_databases(extracted_root: Path, manifest: BackupManifest) -> list[Path]:
    archive_records = [record for record in manifest.files if record.purpose == "archive"]
    paths: list[Path] = []
    for record in archive_records:
        path = extracted_root.joinpath(*PurePosixPath(record.path).parts)
        _validate_database_integrity(path)
        try:
            with _open_sqlite(path) as connection:
                objects = {
                    (str(row[0]), str(row[1]))
                    for row in connection.execute(
                        """
                        SELECT type, name
                        FROM sqlite_master
                        WHERE name NOT LIKE 'sqlite_autoindex_%'
                          AND name NOT IN ('sqlite_sequence', 'sqlite_stat1', 'sqlite_stat4')
                        """
                    ).fetchall()
                }
                tables = {name for object_type, name in objects if object_type == "table"}
                if not tables or not tables.issubset(_ARCHIVE_SCHEMA_SQL):
                    raise MemoryPortabilityError(
                        "archive_schema_invalid",
                        "A memory archive has an unsupported schema.",
                    )
                with sqlite3.connect(":memory:") as reference:
                    for table in sorted(tables):
                        reference.executescript(";".join(_ARCHIVE_SCHEMA_SQL[table]))
                    expected_signature = _archive_schema_signature(reference, tables)
                if _archive_schema_signature(connection, tables) != expected_signature:
                    raise MemoryPortabilityError(
                        "archive_schema_invalid",
                        "A memory archive has an unsupported schema.",
                    )
        except MemoryPortabilityError:
            raise
        except sqlite3.DatabaseError as exc:
            raise MemoryPortabilityError(
                "archive_schema_invalid",
                "A memory archive has an unsupported schema.",
            ) from exc
        paths.append(path)
    return paths


def _archive_schema_signature(
    connection: sqlite3.Connection,
    tables: set[str],
) -> tuple[object, ...]:
    """Return the complete persistent schema contract for production archives."""

    master_objects = tuple(
        (
            str(row[0]),
            str(row[1]),
            str(row[2]),
            _normalize_schema_sql(str(row[3] or "")),
        )
        for row in connection.execute(
            """
            SELECT type, name, tbl_name, sql
            FROM sqlite_master
            WHERE name NOT LIKE 'sqlite_autoindex_%'
              AND name NOT IN ('sqlite_sequence', 'sqlite_stat1', 'sqlite_stat4')
            ORDER BY type, name
            """
        ).fetchall()
    )
    table_signatures: list[tuple[object, ...]] = []
    for table in sorted(tables):
        table_info = tuple(
            (
                int(row[0]),
                str(row[1]),
                str(row[2]),
                int(row[3]),
                None if row[4] is None else str(row[4]),
                int(row[5]),
            )
            for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
        )
        index_list = tuple(
            sorted(
                (
                    str(row[1]),
                    int(row[2]),
                    str(row[3]),
                    int(row[4]),
                )
                for row in connection.execute(f'PRAGMA index_list("{table}")').fetchall()
            )
        )
        index_details = tuple(
            (
                index_name,
                tuple(
                    (
                        int(row[0]),
                        int(row[1]),
                        None if row[2] is None else str(row[2]),
                        int(row[3]),
                        None if row[4] is None else str(row[4]),
                        int(row[5]),
                    )
                    for row in connection.execute(f'PRAGMA index_xinfo("{index_name}")').fetchall()
                ),
            )
            for index_name, _unique, _origin, _partial in index_list
        )
        table_signatures.append((table, table_info, index_list, index_details))
    return master_objects, tuple(table_signatures)


def _validate_manual_assets(extracted_root: Path, manifest: BackupManifest) -> int:
    asset_records = {
        record.path: record for record in manifest.files if record.purpose == "manual_entry_asset"
    }
    expected_paths = referenced_manual_asset_archive_paths(
        extracted_root / "databases" / "memory.db"
    )
    if set(asset_records) != expected_paths:
        raise MemoryPortabilityError(
            "backup_assets_invalid",
            "The managed memory assets do not match visible database references.",
        )
    for archive_path, record in asset_records.items():
        path = extracted_root.joinpath(*PurePosixPath(archive_path).parts)
        try:
            details = path.lstat()
        except OSError as exc:
            raise MemoryPortabilityError(
                "backup_asset_invalid",
                "A managed memory asset is unavailable.",
            ) from exc
        if (
            stat.S_ISLNK(details.st_mode)
            or not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1
            or details.st_size > MAX_UPLOAD_BYTES
            or details.st_size != record.size_bytes
            or sha256_file(path) != record.sha256
        ):
            raise MemoryPortabilityError(
                "backup_asset_invalid",
                "A managed memory asset failed validation.",
            )
    return len(asset_records)


def _build_staged_inventory(
    extracted_root: Path,
    manifest: BackupManifest,
) -> list[BackupFileRecord]:
    records: list[BackupFileRecord] = []
    for source_record in sorted(manifest.files, key=lambda item: item.path):
        path = extracted_root.joinpath(*PurePosixPath(source_record.path).parts)
        try:
            details = path.lstat()
        except OSError as exc:
            raise MemoryPortabilityError(
                "candidate_invalid",
                "A staged restore file is unavailable.",
            ) from exc
        if (
            stat.S_ISLNK(details.st_mode)
            or not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1
            or not _has_private_permissions(details)
        ):
            raise MemoryPortabilityError(
                "candidate_invalid",
                "A staged restore file is not a private regular file.",
            )
        records.append(
            BackupFileRecord(
                path=source_record.path,
                purpose=source_record.purpose,
                size_bytes=details.st_size,
                record_count=snapshot_file_record_count(
                    path,
                    source_record.purpose,
                ),
                sha256=sha256_file(path),
            )
        )
    return records


def _validate_file_record_counts(extracted_root: Path, manifest: BackupManifest) -> None:
    for record in manifest.files:
        path = extracted_root.joinpath(*PurePosixPath(record.path).parts)
        actual = snapshot_file_record_count(path, record.purpose)
        if actual != record.record_count:
            raise MemoryPortabilityError(
                "backup_record_count_invalid",
                "A backup file record count does not match its validated contents.",
            )


def _verify_staged_inventory(
    extracted_root: Path,
    records: list[BackupFileRecord],
) -> None:
    try:
        _verify_staged_inventory_unchecked(extracted_root, records)
    except MemoryPortabilityError:
        raise
    except OSError as exc:
        raise MemoryPortabilityError(
            "candidate_changed",
            "The restore candidate files changed after inspection.",
        ) from exc


def _verify_staged_inventory_unchecked(
    extracted_root: Path,
    records: list[BackupFileRecord],
) -> None:
    try:
        root_details = extracted_root.lstat()
    except OSError as exc:
        raise MemoryPortabilityError(
            "candidate_changed",
            "The restore candidate files changed after inspection.",
        ) from exc
    if (
        stat.S_ISLNK(root_details.st_mode)
        or not stat.S_ISDIR(root_details.st_mode)
        or not _has_private_permissions(root_details)
    ):
        raise MemoryPortabilityError(
            "candidate_changed",
            "The restore candidate files changed after inspection.",
        )
    expected = {record.path: record for record in records}
    expected_directories = {
        parent.as_posix()
        for archive_path in expected
        for parent in PurePosixPath(archive_path).parents
        if parent.as_posix() != "."
    }
    actual: set[str] = set()
    actual_directories: set[str] = set()
    for directory, directory_names, file_names in os.walk(extracted_root, followlinks=False):
        directory_path = Path(directory)
        for name in directory_names:
            child = directory_path / name
            details = child.lstat()
            if (
                stat.S_ISLNK(details.st_mode)
                or not stat.S_ISDIR(details.st_mode)
                or not _has_private_permissions(details)
            ):
                raise MemoryPortabilityError(
                    "candidate_changed",
                    "The restore candidate files changed after inspection.",
                )
            actual_directories.add(child.relative_to(extracted_root).as_posix())
        for name in file_names:
            path = directory_path / name
            details = path.lstat()
            if (
                stat.S_ISLNK(details.st_mode)
                or not stat.S_ISREG(details.st_mode)
                or not _has_private_permissions(details)
            ):
                raise MemoryPortabilityError(
                    "candidate_changed",
                    "The restore candidate files changed after inspection.",
                )
            actual.add(path.relative_to(extracted_root).as_posix())
    if actual != set(expected) or actual_directories != expected_directories:
        raise MemoryPortabilityError(
            "candidate_changed",
            "The restore candidate file inventory changed after inspection.",
        )
    for archive_path, record in expected.items():
        path = extracted_root.joinpath(*PurePosixPath(archive_path).parts)
        details = path.lstat()
        if (
            details.st_nlink != 1
            or details.st_size != record.size_bytes
            or _verified_sha256(path, details) != record.sha256
        ):
            raise MemoryPortabilityError(
                "candidate_changed",
                "A restore candidate file changed after inspection.",
            )


def _candidate_fingerprint(metadata: dict[str, object]) -> str:
    canonical = dict(metadata)
    canonical.pop("fingerprint", None)
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _copy_external_backup(source_path: Path, destination: Path) -> str:
    descriptor, before = _open_external_regular_file(source_path)
    _require_free_space(
        destination.parent,
        before.st_size * 3 + max(before.st_size // 5, 8 * 1024 * 1024),
    )
    digest = hashlib.sha256()
    copied = 0
    try:
        with (
            os.fdopen(descriptor, "rb") as input_handle,
            _open_private_exclusive(destination) as output_handle,
        ):
            while chunk := input_handle.read(1024 * 1024):
                copied += len(chunk)
                if copied > MAX_BACKUP_CONTAINER_BYTES:
                    raise MemoryPortabilityError(
                        "backup_too_large",
                        "The selected backup exceeds the supported size.",
                    )
                digest.update(chunk)
                output_handle.write(chunk)
            output_handle.flush()
            os.fsync(output_handle.fileno())
            after = os.fstat(input_handle.fileno())
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    if (
        copied != before.st_size
        or after.st_dev != before.st_dev
        or after.st_ino != before.st_ino
        or after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
    ):
        destination.unlink(missing_ok=True)
        raise MemoryPortabilityError(
            "backup_changed",
            "The selected backup changed while it was being inspected.",
        )
    return digest.hexdigest()


def _copy_private_file(source: Path, destination: Path, *, max_bytes: int) -> None:
    copied = 0
    with source.open("rb") as input_handle, _open_private_exclusive(destination) as output_handle:
        while chunk := input_handle.read(1024 * 1024):
            copied += len(chunk)
            if copied > max_bytes:
                raise MemoryPortabilityError(
                    "backup_too_large",
                    "The selected backup exceeds the supported size.",
                )
            output_handle.write(chunk)
        output_handle.flush()
        os.fsync(output_handle.fileno())


def _open_external_regular_file(path: Path) -> tuple[int, os.stat_result]:
    expanded = Path(path).expanduser()
    try:
        details = expanded.lstat()
        if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
            raise OSError("not a singly linked regular file")
        if details.st_size <= 0 or details.st_size > MAX_BACKUP_CONTAINER_BYTES:
            raise MemoryPortabilityError(
                "backup_too_large",
                "The selected backup is empty or exceeds the supported size.",
            )
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(expanded, flags)
        opened = os.fstat(descriptor)
        if (
            opened.st_dev != details.st_dev
            or opened.st_ino != details.st_ino
            or not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
        ):
            os.close(descriptor)
            raise OSError("file identity changed")
        return descriptor, opened
    except MemoryPortabilityError:
        raise
    except OSError as exc:
        raise MemoryPortabilityError(
            "backup_unreadable",
            "The selected backup is not a readable regular file.",
        ) from exc


def _read_regular_file(path: Path, *, max_bytes: int) -> bytes:
    details = path.lstat()
    if (
        stat.S_ISLNK(details.st_mode)
        or not stat.S_ISREG(details.st_mode)
        or details.st_nlink != 1
        or details.st_size > max_bytes
        or not _has_private_permissions(details)
    ):
        raise OSError("not a bounded regular file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if opened.st_dev != details.st_dev or opened.st_ino != details.st_ino:
            raise OSError("file identity changed")
        chunks: list[bytes] = []
        total = 0
        while chunk := os.read(descriptor, min(1024 * 1024, max_bytes + 1 - total)):
            total += len(chunk)
            if total > max_bytes:
                raise OSError("file exceeds bound")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _verified_sha256(path: Path, expected: os.stat_result) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags)
    digest = hashlib.sha256()
    try:
        before = os.fstat(descriptor)
        if (
            before.st_dev != expected.st_dev
            or before.st_ino != expected.st_ino
            or before.st_size != expected.st_size
            or before.st_nlink != 1
            or not stat.S_ISREG(before.st_mode)
            or not _has_private_permissions(before)
        ):
            raise OSError("file identity changed")
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        after = os.fstat(descriptor)
        if (
            after.st_dev != before.st_dev
            or after.st_ino != before.st_ino
            or after.st_size != before.st_size
            or after.st_mtime_ns != before.st_mtime_ns
        ):
            raise OSError("file changed while hashing")
    finally:
        os.close(descriptor)
    return digest.hexdigest()


def _has_private_permissions(details: os.stat_result) -> bool:
    return os.name == "nt" or stat.S_IMODE(details.st_mode) & 0o077 == 0


def _validate_archive_target(path: Path) -> Path:
    expanded = Path(path).expanduser()
    try:
        unresolved = expanded.lstat()
        if stat.S_ISLNK(unresolved.st_mode) or not stat.S_ISDIR(unresolved.st_mode):
            raise OSError("not a regular directory")
        resolved = expanded.resolve(strict=True)
        details = resolved.lstat()
    except OSError as exc:
        raise MemoryPortabilityError(
            "archive_target_invalid",
            "The configured memory archive directory is unavailable.",
            status_code=500,
        ) from exc
    if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
        raise MemoryPortabilityError(
            "archive_target_invalid",
            "The configured memory archive path is not a regular directory.",
            status_code=500,
        )
    return resolved


def _ensure_private_directory(path: Path) -> None:
    requested = Path(path)
    missing: list[Path] = []
    cursor = requested
    while True:
        try:
            ancestor_details = cursor.lstat()
            break
        except FileNotFoundError:
            missing.append(cursor)
            if cursor.parent == cursor:
                raise MemoryPortabilityError(
                    "candidate_invalid",
                    "A private restore staging directory is invalid.",
                    status_code=500,
                )
            cursor = cursor.parent
        except OSError as exc:
            raise MemoryPortabilityError(
                "candidate_invalid",
                "A private restore staging directory is invalid.",
                status_code=500,
            ) from exc
    if stat.S_ISLNK(ancestor_details.st_mode) or not stat.S_ISDIR(ancestor_details.st_mode):
        raise MemoryPortabilityError(
            "candidate_invalid",
            "A private restore staging directory is invalid.",
            status_code=500,
        )
    for directory in reversed(missing):
        try:
            directory.mkdir(mode=0o700, exist_ok=False)
        except FileExistsError:
            pass
        details = directory.lstat()
        if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
            raise MemoryPortabilityError(
                "candidate_invalid",
                "A private restore staging directory is invalid.",
                status_code=500,
            )
        if os.name != "nt":
            directory.chmod(0o700)
    details = requested.lstat()
    if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
        raise MemoryPortabilityError(
            "candidate_invalid",
            "A private restore staging directory is invalid.",
            status_code=500,
        )
    if os.name != "nt":
        requested.chmod(0o700)


def _parse_candidate_id(candidate_id: str) -> uuid.UUID:
    try:
        parsed_id = uuid.UUID(str(candidate_id))
    except ValueError as exc:
        raise MemoryPortabilityError(
            "candidate_invalid",
            "The restore candidate identifier is invalid.",
        ) from exc
    if parsed_id.version != 4 or str(parsed_id) != str(candidate_id):
        raise MemoryPortabilityError(
            "candidate_invalid",
            "The restore candidate identifier is invalid.",
        )
    return parsed_id


def _parse_utc_timestamp(value: object, *, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"Invalid {label}")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.tzinfo != timezone.utc:
        raise ValueError(f"Invalid {label}")
    return parsed


__all__ = [
    "backup_requires_password",
    "cleanup_expired_candidates",
    "delete_restore_candidate",
    "inspect_memory_backup",
    "load_restore_candidate",
]
