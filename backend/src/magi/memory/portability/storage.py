"""Consistent SQLite snapshots and managed-file collection for portability."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import tempfile
from typing import Any, AsyncIterator, Iterator
from urllib.parse import quote
import uuid

import sqlite_vec

from ...utils.runtime import RuntimePaths
from ..manual_entries.asset_store import MAX_UPLOAD_BYTES
from ..source_event_governance import source_occurrence_visible_predicate
from .errors import MemoryPortabilityError
from .models import SnapshotBundle, SnapshotFile

_ARCHIVE_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}\.db$")
_ASSET_NAME = re.compile(r"^[0-9a-f]{64}\.(?:gif|jpg|png|webp)$")
_BACKUP_EXCLUDED_L1_TABLES = ("chat_sessions",)
PORTABILITY_OPERATIONAL_TABLES = (
    "embedding_rebuild_job_layers",
    "embedding_rebuild_jobs",
    "l2_event_entity_link_outbox",
    "l2_projection_jobs",
    "memory_derivation_jobs",
    "place_geocode_cache",
)
_DISPOSABLE_L0_TABLES = (
    "l0_sessions",
    "l0_attention_items",
    "l0_goal_stack",
    "l0_active_entities",
    "l0_temporary_tactics",
)
_VECTOR_CACHE_SPECS = {
    "l1": (("l1_event_chunk_vectors", "l1_event_vec"),),
    "memory_shared": (
        ("l2_entity_vectors", "l2_entity_vec"),
        ("l2_edge_vectors", "l2_edge_vec"),
        ("l3_summary_chunk_vectors", "l3_summary_chunk_vec"),
        ("l4_skill_chunk_vectors", "l4_skill_chunk_vec"),
    ),
}


async def create_memory_snapshot(
    *,
    runtime_paths: RuntimePaths,
    archive_dir: Path,
    unified_memory: Any | None,
    include_l0: bool,
) -> SnapshotBundle:
    """Create one private cross-database snapshot of the restorable memory scope."""

    root: Path | None = None
    try:
        runtime_paths.memory_portability_dir.mkdir(parents=True, exist_ok=True)
        async with _maintenance_guard(unified_memory):
            if include_l0 and getattr(unified_memory, "l0", None) is not None:
                await unified_memory.l0.checkpoint_all()
            await asyncio.to_thread(
                _require_snapshot_free_space,
                runtime_paths,
                Path(archive_dir).expanduser(),
            )
            root = Path(
                tempfile.mkdtemp(
                    prefix="snapshot-",
                    dir=runtime_paths.memory_portability_dir,
                )
            )
            return await asyncio.to_thread(
                _create_memory_snapshot_sync,
                runtime_paths,
                Path(archive_dir).expanduser(),
                root,
                include_l0,
            )
    except BaseException as exc:
        if root is not None:
            shutil.rmtree(root, ignore_errors=True)
        if _is_no_space_error(exc):
            raise MemoryPortabilityError(
                "insufficient_space",
                "The memory portability directory does not have enough free space.",
            ) from exc
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
            _load_sqlite_vec(connection)
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
        "l0_sessions": _safe_count(memory_path, "l0_sessions"),
        "l0_attention_items": _safe_count(memory_path, "l0_attention_items"),
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


def snapshot_file_record_count(path: Path, purpose: str) -> int:
    """Return the stable semantic record count for one backup data file."""

    if purpose == "l1":
        return _safe_count(path, "fact_events", "deleted_at IS NULL")
    if purpose == "memory":
        return sum(
            (
                _safe_count(path, "l0_sessions"),
                _safe_count(path, "l0_attention_items"),
                _safe_count(path, "entity_catalog"),
                _safe_count(path, "knowledge_graph", "status = 'active'"),
                _safe_count(path, "tom_trait_assertions", "status = 'active'"),
                _safe_count(path, "episodes"),
                _safe_count(path, "experiences"),
                _safe_count(path, "manual_entries", "deleted_at IS NULL"),
                _safe_count(path, "summaries"),
                _safe_count(path, "procedural_skills", "deleted_at IS NULL"),
            )
        )
    if purpose == "archive":
        try:
            with sqlite3.connect(_read_only_sqlite_uri(path), uri=True) as connection:
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
        except sqlite3.DatabaseError as exc:
            raise MemoryPortabilityError(
                "database_schema_invalid",
                "A memory archive could not be counted.",
            ) from exc
        return sum(
            _safe_count(path, table)
            for table in ("archived_l1_events", "archived_l3_summaries")
            if table in tables
        )
    if purpose == "manual_entry_asset":
        return 1
    raise ValueError("Unknown backup file purpose")


def _require_snapshot_free_space(runtime_paths: RuntimePaths, archive_dir: Path) -> None:
    required_bytes = _snapshot_required_bytes(runtime_paths, archive_dir)
    try:
        free_bytes = shutil.disk_usage(runtime_paths.memory_portability_dir).free
    except OSError as exc:
        if exc.errno == errno.ENOSPC:
            raise MemoryPortabilityError(
                "insufficient_space",
                "The memory portability directory does not have enough free space.",
            ) from exc
        raise MemoryPortabilityError(
            "free_space_unknown",
            "Available space could not be checked for memory snapshot staging.",
        ) from exc
    if free_bytes < required_bytes:
        raise MemoryPortabilityError(
            "insufficient_space",
            "The memory portability directory does not have enough free space.",
        )


def _snapshot_required_bytes(runtime_paths: RuntimePaths, archive_dir: Path) -> int:
    l1_bytes = _database_snapshot_bytes(runtime_paths.l1_memory_db_path)
    memory_bytes = _database_snapshot_bytes(runtime_paths.memory_db_path)
    archive_bytes = sum(
        _database_snapshot_bytes(path) for path in _iter_archive_databases(archive_dir)
    )
    referenced_assets = _collect_referenced_asset_paths(
        runtime_paths.memory_db_path,
        runtime_paths.manual_entry_assets_dir,
    )
    asset_bytes = sum(source.stat().st_size for source, _relative_path in referenced_assets)
    return l1_bytes + memory_bytes + archive_bytes + asset_bytes + max(l1_bytes, memory_bytes)


def _database_snapshot_bytes(path: Path) -> int:
    _require_regular_private_source(path, label="memory database")
    main_bytes = path.stat().st_size
    wal_path = path.with_name(f"{path.name}-wal")
    wal_bytes = 0
    if wal_path.exists():
        wal_details = wal_path.lstat()
        if not stat.S_ISREG(wal_details.st_mode):
            raise MemoryPortabilityError(
                "managed_source_invalid",
                "A memory database journal is not a regular file.",
                status_code=500,
            )
        wal_bytes = wal_details.st_size
    try:
        with sqlite3.connect(_read_only_sqlite_uri(path), uri=True) as connection:
            page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
            page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
    except (TypeError, sqlite3.DatabaseError) as exc:
        raise MemoryPortabilityError(
            "snapshot_failed",
            "Memory snapshot space requirements could not be determined.",
            status_code=500,
        ) from exc
    return max(main_bytes + wal_bytes, page_count * page_size)


def _is_no_space_error(exc: BaseException) -> bool:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, OSError) and current.errno == errno.ENOSPC:
            return True
        if isinstance(current, sqlite3.Error) and getattr(
            current, "sqlite_errorcode", None
        ) == getattr(sqlite3, "SQLITE_FULL", 13):
            return True
        current = current.__cause__ or current.__context__
    return False


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

    counts = count_snapshot_records(l1_output, memory_output, archived_outputs)
    counts["manual_entry_assets"] = len(referenced_assets)
    return SnapshotBundle(
        root=root,
        files=snapshot_files,
        schema_revisions={
            "l1": database_revision(l1_output),
            "memory_shared": database_revision(memory_output),
        },
        counts=counts,
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
        _load_sqlite_vec(connection)
        connection.execute("PRAGMA secure_delete = ON")
        for table in _BACKUP_EXCLUDED_L1_TABLES:
            _delete_table_if_present(connection, table)
        _clear_snapshot_embedding_state(connection, target_name="l1")
        connection.commit()
        connection.execute("VACUUM")
    sqlite_quick_check(path)


def _sanitize_memory_snapshot(path: Path, *, include_l0: bool) -> None:
    with sqlite3.connect(path) as connection:
        _load_sqlite_vec(connection)
        connection.execute("PRAGMA secure_delete = ON")
        if not include_l0:
            for table in _DISPOSABLE_L0_TABLES:
                _delete_table_if_present(connection, table)
        clear_portability_operational_state(connection)
        _clear_snapshot_embedding_state(connection, target_name="memory_shared")
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


def clear_portability_operational_state(connection: sqlite3.Connection) -> None:
    """Remove task queues and rebuildable caches excluded from memory backups."""

    for table in PORTABILITY_OPERATIONAL_TABLES:
        _delete_table_if_present(connection, table)


def _clear_snapshot_embedding_state(
    connection: sqlite3.Connection,
    *,
    target_name: str,
) -> None:
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    for registry, vec_prefix in _VECTOR_CACHE_SPECS[target_name]:
        roots = sorted(
            table
            for table in tables
            if re.fullmatch(rf"{re.escape(vec_prefix)}_[0-9a-f]{{12}}", table)
        )
        for table in roots:
            connection.execute(f'DROP TABLE "{table}"')
        if registry in tables:
            connection.execute(f'DELETE FROM "{registry}"')

    if target_name == "l1":
        _delete_table_if_present(connection, "l1_event_chunks")
        _delete_table_if_present(connection, "embedding_profiles")
        connection.execute(
            """
            UPDATE l1_event_embedding_state
            SET embedding_status = 2, embedding_profile_id = NULL,
                embedding_chunk_count = 0, last_embedded_at = NULL
            """
        )
        return

    _delete_table_if_present(connection, "l3_summary_chunks")
    _delete_table_if_present(connection, "l4_skill_chunks")
    for table in ("entity_catalog", "knowledge_graph", "episodes"):
        connection.execute(
            f"""
            UPDATE "{table}"
            SET embedding_status = 'pending', embedding_profile_id = NULL,
                last_embedded_at = NULL
            """
        )
    for table in ("summaries", "procedural_skills"):
        connection.execute(
            f"""
            UPDATE "{table}"
            SET embedding_status = 'pending', embedding_profile_id = NULL,
                embedding_chunk_count = 0, last_embedded_at = NULL
            """
        )


def _redact_history_import_provenance(connection: sqlite3.Connection) -> None:
    """Keep batch-to-event deletion lineage without exporting imported transcripts."""

    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    required = {
        "history_import_jobs",
        "history_import_source_records",
        "history_import_job_records",
    }
    present = required.intersection(tables)
    if not present:
        return
    if present != required:
        raise MemoryPortabilityError(
            "database_schema_invalid",
            "The memory database has an incomplete history-import schema.",
            status_code=500,
        )

    connection.row_factory = sqlite3.Row
    source_rows = connection.execute(
        "SELECT * FROM history_import_source_records ORDER BY source_record_key"
    ).fetchall()
    job_rows = connection.execute("SELECT * FROM history_import_jobs ORDER BY job_id").fetchall()

    source_values = {str(row["source_id"] or "") for row in source_rows}
    participant_values = {
        str(row["speaker_id"]) for row in source_rows if str(row["speaker_id"] or "").strip()
    }
    parsed_jobs: dict[str, tuple[list[str], list[str], list[str]]] = {}
    for row in job_rows:
        source_ids = _parse_history_import_id_list(row["source_ids_json"])
        included_ids = _parse_history_import_id_list(row["included_source_ids_json"])
        participant_ids = _parse_history_import_id_list(row["self_participant_ids_json"])
        parsed_jobs[str(row["job_id"])] = (source_ids, included_ids, participant_ids)
        source_values.update(source_ids)
        source_values.update(included_ids)
        participant_values.update(participant_ids)

    source_ids = _opaque_id_map(source_values, prefix="backup-source")
    participant_ids = _opaque_id_map(participant_values, prefix="backup-participant")
    record_keys = _opaque_id_map(
        {str(row["source_record_key"]) for row in source_rows},
        prefix="backup-record",
    )
    file_fingerprints = _opaque_id_map(
        {str(row["file_fingerprint"] or "") for row in source_rows},
        prefix="backup-file",
    )
    session_keys = _opaque_id_map(
        {
            "\x1f".join(
                (
                    str(row["source_id"] or ""),
                    str(row["parsed_session_key"] or ""),
                    str(row["session_id"] or ""),
                )
            )
            for row in source_rows
        },
        prefix="backup-session",
    )
    message_identities: set[str] = set()
    for row in source_rows:
        identity_prefix = "\x1f".join(
            (str(row["source_id"] or ""), str(row["parsed_session_key"] or ""))
        )
        message_identities.add(f"{identity_prefix}\x1f{str(row['message_key'] or '')}")
        if row["parent_message_key"] is not None:
            message_identities.add(f"{identity_prefix}\x1f{str(row['parent_message_key'] or '')}")
    message_keys = _opaque_id_map(message_identities, prefix="backup-message")

    for row in source_rows:
        old_source_id = str(row["source_id"] or "")
        old_parsed_session = str(row["parsed_session_key"] or "")
        session_identity = "\x1f".join(
            (old_source_id, old_parsed_session, str(row["session_id"] or ""))
        )
        message_identity = (
            f"{old_source_id}\x1f{old_parsed_session}\x1f{str(row['message_key'] or '')}"
        )
        parent_identity = (
            f"{old_source_id}\x1f{old_parsed_session}\x1f{str(row['parent_message_key'] or '')}"
            if row["parent_message_key"] is not None
            else None
        )
        speaker_role = str(row["speaker_role"] or "unknown").strip().lower()
        if speaker_role not in {"assistant", "system", "tool", "unknown", "user"}:
            speaker_role = "unknown"
        connection.execute(
            """
            UPDATE history_import_source_records
            SET source_record_key = ?, file_fingerprint = ?, source_name = '',
                parsed_session_key = ?, session_id = ?, speaker_name = '',
                speaker_role = ?, content = '', timestamp_confidence = 'redacted',
                timestamp_anchor_source = 'redacted', calendar_timezone_id = 'UTC',
                source_id = ?, source_kind = 'restored_memory', speaker_id = ?,
                message_key = ?, parent_message_key = ?
            WHERE source_record_key = ?
            """,
            (
                record_keys[str(row["source_record_key"])],
                file_fingerprints[str(row["file_fingerprint"] or "")],
                session_keys[session_identity],
                session_keys[session_identity],
                speaker_role,
                source_ids[old_source_id],
                participant_ids.get(str(row["speaker_id"] or ""), ""),
                message_keys[message_identity],
                message_keys[parent_identity] if parent_identity is not None else None,
                str(row["source_record_key"]),
            ),
        )

    for old_key, new_key in record_keys.items():
        connection.execute(
            "UPDATE history_import_job_records SET source_record_key = ? WHERE source_record_key = ?",
            (new_key, old_key),
        )
    connection.execute("""
        UPDATE history_import_job_records
        SET raw_state = CASE WHEN raw_state = 'stored' THEN 'stored' ELSE 'skipped' END,
            projection_state = CASE
                WHEN raw_state = 'stored' AND projection_state = 'projected'
                    THEN 'projected'
                ELSE 'skipped'
            END
        """)

    for row in job_rows:
        job_id = str(row["job_id"])
        job_sources, included_sources, self_participants = parsed_jobs[job_id]
        connection.execute(
            """
            UPDATE history_import_jobs
            SET source_type = 'restored_memory', source_fingerprint = ?,
                source_ids_json = ?, included_source_ids_json = ?,
                detected_kind = 'restored_memory', status = 'completed',
                self_participant_ids_json = ?,
                warnings_json = '["restore_provenance_only"]', quick_ready = 0,
                error_text = NULL, importer_plugin_id = NULL, importer_id = NULL,
                importer_format_version = NULL
            WHERE job_id = ?
            """,
            (
                f"backup-job-{uuid.uuid4().hex}",
                json.dumps([source_ids[value] for value in job_sources], separators=(",", ":")),
                json.dumps(
                    [source_ids[value] for value in included_sources],
                    separators=(",", ":"),
                ),
                json.dumps(
                    [participant_ids[value] for value in self_participants],
                    separators=(",", ":"),
                ),
                job_id,
            ),
        )

    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise MemoryPortabilityError(
            "database_invalid",
            "History-import ownership could not be preserved in the memory snapshot.",
            status_code=500,
        )


def _parse_history_import_id_list(value: object) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError) as exc:
        raise MemoryPortabilityError(
            "database_invalid",
            "History-import ownership metadata is invalid.",
            status_code=500,
        ) from exc
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        raise MemoryPortabilityError(
            "database_invalid",
            "History-import ownership metadata is invalid.",
            status_code=500,
        )
    return list(dict.fromkeys(parsed))


def _opaque_id_map(values: set[str], *, prefix: str) -> dict[str, str]:
    return {value: f"{prefix}-{uuid.uuid4().hex}" for value in sorted(values)}


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
    archive_paths = referenced_manual_asset_archive_paths(memory_db_path)
    collected: list[tuple[Path, Path]] = []
    if archive_paths:
        _require_directory(root, label="manual-entry asset directory")
        resolved_root = root.resolve(strict=True)
    for archive_path in sorted(archive_paths):
        relative_path = Path(*PurePosixPath(archive_path).parts[2:])
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
            or not _ASSET_NAME.fullmatch(source.name)
            or sha256_file(source) != source.name[:64]
            or source.stat().st_size != source_size
        ):
            raise MemoryPortabilityError(
                "managed_asset_invalid",
                "A managed memory asset failed its content-address check.",
                status_code=500,
            )
        collected.append((source, relative_path))
    return collected


def referenced_manual_asset_archive_paths(memory_db_path: Path) -> set[str]:
    """Return canonical backup paths for every visible managed asset reference."""

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
                except (TypeError, ValueError) as exc:
                    raise MemoryPortabilityError(
                        "database_schema_invalid",
                        "A visible manual entry contains invalid attachment metadata.",
                    ) from exc
                if not isinstance(values, list) or any(
                    not isinstance(value, str) for value in values
                ):
                    raise MemoryPortabilityError(
                        "database_schema_invalid",
                        "A visible manual entry contains invalid attachment metadata.",
                    )
                refs.update(values)
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
    archive_paths: set[str] = set()
    for asset_ref in sorted(refs):
        match = canonical.fullmatch(asset_ref)
        if match is None:
            if asset_ref.startswith("manual-entry-asset://"):
                raise MemoryPortabilityError(
                    "backup_assets_invalid",
                    "A visible managed memory asset reference is invalid.",
                )
            continue
        file_name = f"{match.group('digest')}.{match.group('ext')}"
        archive_paths.add(f"assets/manual_entries/{file_name[:2]}/{file_name}")
    return archive_paths


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
    except sqlite3.DatabaseError as exc:
        raise MemoryPortabilityError(
            "database_schema_invalid",
            "A required memory table could not be counted.",
        ) from exc
    if row is None:
        raise MemoryPortabilityError(
            "database_schema_invalid",
            "A required memory table could not be counted.",
        )
    return int(row[0])


def _read_only_sqlite_uri(path: Path) -> str:
    absolute = str(Path(path).resolve(strict=True))
    return f"file:{quote(absolute, safe='/')}?mode=ro"


def _load_sqlite_vec(connection: sqlite3.Connection) -> None:
    connection.enable_load_extension(True)
    try:
        connection.load_extension(sqlite_vec.loadable_path())
    finally:
        connection.enable_load_extension(False)


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
    "PORTABILITY_OPERATIONAL_TABLES",
    "clear_portability_operational_state",
    "count_snapshot_records",
    "create_memory_snapshot",
    "database_revision",
    "discard_snapshot",
    "referenced_manual_asset_archive_paths",
    "sha256_file",
    "snapshot_file_record_count",
    "sqlite_quick_check",
]
