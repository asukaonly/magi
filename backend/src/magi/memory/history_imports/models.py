"""Contracts for durable one-shot history imports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class HistoryImportRecord:
    """One normalized source record kept in original conversation order."""

    job_record_id: str
    job_id: str
    source_record_key: str
    file_fingerprint: str
    source_id: str
    source_name: str
    source_kind: str
    parsed_session_key: str
    session_id: str
    session_seq: int
    speaker_id: str
    speaker_name: str
    message_key: str
    parent_message_key: str | None
    content: str
    event_at: float
    timestamp_confidence: str
    timestamp_anchor_source: str
    calendar_timezone_id: str
    meaningful: bool
    event_id: str
    speaker_role: str = "unknown"
    raw_state: str = "pending"
    projection_state: str = "pending"
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class HistoryImportParticipant:
    """Participant summary shown before the user confirms their identity."""

    participant_id: str
    display_name: str
    message_count: int
    meaningful_count: int
    sample: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class HistoryImportSourceSummary:
    """One selected Markdown file and its reader-facing preview metadata."""

    source_id: str
    source_name: str
    detected_kind: str
    record_count: int
    meaningful_count: int
    first_event_at: float
    last_event_at: float
    timestamp_confidence: str
    sample: str
    included: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class HistoryImportSourcePreview:
    """Bounded content preview for one selected source file."""

    source_id: str
    source_name: str
    detected_kind: str
    records: list[HistoryImportRecord]
    truncated: bool

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["records"] = [item.to_dict() for item in self.records]
        return payload


@dataclass(slots=True)
class HistoryImportJob:
    """Durable import lifecycle and reader-facing progress."""

    job_id: str
    source_type: str
    source_fingerprint: str
    source_ids: list[str]
    included_source_ids: list[str]
    detected_kind: str
    status: str
    total_records: int
    meaningful_records: int
    quick_target_records: int
    quick_max_records: int
    quick_imported_count: int
    imported_count: int
    projected_count: int
    self_participant_ids: list[str]
    warnings: list[str]
    quick_ready: bool
    created_at: float
    updated_at: float
    importer_plugin_id: str | None = None
    importer_id: str | None = None
    importer_format_version: str | None = None
    error_text: str | None = None
    deleted_at: float | None = None
    participants: list[HistoryImportParticipant] = field(default_factory=list)
    sources: list[HistoryImportSourceSummary] = field(default_factory=list)
    preview_records: list[HistoryImportRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["participants"] = [item.to_dict() for item in self.participants]
        payload["sources"] = [item.to_dict() for item in self.sources]
        payload["preview_records"] = [item.to_dict() for item in self.preview_records]
        return payload


@dataclass(slots=True)
class HistoryImportAppendResult:
    """Result of extending an unconfirmed preview with more source files."""

    job: HistoryImportJob
    added_source_count: int
    duplicate_source_count: int


@dataclass(slots=True)
class ParsedHistorySource:
    """Parser output before a preview job receives durable identities."""

    source_id: str
    source_name: str
    session_key: str
    detected_kind: str
    records: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)


__all__ = [
    "HistoryImportAppendResult",
    "HistoryImportJob",
    "HistoryImportParticipant",
    "HistoryImportRecord",
    "HistoryImportSourcePreview",
    "HistoryImportSourceSummary",
    "ParsedHistorySource",
]
