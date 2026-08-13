from __future__ import annotations

import pytest
from pydantic import ValidationError

from magi_plugin_sdk import (
    HistoryImportParseResult,
    HistoryImportRecord,
    HistoryImportSource,
    HistoryImporterSpec,
)
from magi_plugin_sdk.history_imports import (
    MAX_HISTORY_IMPORT_CONTENT_LENGTH,
    MAX_HISTORY_IMPORT_LOCALES,
    MAX_HISTORY_IMPORT_RECORDS_PER_SOURCE,
    MAX_HISTORY_IMPORT_SOURCES,
)


def test_importer_spec_normalizes_extensions() -> None:
    spec = HistoryImporterSpec(
        importer_id="chatgpt-export",
        display_name="ChatGPT",
        display_name_i18n={"zh-CN": " ChatGPT 历史 "},
        description="Import an official export.",
        description_i18n={"zh-CN": " 导入官方导出文件。 "},
        accepted_extensions=[".ZIP", "json", "json"],
        format_version="1",
    )

    assert spec.accepted_extensions == ["zip", "json"]
    assert spec.display_name_i18n == {"zh-CN": "ChatGPT 历史"}
    assert spec.description_i18n == {"zh-CN": "导入官方导出文件。"}
    assert spec.participant_identity_scope == "source"


def test_importer_spec_can_declare_export_global_participants() -> None:
    spec = HistoryImporterSpec(
        importer_id="archive",
        display_name="Archive",
        accepted_extensions=["zip"],
        format_version="1",
        participant_identity_scope="export",
    )

    assert spec.participant_identity_scope == "export"


def test_importer_spec_rejects_unknown_participant_identity_scope() -> None:
    with pytest.raises(ValidationError, match="participant_identity_scope"):
        HistoryImporterSpec(
            importer_id="archive",
            display_name="Archive",
            accepted_extensions=["zip"],
            format_version="1",
            participant_identity_scope="conversation",  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("field_name", "value", "error"),
    [
        ("display_name_i18n", {"zh_CN": "名称"}, "valid language tags"),
        ("display_name_i18n", {"zh-CN": "   "}, "cannot be blank"),
        ("description_i18n", {"en": "x" * 1_001}, "is too long"),
    ],
)
def test_importer_spec_rejects_invalid_localized_metadata(
    field_name: str,
    value: dict[str, str],
    error: str,
) -> None:
    with pytest.raises(ValidationError, match=error):
        HistoryImporterSpec(
            importer_id="archive",
            display_name="Archive",
            accepted_extensions=["zip"],
            format_version="1",
            **{field_name: value},
        )


def test_importer_spec_bounds_localized_metadata_entries() -> None:
    with pytest.raises(ValidationError, match="at most"):
        HistoryImporterSpec(
            importer_id="archive",
            display_name="Archive",
            display_name_i18n={
                f"x-{index}": f"Name {index}"
                for index in range(MAX_HISTORY_IMPORT_LOCALES + 1)
            },
            accepted_extensions=["zip"],
            format_version="1",
        )


