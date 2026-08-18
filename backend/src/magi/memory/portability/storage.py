"""Consistent SQLite snapshots and managed-file collection for portability."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tempfile
from typing import Any, AsyncIterator, Iterator
from urllib.parse import quote

from ...utils.runtime import RuntimePaths
from ..manual_entries.asset_store import MAX_UPLOAD_BYTES
from ..source_event_governance import source_occurrence_visible_predicate
from .errors import MemoryPortabilityError
from .models import SnapshotBundle, SnapshotFile

_ARCHIVE_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}\.db$")
_ASSET_NAME = re.compile(r"^[0-9a-f]{64}\.(?:gif|jpg|png|webp)$")
_BACKUP_EXCLUDED_L1_TABLES = ("chat_sessions",)
_DISPOSABLE_L0_TABLES = (
    "l0_sessions",
    "l0_attention_items",
    "l0_goal_stack",
    "l0_active_entities",
    "l0_temporary_tactics",
)


async def create_memory_snapshot(
    *,
    runtime_paths: RuntimePaths,
    archive_dir: Path,
    unified_memory: Any | None,
    include_l0: bool,
) -> SnapshotBundle:
    """Create one private cross-database snapshot of the restorable memory scope."""

    runtime_paths.memory_portability_dir.mkdir(parents=True, exist_ok=True)
    root = Path(
        tempfile.mkdtemp(
            prefix="snapshot-",
            dir=runtime_paths.memory_portability_dir,
        )
    )
    try:
        async with _maintenance_guard(unified_memory):
            if include_l0 and getattr(unified_memory, "l0", None) is not None:
                await unified_memory.l0.checkpoint_all()
            return await asyncio.to_thread(
                _create_memory_snapshot_sync,
                runtime_paths,
                Path(archive_dir).expanduser(),
                root,
                include_l0,
            )
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)
        raise


def discard_snapshot(snapshot: SnapshotBundle) -> None:
    """Remove a private snapshot after packaging or export completes."""

    shutil.rmtree(Path(snapshot.root), ignore_errors=True)


def sha256_file(path: Path) -> str:
    """Return the lowercase SHA-256 digest of one regular file."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def sqlite_quick_check(path: Path) -> None:
    """Reject a file that is not a complete, internally consistent SQLite DB."""

    uri = _read_only_sqlite_uri(path)
    try:
        with sqlite3.connect(uri, uri=True) as connection:
            row = connection.execute("PRAGMA quick_check").fetchone()
    except sqlite3.DatabaseError as exc:
        raise MemoryPortabilityError(
            "database_invalid",
            "A database in the backup is invalid or corrupt.",
        ) from exc
    if row is None or str(row[0]).lower() != "ok":
        raise MemoryPortabilityError(
            "database_invalid",
            "A database in the backup failed its integrity check.",
        )


def database_revision(path: Path) -> str:
    """Read the single Alembic revision recorded in a portable database."""

    uri = _read_only_sqlite_uri(path)
    try:
        with sqlite3.connect(uri, uri=True) as connection:
            rows = connection.execute("SELECT version_num FROM alembic_version").fetchall()
    except sqlite3.DatabaseError as exc:
        raise MemoryPortabilityError(
            "schema_revision_missing",
            "A memory database does not contain a valid schema revision.",
        ) from exc
    if len(rows) != 1 or not str(rows[0][0]).strip():
        raise MemoryPortabilityError(
            "schema_revision_missing",
            "A memory database does not contain a single schema revision.",
        )
    return str(rows[0][0]).strip()


def count_snapshot_records(
    l1_path: Path, memory_path: Path, archive_paths: list[Path]
) -> dict[str, int]:
    """Return user-facing record counts without opening runtime stores."""

    counts = {
        "l1_events": _safe_count(l1_path, "fact_events", "deleted_at IS NULL"),
        "l2_entities": _safe_count(memory_path, "entity_catalog"),
        "l2_relationships": _safe_count(memory_path, "knowledge_graph", "status = 'active'"),
        "l2_assertions": _safe_count(memory_path, "tom_trait_assertions", "status = 'active'"),
        "l2_episodes": _safe_count(memory_path, "episodes"),
        "l2_experiences": _safe_count(memory_path, "experiences"),
        "manual_entries": _safe_count(memory_path, "manual_entries", "deleted_at IS NULL"),
        "l3_summaries": _safe_count(memory_path, "summaries"),
        "l4_procedures": _safe_count(memory_path, "procedural_skills", "deleted_at IS NULL"),
        "archives": len(archive_paths),
    }
    return counts


