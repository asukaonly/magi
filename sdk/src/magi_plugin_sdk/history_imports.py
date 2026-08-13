"""Contracts for platform-specific, one-shot history import adapters."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Annotated, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field, field_validator, model_validator

MAX_HISTORY_IMPORT_SOURCES = 500
MAX_HISTORY_IMPORT_RECORDS_PER_SOURCE = 20_000
MAX_HISTORY_IMPORT_WARNINGS = 200
MAX_HISTORY_IMPORT_SOURCE_WARNINGS = 100
MAX_HISTORY_IMPORT_WARNING_LENGTH = 512
MAX_HISTORY_IMPORT_CONTENT_LENGTH = 1_000_000
MAX_HISTORY_IMPORT_LOCALES = 20
MAX_HISTORY_IMPORT_LOCALE_LENGTH = 35

_LOCALE_PATTERN = re.compile(r"^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$")

_WarningText = Annotated[
    str,
    Field(min_length=1, max_length=MAX_HISTORY_IMPORT_WARNING_LENGTH),
]


class HistoryImporterSpec(BaseModel):
    """Declarative metadata for one host-rendered history importer."""

    importer_id: str = Field(pattern=r"^[a-z0-9_-]+$")
    display_name: str = Field(max_length=256)
    display_name_i18n: dict[str, str] = Field(
        default_factory=dict,
        max_length=MAX_HISTORY_IMPORT_LOCALES,
    )
    description: str = Field(default="", max_length=1_000)
    description_i18n: dict[str, str] = Field(
        default_factory=dict,
        max_length=MAX_HISTORY_IMPORT_LOCALES,
    )
    accepted_extensions: list[str] = Field(min_length=1, max_length=20)
    format_version: str = Field(min_length=1, max_length=128)
    participant_identity_scope: Literal["source", "export"] = "source"
    export_help_url: str | None = Field(default=None, max_length=2_048)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("History importer metadata cannot be blank")
        return normalized

    @field_validator("display_name_i18n")
    @classmethod
    def normalize_localized_display_names(
        cls, values: dict[str, str]
    ) -> dict[str, str]:
        return _normalize_localized_text(
            values,
            max_text_length=256,
            field_name="display name",
        )

    @field_validator("description_i18n")
    @classmethod
    def normalize_localized_descriptions(cls, values: dict[str, str]) -> dict[str, str]:
        return _normalize_localized_text(
            values,
            max_text_length=1_000,
            field_name="description",
        )

    @field_validator("format_version")
    @classmethod
    def validate_format_version(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("History importer metadata cannot be blank")
        if normalized != value:
            raise ValueError(
                "History importer format version cannot contain outer whitespace"
            )
        return value

    @field_validator("accepted_extensions")
    @classmethod
    def normalize_extensions(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().casefold().lstrip(".") for value in values]
        if any(
            not value or not value.replace("-", "").isalnum() for value in normalized
        ):
            raise ValueError("History importer extensions must be simple file suffixes")
        return list(dict.fromkeys(normalized))


def _normalize_localized_text(
    values: dict[str, str],
    *,
    max_text_length: int,
    field_name: str,
) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for locale, text in values.items():
        if (
            locale != locale.strip()
            or len(locale) > MAX_HISTORY_IMPORT_LOCALE_LENGTH
            or _LOCALE_PATTERN.fullmatch(locale) is None
        ):
            raise ValueError("History importer locale keys must be valid language tags")
        normalized_text = text.strip()
        if not normalized_text:
            raise ValueError(f"History importer localized {field_name} cannot be blank")
        if len(normalized_text) > max_text_length:
            raise ValueError(f"History importer localized {field_name} is too long")
        normalized[locale] = normalized_text
    return normalized


class HistoryImportRecord(BaseModel):
    """One message with source-declared identity and ordering semantics."""

    message_key: str = Field(min_length=1, max_length=512)
    source_order: int = Field(ge=0)
    speaker_id: str = Field(min_length=1, max_length=512)
    speaker_name: str = Field(min_length=1, max_length=256)
    role_hint: Literal["user", "assistant", "other", "unknown"] = "unknown"
    content: str = Field(min_length=1, max_length=MAX_HISTORY_IMPORT_CONTENT_LENGTH)
    occurred_at: float | None = None
    timestamp_confidence: Literal["exact", "inferred", "source_order", "unknown"] = (
        "unknown"
    )
    parent_message_key: str | None = Field(default=None, max_length=512)

    @field_validator("message_key", "speaker_id")
    @classmethod
    def validate_record_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("History import record identity cannot be blank")
        if normalized != value:
            raise ValueError(
                "History import record identity cannot contain outer whitespace"
            )
        return value

    @field_validator("speaker_name")
    @classmethod
    def normalize_speaker_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("History import speaker name cannot be blank")
        return normalized

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("History import record content cannot be blank")
        return normalized

    @field_validator("parent_message_key")
    @classmethod
    def normalize_parent_message_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("History import parent message key cannot be blank")
        if normalized != value:
            raise ValueError(
                "History import parent message key cannot contain outer whitespace"
            )
        return value

    @field_validator("occurred_at")
    @classmethod
    def require_finite_timestamp(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("History import timestamp must be finite")
        return value

    @model_validator(mode="after")
    def validate_timestamp_contract(self) -> "HistoryImportRecord":
        if self.timestamp_confidence in {"exact", "inferred"}:
            if self.occurred_at is None:
                raise ValueError(
                    "Timestamp confidence exact or inferred requires occurred_at"
                )
            return self
        if self.occurred_at is not None:
            raise ValueError(
                "Source-order and unknown timestamp confidence require occurred_at=None"
            )
        return self


class HistoryImportSource(BaseModel):
    """One independently selectable conversation from an export archive."""

    source_id: str = Field(min_length=1, max_length=512)
    source_name: str = Field(min_length=1, max_length=512)
    session_key: str = Field(min_length=1, max_length=512)
    detected_kind: Literal["chat"] = "chat"
    records: list[HistoryImportRecord] = Field(
        min_length=1,
        max_length=MAX_HISTORY_IMPORT_RECORDS_PER_SOURCE,
    )
    warnings: list[_WarningText] = Field(
        default_factory=list,
        max_length=MAX_HISTORY_IMPORT_SOURCE_WARNINGS,
    )

    @field_validator("source_id", "session_key")
    @classmethod
    def validate_source_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("History import source identity cannot be blank")
        if normalized != value:
            raise ValueError(
                "History import source identity cannot contain outer whitespace"
            )
        return value

    @field_validator("source_name")
    @classmethod
    def normalize_source_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("History import source name cannot be blank")
        return normalized

    @model_validator(mode="after")
    def validate_record_identity(self) -> "HistoryImportSource":
        message_keys = [record.message_key for record in self.records]
        source_orders = [record.source_order for record in self.records]
        if len(message_keys) != len(set(message_keys)):
            raise ValueError("History import message keys must be unique per source")
        if len(source_orders) != len(set(source_orders)):
            raise ValueError("History import source order must be unique per source")
        known_keys = set(message_keys)
        if any(
            record.parent_message_key is not None
            and record.parent_message_key not in known_keys
            for record in self.records
        ):
            raise ValueError(
                "History import parent message keys must reference the source"
            )
        return self


class HistoryImportParseResult(BaseModel):
    """Complete normalized output returned to the host preview boundary."""

    sources: list[HistoryImportSource] = Field(
        min_length=1,
        max_length=MAX_HISTORY_IMPORT_SOURCES,
    )
    warnings: list[_WarningText] = Field(
        default_factory=list,
        max_length=MAX_HISTORY_IMPORT_WARNINGS,
    )

    @model_validator(mode="after")
    def validate_source_identity(self) -> "HistoryImportParseResult":
        source_ids = [source.source_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("History import source ids must be unique")
        return self


@runtime_checkable
class HistoryImporter(Protocol):
    """Parser-only adapter; the host owns persistence and memory governance."""

    async def parse(self, paths: list[Path]) -> HistoryImportParseResult:
        """Parse declared export files without writing host state."""


__all__ = [
    "HistoryImportParseResult",
    "HistoryImportRecord",
    "HistoryImportSource",
    "HistoryImporter",
    "HistoryImporterSpec",
    "MAX_HISTORY_IMPORT_CONTENT_LENGTH",
    "MAX_HISTORY_IMPORT_LOCALES",
    "MAX_HISTORY_IMPORT_RECORDS_PER_SOURCE",
    "MAX_HISTORY_IMPORT_SOURCES",
    "MAX_HISTORY_IMPORT_SOURCE_WARNINGS",
    "MAX_HISTORY_IMPORT_WARNINGS",
    "MAX_HISTORY_IMPORT_WARNING_LENGTH",
]
