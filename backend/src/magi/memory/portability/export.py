"""Human-readable, non-restorable memory export packages."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import uuid
import zipfile

from .backup import (
    _magi_version,
    _open_private_exclusive,
    _fsync_directory,
    _fsync_file,
    _require_free_space,
    _require_output_directory,
)
from .errors import MemoryPortabilityError
from .models import EXPORT_FORMAT, EXPORT_FORMAT_VERSION, SnapshotBundle, utc_now_iso

_L1_EXPORT_TABLES = (
    "fact_events",
    "l1_event_payload",
    "l1_event_entities",
    "l1_source_facets",
)
_MEMORY_EXPORT_TABLES = (
    "entity_catalog",
    "entity_aliases",
    "entity_mentions",
    "entity_name_evidence",
    "entity_facets",
    "knowledge_graph",
    "knowledge_graph_versions",
    "tom_trait_assertions",
    "tom_snapshots",
    "l2_grounded_claims",
    "l2_claim_evidence",
    "l2_claim_entity_refs",
    "l2_claim_projection_outcomes",
    "l2_pending_reviews",
    "episodes",
    "episode_events",
    "summaries",
    "summary_event_links",
    "summary_task_links",
    "procedural_skills",
    "l4_execution_traces",
    "l4_skill_event_links",
    "manual_entries",
    "experiences",
    "experience_members",
    "experience_key_events",
    "experience_seeds",
    "experience_seed_evidence",
    "experience_drafts",
    "experience_chapters",
    "daily_mood_aggregate",
    "location_samples",
    "place_labels",
    "user_portrait_projection",
    "memory_corrections",
    "memory_correction_rules",
    "memory_correction_evidence_events",
    "memory_correction_evidence_fail_closed",
    "memory_correction_forget_barriers",
    "memory_correction_revert_blocks",
    "memory_relationship_conflict_effects",
    "memory_claim_evidence_events",
    "memory_forget_claim_rules",
    "memory_forget_evidence_events",
    "memory_forget_operations",
    "memory_forget_operation_events",
    "memory_forget_operation_refs",
    "memory_source_event_tombstones",
    "memory_source_turn_cutoffs",
    "memory_time_range_forget_barriers",
    "memory_projection_blocks",
    "memory_entity_projection_identity_blocks",
    "memory_context_catalog",
    "memory_context_aliases",
    "memory_context_bindings",
    "history_import_jobs",
    "history_import_source_records",
    "history_import_job_records",
    "l0_forgotten_attention_source_refs",
    "l0_forgotten_attention_entities",
)
_L0_EXPORT_TABLES = ("l0_sessions", "l0_attention_items")
_ARCHIVE_EXPORT_TABLES = ("archived_l1_events", "archived_l3_summaries")


def build_readable_export(
    *,
    snapshot: SnapshotBundle,
    output_directory: Path,
    include_l0: bool,
) -> tuple[Path, dict[str, object]]:
    """Write stable JSONL files, a schema manifest, and managed assets."""

    output_directory = _require_output_directory(output_directory)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = output_directory / (f"magi-memory-export-{timestamp}-{uuid.uuid4().hex[:8]}.zip")
    partial_path = output_directory / f".{output_path.name}.partial"
    estimated_bytes = sum(Path(item.source_path).stat().st_size for item in snapshot.files)
    _require_free_space(output_directory, estimated_bytes + 1024 * 1024)
    manifest: dict[str, object] = {
        "format": EXPORT_FORMAT,
        "format_version": EXPORT_FORMAT_VERSION,
        "created_at": utc_now_iso(),
        "magi_version": _magi_version(),
        "restorable": False,
        "includes_l0": bool(include_l0),
        "source_counts": dict(snapshot.counts),
        "files": {},
        "record_contract": {
            "encoding": "UTF-8 JSON Lines",
            "record_type_field": "record_type",
            "schema_version_field": "schema_version",
        },
    }
    try:
        with (
            _open_private_exclusive(partial_path) as output_handle,
            zipfile.ZipFile(
                output_handle,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=6,
                allowZip64=True,
            ) as archive,
        ):
            export_files: dict[str, dict[str, object]] = {}
            l1_path = _snapshot_file(snapshot, "databases/l1_events.db")
            memory_path = _snapshot_file(snapshot, "databases/memory.db")
            for table in _L1_EXPORT_TABLES:
                archive_path = f"l1/{table}.jsonl"
                export_files[archive_path] = _write_table_jsonl(
                    archive,
                    l1_path,
                    table,
                    archive_path,
                )
            memory_tables = list(_MEMORY_EXPORT_TABLES)
            if include_l0:
                memory_tables.extend(_L0_EXPORT_TABLES)
            for table in memory_tables:
                archive_path = f"memory/{table}.jsonl"
                export_files[archive_path] = _write_table_jsonl(
                    archive,
                    memory_path,
                    table,
                    archive_path,
                )
            for item in snapshot.files:
                if item.purpose == "archive":
                    date = Path(item.archive_path).stem
                    for table in _ARCHIVE_EXPORT_TABLES:
                        archive_path = f"archives/{date}/{table}.jsonl"
                        export_files[archive_path] = _write_table_jsonl(
                            archive,
                            Path(item.source_path),
                            table,
                            archive_path,
                            extra={"archive_date": date},
                        )
                elif item.purpose == "manual_entry_asset":
                    _write_asset(archive, item.archive_path, Path(item.source_path))
            manifest["files"] = export_files
            _write_text(
                archive,
                "schema.json",
                json.dumps(export_files, ensure_ascii=False, indent=2, sort_keys=True),
            )
            _write_text(archive, "README.txt", _export_readme(include_l0))
            _write_text(
                archive,
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            )
        partial_path.chmod(0o600)
        _fsync_file(partial_path)
        os.replace(partial_path, output_path)
        _fsync_directory(output_directory)
        return output_path, manifest
    except MemoryPortabilityError:
        partial_path.unlink(missing_ok=True)
        raise
    except (OSError, sqlite3.DatabaseError, zipfile.BadZipFile) as exc:
        partial_path.unlink(missing_ok=True)
        raise MemoryPortabilityError(
            "export_write_failed",
            "The readable memory export could not be created.",
            status_code=500,
        ) from exc


def _write_table_jsonl(
    archive: zipfile.ZipFile,
    database_path: Path,
    table: str,
    archive_path: str,
    *,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    if not re.fullmatch(r"[a-z0-9_]+", table):
        raise ValueError("Unsafe SQLite table name")
    with sqlite3.connect(f"file:{database_path}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        if exists is None:
            return {"record_count": 0, "fields": []}
        columns = [
            {"name": str(row[1]), "sqlite_type": str(row[2] or "")}
            for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
        ]
        cursor = connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid')
        info = zipfile.ZipInfo(archive_path)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100600 << 16
        count = 0
        with archive.open(info, "w", force_zip64=True) as handle:
            for row in cursor:
                payload = {
                    "record_type": table,
                    "schema_version": 1,
                    **{key: _json_value(row[key]) for key in row.keys()},
                }
                if extra:
                    payload = {**extra, **payload}
                handle.write(
                    (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
                )
                count += 1
        return {
            "record_count": count,
            "fields": [
                {"name": "record_type", "type": "string"},
                {"name": "schema_version", "type": "integer"},
                *columns,
            ],
        }


def _json_value(value: object) -> object:
    if isinstance(value, bytes):
        return {"encoding": "base64", "data": base64.b64encode(value).decode("ascii")}
    return value


def _snapshot_file(snapshot: SnapshotBundle, archive_path: str) -> Path:
    for item in snapshot.files:
        if item.archive_path == archive_path:
            return Path(item.source_path)
    raise MemoryPortabilityError(
        "snapshot_incomplete",
        "The consistent snapshot is missing a required database.",
        status_code=500,
    )


def _write_asset(archive: zipfile.ZipFile, archive_path: str, source: Path) -> None:
    info = zipfile.ZipInfo(archive_path)
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = 0o100600 << 16
    with source.open("rb") as input_handle, archive.open(info, "w", force_zip64=True) as handle:
        shutil.copyfileobj(input_handle, handle, length=1024 * 1024)


def _write_text(archive: zipfile.ZipFile, archive_path: str, content: str) -> None:
    info = zipfile.ZipInfo(archive_path)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100600 << 16
    archive.writestr(info, content.encode("utf-8"))


def _export_readme(include_l0: bool) -> str:
    l0_note = (
        "L0 short-term attention is included because it was explicitly requested."
        if include_l0
        else "L0 short-term attention is omitted by default because it is disposable chat context."
    )
    return (
        "Magi readable memory export\n\n"
        "Each JSONL file contains one versioned JSON object per line. schema.json lists "
        "the fields and SQLite source types for every file. This export is intended for "
        "reading and data portability; it cannot be restored into Magi. Chat transcripts, "
        "attachments, runtime logs, tasks, models, plugins, credentials, configuration, and "
        "persona state are not included. Original chat evidence referenced by an L1 event may "
        "not exist on another device.\n\n"
        f"{l0_note}\n"
    )


__all__ = ["build_readable_export"]
