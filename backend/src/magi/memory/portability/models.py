"""Portable on-disk and API-neutral memory data contracts."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

BACKUP_FORMAT = "magi-memory-backup"
BACKUP_FORMAT_VERSION = 1
EXPORT_FORMAT = "magi-memory-export"
EXPORT_FORMAT_VERSION = 1
MAX_BACKUP_FILE_COUNT = 100_000
MAX_BACKUP_UNCOMPRESSED_BYTES = 64 * 1024 * 1024 * 1024
BACKUP_LIMITATIONS = (
    "l0_runtime_attention_not_restored",
    "chat_records_and_attachments_not_included",
    "source_evidence_may_be_unavailable",
    "raw_history_import_content_redacted",
)


def utc_now_iso() -> str:
    """Return a stable UTC timestamp for manifests and candidate metadata."""

    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class BackupFileRecord(BaseModel):
    """Integrity record for one regular file in a backup payload."""

    model_config = ConfigDict(extra="forbid", strict=True)

    path: str = Field(min_length=1, max_length=1024)
    purpose: Literal["l1", "memory", "archive", "manual_entry_asset"]
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class BackupManifest(BaseModel):
    """Self-describing manifest stored inside every ``.magibackup`` file."""

    model_config = ConfigDict(extra="forbid", strict=True)

    format: Literal["magi-memory-backup"] = BACKUP_FORMAT
    format_version: int = BACKUP_FORMAT_VERSION
    backup_id: str
    created_at: str
    magi_version: str = Field(min_length=1, max_length=100)
    encrypted: bool
    scope: list[Literal["l1", "l2", "l3", "l4", "archives", "manual_entry_assets"]]
    schema_revisions: dict[Literal["l1", "memory_shared"], str]
    archive_schema_version: int = 1
    limitations: list[
        Literal[
            "l0_runtime_attention_not_restored",
            "chat_records_and_attachments_not_included",
            "source_evidence_may_be_unavailable",
            "raw_history_import_content_redacted",
        ]
    ]
    files: list[BackupFileRecord] = Field(min_length=2, max_length=MAX_BACKUP_FILE_COUNT)
    counts: dict[str, int] = Field(default_factory=dict)

    @field_validator("format_version")
    @classmethod
    def _supported_version(cls, value: int) -> int:
        if int(value) != BACKUP_FORMAT_VERSION:
            raise ValueError("Unsupported backup format version")
        return int(value)

    @field_validator("backup_id")
    @classmethod
    def _valid_backup_id(cls, value: str) -> str:
        try:
            parsed = uuid.UUID(value)
        except ValueError as exc:
            raise ValueError("Backup ID must be a UUID") from exc
        if parsed.version != 4 or str(parsed) != value:
            raise ValueError("Backup ID must be a canonical UUIDv4")
        return value

    @field_validator("created_at")
    @classmethod
    def _valid_created_at(cls, value: str) -> str:
        if not value.endswith("Z"):
            raise ValueError("Backup creation time must be UTC")
        try:
            parsed = datetime.fromisoformat(value[:-1] + "+00:00")
        except ValueError as exc:
            raise ValueError("Backup creation time is invalid") from exc
        if parsed.tzinfo != timezone.utc:
            raise ValueError("Backup creation time must be UTC")
        return value

    @model_validator(mode="after")
    def _unique_files_and_required_databases(self) -> "BackupManifest":
        paths = [record.path for record in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("Backup manifest contains duplicate file paths")
        required = {"databases/l1_events.db", "databases/memory.db"}
        if not required.issubset(paths):
            raise ValueError("Backup manifest is missing a required memory database")
        expected_scope = {
            "l1",
            "l2",
            "l3",
            "l4",
            "archives",
            "manual_entry_assets",
        }
        if len(self.scope) != len(set(self.scope)) or set(self.scope) != expected_scope:
            raise ValueError("Backup manifest has an invalid restorable scope")
        if set(self.schema_revisions) != {"l1", "memory_shared"}:
            raise ValueError("Backup manifest has an invalid schema revision set")
        if any(not value or len(value) > 200 for value in self.schema_revisions.values()):
            raise ValueError("Backup manifest has an invalid schema revision")
        if any(value < 0 for value in self.counts.values()):
            raise ValueError("Backup manifest contains a negative record count")
        if any(not re.fullmatch(r"[a-z0-9_]{1,100}", key) for key in self.counts):
            raise ValueError("Backup manifest contains an invalid record count key")
        if self.archive_schema_version != 1:
            raise ValueError("Backup manifest has an unsupported archive schema version")
        if tuple(self.limitations) != BACKUP_LIMITATIONS:
            raise ValueError("Backup manifest has an invalid limitations contract")
        if sum(record.size_bytes for record in self.files) > MAX_BACKUP_UNCOMPRESSED_BYTES:
            raise ValueError("Backup manifest exceeds the supported size")
        for record in self.files:
            if not _purpose_matches_path(record):
                raise ValueError("Backup manifest file purpose does not match its path")
        return self


def _purpose_matches_path(record: BackupFileRecord) -> bool:
    if record.purpose == "l1":
        return record.path == "databases/l1_events.db"
    if record.purpose == "memory":
        return record.path == "databases/memory.db"
    if record.purpose == "archive":
        match = re.fullmatch(r"archives/(?P<date>\d{4}-\d{2}-\d{2})\.db", record.path)
        if match is None:
            return False
        try:
            datetime.fromisoformat(match.group("date"))
        except ValueError:
            return False
        return True
    if record.purpose == "manual_entry_asset":
        match = re.fullmatch(
            r"assets/manual_entries/(?P<shard>[0-9a-f]{2})/"
            r"(?P<digest>[0-9a-f]{64})\.(?:gif|jpg|png|webp)",
            record.path,
        )
        return bool(
            match is not None
            and match.group("shard") == match.group("digest")[:2]
            and match.group("digest") == record.sha256
        )
    return False


class SnapshotFile(BaseModel):
    """One staged file and its archive-facing metadata."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    source_path: Any
    archive_path: str
    purpose: Literal["l1", "memory", "archive", "manual_entry_asset"]


class SnapshotBundle(BaseModel):
    """Private consistent cut used to build a backup or readable export."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    root: Any
    files: list[SnapshotFile]
    schema_revisions: dict[str, str]
    counts: dict[str, int]


class BackupInspection(BaseModel):
    """Validated restore candidate returned before destructive confirmation."""

    model_config = ConfigDict(extra="forbid")

    password_required: bool = False
    candidate_id: str | None = None
    fingerprint: str | None = None
    created_at: str | None = None
    magi_version: str | None = None
    encrypted: bool = False
    scope: list[str] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    expires_at: str | None = None


class PortabilityJob(BaseModel):
    """Process-local progress record for backup, export, or restore work."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    kind: Literal["backup", "export", "restore"]
    status: Literal["pending", "running", "succeeded", "failed"]
    stage: str
    created_at: str
    updated_at: str
    output_path: str | None = None
    safety_backup_path: str | None = None
    error_code: str | None = None
    error_message: str | None = None


__all__ = [
    "BACKUP_FORMAT",
    "BACKUP_FORMAT_VERSION",
    "BACKUP_LIMITATIONS",
    "EXPORT_FORMAT",
    "EXPORT_FORMAT_VERSION",
    "MAX_BACKUP_FILE_COUNT",
    "MAX_BACKUP_UNCOMPRESSED_BYTES",
    "BackupFileRecord",
    "BackupInspection",
    "BackupManifest",
    "PortabilityJob",
    "SnapshotBundle",
    "SnapshotFile",
    "utc_now_iso",
]