@pytest.mark.parametrize("timestamp_confidence", ["exact", "inferred"])
def test_declared_timestamp_confidence_requires_occurred_at(
    timestamp_confidence: str,
) -> None:
    with pytest.raises(ValidationError, match="requires occurred_at"):
        HistoryImportRecord(
            message_key="m1",
            source_order=0,
            speaker_id="user",
            speaker_name="You",
            role_hint="user",
            content="I like pottery.",
            timestamp_confidence=timestamp_confidence,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("timestamp_confidence", ["exact", "inferred"])
def test_declared_timestamp_confidence_accepts_occurred_at(
    timestamp_confidence: str,
) -> None:
    record = HistoryImportRecord(
        message_key="m1",
        source_order=0,
        speaker_id="user",
        speaker_name="You",
        content="I like pottery.",
        occurred_at=1_700_000_000,
        timestamp_confidence=timestamp_confidence,  # type: ignore[arg-type]
    )

    assert record.occurred_at == 1_700_000_000
    assert record.timestamp_confidence == timestamp_confidence


@pytest.mark.parametrize("timestamp_confidence", ["source_order", "unknown"])
def test_untimed_confidence_requires_occurred_at_none(
    timestamp_confidence: str,
) -> None:
    with pytest.raises(ValidationError, match="require occurred_at=None"):
        HistoryImportRecord(
            message_key="m1",
            source_order=0,
            speaker_id="user",
            speaker_name="You",
            content="I like pottery.",
            occurred_at=1_700_000_000,
            timestamp_confidence=timestamp_confidence,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("occurred_at", [float("nan"), float("inf"), float("-inf")])
def test_record_rejects_non_finite_timestamp(occurred_at: float) -> None:
    with pytest.raises(ValidationError, match="timestamp must be finite"):
        HistoryImportRecord(
            message_key="m1",
            source_order=0,
            speaker_id="user",
            speaker_name="You",
            content="I like pottery.",
            occurred_at=occurred_at,
        )


def test_record_strips_content_but_rejects_whitespace_in_identity() -> None:
    record = HistoryImportRecord(
        message_key="m1",
        source_order=0,
        speaker_id="user",
        speaker_name=" You ",
        content="  I like pottery.  ",
    )

    assert record.message_key == "m1"
    assert record.speaker_id == "user"
    assert record.speaker_name == "You"
    assert record.content == "I like pottery."
    with pytest.raises(ValidationError, match="outer whitespace"):
        HistoryImportRecord(
            message_key=" m1 ",
            source_order=0,
            speaker_id="user",
            speaker_name="You",
            content="I like pottery.",
        )


def test_source_rejects_duplicate_message_identity_and_dangling_parent() -> None:
    base = dict(
        source_order=0,
        speaker_id="user",
        speaker_name="You",
        content="I like pottery.",
    )
    with pytest.raises(ValidationError, match="message keys must be unique"):
        HistoryImportSource(
            source_id="conversation-1",
            source_name="Pottery",
            session_key="conversation-1",
            records=[
                HistoryImportRecord(message_key="m1", **base),
                HistoryImportRecord(message_key="m1", **{**base, "source_order": 1}),
            ],
        )
    with pytest.raises(ValidationError, match="parent message keys"):
        HistoryImportSource(
            source_id="conversation-1",
            source_name="Pottery",
            session_key="conversation-1",
            records=[
                HistoryImportRecord(
                    message_key="m1",
                    parent_message_key="missing",
                    **base,
                )
            ],
        )


def test_parse_result_rejects_duplicate_source_identity() -> None:
    def source(*, source_id: str, session_key: str) -> HistoryImportSource:
        return HistoryImportSource(
            source_id=source_id,
            source_name=source_id,
            session_key=session_key,
            records=[
                HistoryImportRecord(
                    message_key="m1",
                    source_order=0,
                    speaker_id="user",
                    speaker_name="You",
                    content="I like pottery.",
                )
            ],
        )

    with pytest.raises(ValidationError, match="source ids must be unique"):
        HistoryImportParseResult(
            sources=[
                source(source_id="same", session_key="session-1"),
                source(source_id="same", session_key="session-2"),
            ]
        )
    result = HistoryImportParseResult(
        sources=[
            source(source_id="source-1", session_key="same"),
            source(source_id="source-2", session_key="same"),
        ]
    )
    assert len(result.sources) == 2


def test_contract_rejects_oversized_content_and_collections() -> None:
    with pytest.raises(ValidationError, match="at most"):
        HistoryImportRecord(
            message_key="m1",
            source_order=0,
            speaker_id="user",
            speaker_name="You",
            content="x" * (MAX_HISTORY_IMPORT_CONTENT_LENGTH + 1),
        )

    record = HistoryImportRecord(
        message_key="m1",
        source_order=0,
        speaker_id="user",
        speaker_name="You",
        content="text",
    )
    with pytest.raises(ValidationError, match="at most"):
        HistoryImportSource(
            source_id="conversation-1",
            source_name="Conversation",
            session_key="conversation-1",
            records=[record] * (MAX_HISTORY_IMPORT_RECORDS_PER_SOURCE + 1),
        )

    source = HistoryImportSource(
        source_id="conversation-1",
        source_name="Conversation",
        session_key="conversation-1",
        records=[record],
    )
    with pytest.raises(ValidationError, match="at most"):
        HistoryImportParseResult(sources=[source] * (MAX_HISTORY_IMPORT_SOURCES + 1))