def _create_memory_snapshot_sync(
    runtime_paths: RuntimePaths,
    archive_dir: Path,
    root: Path,
    include_l0: bool,
) -> SnapshotBundle:
    database_dir = root / "databases"
    archive_output_dir = root / "archives"
    asset_output_dir = root / "assets" / "manual_entries"
    database_dir.mkdir(parents=True, exist_ok=True)
    archive_output_dir.mkdir(parents=True, exist_ok=True)
    asset_output_dir.mkdir(parents=True, exist_ok=True)

    l1_output = database_dir / "l1_events.db"
    memory_output = database_dir / "memory.db"
    _sqlite_online_backup(runtime_paths.l1_memory_db_path, l1_output)
    _sqlite_online_backup(runtime_paths.memory_db_path, memory_output)
    _sanitize_l1_snapshot(l1_output)
    _sanitize_memory_snapshot(memory_output, include_l0=include_l0)

    snapshot_files = [
        SnapshotFile(source_path=l1_output, archive_path="databases/l1_events.db", purpose="l1"),
        SnapshotFile(
            source_path=memory_output, archive_path="databases/memory.db", purpose="memory"
        ),
    ]
    archived_outputs: list[Path] = []
    for source in _iter_archive_databases(archive_dir):
        destination = archive_output_dir / source.name
        _sqlite_online_backup(source, destination)
        archived_outputs.append(destination)
        snapshot_files.append(
            SnapshotFile(
                source_path=destination,
                archive_path=f"archives/{source.name}",
                purpose="archive",
            )
        )

    referenced_assets = _collect_referenced_asset_paths(
        memory_output,
        runtime_paths.manual_entry_assets_dir,
    )
    for source, relative_path in referenced_assets:
        destination = asset_output_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        _copy_regular_file(source, destination, max_bytes=MAX_UPLOAD_BYTES)
        if sha256_file(destination) != destination.name[:64]:
            raise MemoryPortabilityError(
                "managed_asset_changed",
                "A managed memory asset changed while the snapshot was created.",
                status_code=500,
            )
        snapshot_files.append(
            SnapshotFile(
                source_path=destination,
                archive_path=f"assets/manual_entries/{relative_path.as_posix()}",
                purpose="manual_entry_asset",
            )
        )

    return SnapshotBundle(
        root=root,
        files=snapshot_files,
        schema_revisions={
            "l1": database_revision(l1_output),
            "memory_shared": database_revision(memory_output),
        },
        counts=count_snapshot_records(l1_output, memory_output, archived_outputs),
    )


def _sqlite_online_backup(source: Path, destination: Path) -> None:
    _require_regular_private_source(source, label="memory database")
    source_uri = _read_only_sqlite_uri(source)
    try:
        with sqlite3.connect(source_uri, uri=True, timeout=30.0) as source_db:
            with sqlite3.connect(destination) as destination_db:
                source_db.backup(destination_db, pages=1024)
                destination_db.commit()
    except sqlite3.DatabaseError as exc:
        raise MemoryPortabilityError(
            "snapshot_failed",
            "A consistent memory database snapshot could not be created.",
            status_code=500,
        ) from exc
    sqlite_quick_check(destination)


def _sanitize_l1_snapshot(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA secure_delete = ON")
        for table in _BACKUP_EXCLUDED_L1_TABLES:
            _delete_table_if_present(connection, table)
        connection.commit()
        connection.execute("VACUUM")
    sqlite_quick_check(path)


def _sanitize_memory_snapshot(path: Path, *, include_l0: bool) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA secure_delete = ON")
        if not include_l0:
            for table in _DISPOSABLE_L0_TABLES:
                _delete_table_if_present(connection, table)
        _redact_history_import_provenance(connection)
        connection.commit()
        connection.execute("VACUUM")
    sqlite_quick_check(path)


def _delete_table_if_present(connection: sqlite3.Connection, table: str) -> None:
    if not re.fullmatch(r"[a-z0-9_]+", table):
        raise ValueError("Unsafe SQLite table name")
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    if row is not None:
        connection.execute(f'DELETE FROM "{table}"')


def _redact_history_import_provenance(connection: sqlite3.Connection) -> None:
    """Keep batch-to-event deletion lineage without exporting imported transcripts."""

    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    if "history_import_source_records" in tables:
        connection.execute("""
            UPDATE history_import_source_records
            SET file_fingerprint = 'redacted',
                source_name = '',
                parsed_session_key = '',
                session_id = '',
                session_seq = 0,
                speaker_name = '',
                speaker_role = 'unknown',
                content = '',
                timestamp_confidence = 'redacted',
                timestamp_anchor_source = 'redacted',
                calendar_timezone_id = 'UTC',
                source_id = '',
                source_kind = 'redacted',
                speaker_id = '',
                message_key = '',
                parent_message_key = NULL
            """)
    if "history_import_job_records" in tables:
        connection.execute("""
            UPDATE history_import_job_records
            SET raw_state = CASE WHEN raw_state = 'stored' THEN 'stored' ELSE 'skipped' END,
                projection_state = CASE
                    WHEN raw_state = 'stored' AND projection_state = 'projected'
                        THEN 'projected'
                    ELSE 'skipped'
                END
            """)
    if "history_import_jobs" in tables:
        connection.execute("""
            UPDATE history_import_jobs
            SET source_fingerprint = 'redacted:' || job_id,
                source_ids_json = '[]',
                included_source_ids_json = '[]',
                status = 'succeeded',
                self_participant_ids_json = '[]',
                warnings_json = '["restore_provenance_only"]',
                quick_ready = 0,
                error_text = NULL,
                importer_plugin_id = NULL,
                importer_id = NULL,
                importer_format_version = NULL
            """)


def _iter_archive_databases(directory: Path) -> Iterator[Path]:
    if not directory.exists():
        return
    _require_directory(directory, label="memory archive directory")
    for entry in sorted(directory.iterdir(), key=lambda item: item.name):
        if not _ARCHIVE_NAME.fullmatch(entry.name):
            continue
        _require_regular_private_source(entry, label="memory archive")
        yield entry


def _collect_referenced_asset_paths(
    memory_db_path: Path,
    root: Path,
) -> list[tuple[Path, Path]]:
    refs: set[str] = set()
    with sqlite3.connect(_read_only_sqlite_uri(memory_db_path), uri=True) as connection:
        connection.row_factory = sqlite3.Row
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if "manual_entries" in tables:
            visibility = source_occurrence_visible_predicate(
                "entry.event_at",
                barrier_alias="portability_forget_range",
            )
            for row in connection.execute(f"""
                SELECT entry.attachments_json
                FROM manual_entries AS entry
                WHERE entry.deleted_at IS NULL
                  AND entry.delete_requested_at IS NULL
                  AND (
                      entry.pending_l1_event_id IS NULL
                      OR entry.pending_l1_predecessor_event_id IS NULL
                  )
                  AND {visibility}
                """):
                try:
                    values = json.loads(str(row[0] or "[]"))
                except (TypeError, ValueError):
                    values = []
                if isinstance(values, list):
                    refs.update(str(value) for value in values)
        for table, column, where in (
            ("experiences", "user_cover_asset_ref", "status != 'invalidated'"),
            ("experience_drafts", "user_cover_asset_ref", "1 = 1"),
            (
                "timeline_cover_preferences",
                "asset_ref",
                "mode = 'asset' AND source IN ('current_period', 'custom_upload')",
            ),
        ):
            if table not in tables or not _table_has_column(connection, table, column):
                continue
            rows = connection.execute(
                f'SELECT "{column}" FROM "{table}" WHERE {where} AND "{column}" IS NOT NULL'
            ).fetchall()
            refs.update(str(row[0]) for row in rows)

    canonical = re.compile(
        r"manual-entry-asset://(?P<digest>[0-9a-f]{64})\.(?P<ext>gif|jpg|png|webp)"
    )
    collected: list[tuple[Path, Path]] = []
    if refs:
        _require_directory(root, label="manual-entry asset directory")
        resolved_root = root.resolve(strict=True)
    for asset_ref in sorted(refs):
        match = canonical.fullmatch(asset_ref)
        if match is None:
            continue
        file_name = f"{match.group('digest')}.{match.group('ext')}"
        relative_path = Path(file_name[:2]) / file_name
        source = root / relative_path
        if not source.exists():
            raise MemoryPortabilityError(
                "managed_asset_missing",
                "A referenced managed memory asset is missing.",
                status_code=500,
            )
        _require_regular_private_source(source, label="manual-entry asset")
        _require_directory(source.parent, label="manual-entry asset prefix directory")
        try:
            source.resolve(strict=True).relative_to(resolved_root)
        except (OSError, ValueError) as exc:
            raise MemoryPortabilityError(
                "managed_asset_invalid",
                "A managed memory asset resolves outside its owned directory.",
                status_code=500,
            ) from exc
        source_size = source.stat().st_size
        if (
            source_size > MAX_UPLOAD_BYTES
            or not _ASSET_NAME.fullmatch(file_name)
            or sha256_file(source) != file_name[:64]
            or source.stat().st_size != source_size
        ):
            raise MemoryPortabilityError(
                "managed_asset_invalid",
                "A managed memory asset failed its content-address check.",
                status_code=500,
            )
        collected.append((source, relative_path))
    return collected


def _table_has_column(connection: sqlite3.Connection, table: str, column: str) -> bool:
    return any(str(row[1]) == column for row in connection.execute(f'PRAGMA table_info("{table}")'))


def _copy_regular_file(source: Path, destination: Path, *, max_bytes: int) -> None:
    with source.open("rb") as input_handle, destination.open("xb") as output_handle:
        copied = 0
        while chunk := input_handle.read(1024 * 1024):
            copied += len(chunk)
            if copied > max_bytes:
                raise MemoryPortabilityError(
                    "managed_asset_too_large",
                    "A managed memory asset exceeds the supported size.",
                    status_code=500,
                )
            output_handle.write(chunk)
        output_handle.flush()
        os.fsync(output_handle.fileno())


def _require_directory(path: Path, *, label: str) -> None:
    try:
        details = path.lstat()
    except OSError as exc:
        raise MemoryPortabilityError(
            "managed_source_unreadable",
            f"The {label} cannot be inspected.",
            status_code=500,
        ) from exc
    if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
        raise MemoryPortabilityError(
            "managed_source_invalid",
            f"The {label} is not a regular directory.",
            status_code=500,
        )


def _require_regular_private_source(path: Path, *, label: str) -> None:
    try:
        details = path.lstat()
    except OSError as exc:
        raise MemoryPortabilityError(
            "managed_source_unreadable",
            f"The {label} cannot be read.",
            status_code=500,
        ) from exc
    if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
        raise MemoryPortabilityError(
            "managed_source_invalid",
            f"The {label} must be a regular, singly linked file.",
            status_code=500,
        )


def _safe_count(path: Path, table: str, where: str | None = None) -> int:
    if not re.fullmatch(r"[a-z0-9_]+", table):
        raise ValueError("Unsafe SQLite table name")
    query = f'SELECT COUNT(*) FROM "{table}"'
    if where:
        query = f"{query} WHERE {where}"
    try:
        with sqlite3.connect(_read_only_sqlite_uri(path), uri=True) as connection:
            row = connection.execute(query).fetchone()
    except sqlite3.DatabaseError:
        return 0
    return int(row[0]) if row is not None else 0


def _read_only_sqlite_uri(path: Path) -> str:
    absolute = str(Path(path).resolve(strict=True))
    return f"file:{quote(absolute, safe='/')}?mode=ro"


@asynccontextmanager
async def _maintenance_guard(unified_memory: Any | None) -> AsyncIterator[None]:
    if unified_memory is None:
        yield
        return
    guard = getattr(unified_memory, "memory_maintenance_guard", None)
    if not callable(guard):
        raise MemoryPortabilityError(
            "memory_runtime_unavailable",
            "The memory runtime does not support consistent maintenance snapshots.",
            status_code=503,
        )
    async with guard():
        yield


__all__ = [
    "count_snapshot_records",
    "create_memory_snapshot",
    "database_revision",
    "discard_snapshot",
    "sha256_file",
    "sqlite_quick_check",
]
