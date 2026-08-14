"""Reader-facing contract tests for history import routes."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from magi_plugin_sdk import HistoryImporterSpec
from magi_plugin_sdk.history_imports import MAX_HISTORY_IMPORT_SOURCES
from pydantic import ValidationError

from magi.api.routers.memory import history_import_routes
from magi.api.routers.memory.history_import_routes import _warning_summary
from magi.memory.history_imports.service import (
    HistoryImportNotFoundError,
    HistoryImportValidationError,
)


@pytest.mark.asyncio
async def test_importer_list_preserves_localized_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    importer = SimpleNamespace(
        plugin_id="platform-history",
        importer_id="account-export",
        spec=HistoryImporterSpec(
            importer_id="account-export",
            display_name="Account history",
            display_name_i18n={"zh-CN": "账户历史"},
            description="Import an official export.",
            description_i18n={"zh-CN": "导入官方导出文件。"},
            accepted_extensions=["zip"],
            format_version="1",
            participant_identity_scope="export",
        ),
    )
    service = SimpleNamespace(list_importers=lambda: [importer])
    monkeypatch.setattr(history_import_routes, "_require_service", lambda: service)

    result = await history_import_routes.list_history_importers()

    assert len(result) == 1
    assert result[0].display_name == "Account history"
    assert result[0].display_name_i18n == {"zh-CN": "账户历史"}
    assert result[0].description_i18n == {"zh-CN": "导入官方导出文件。"}
    assert result[0].participant_identity_scope == "export"


def test_warning_summary_never_exposes_raw_warning_details() -> None:
    summary = _warning_summary(
        [
            "unsupported_content:conversation-private:message-private",
            "a warning containing private prose",
        ]
    )

    assert summary.total_count == 2
    assert summary.codes == ["unsupported_content", "unknown"]
    assert "private" not in " ".join(summary.codes)
    assert summary.truncated is False


def test_warning_summary_preserves_pre_truncation_count() -> None:
    summary = _warning_summary(
        [
            "unsupported_content:one",
            "history_import_warnings_truncated:430",
        ]
    )

    assert summary.total_count == 430
    assert summary.codes == ["unsupported_content"]
    assert summary.truncated is True


@pytest.mark.parametrize(
    "reason",
    [
        "history_import_confirmation_conflict",
        "history_import_scope_conflict",
        "history_import_selection_locked",
        "history_import_speaker_role_conflict",
        "history_importer_non_append_update",
    ],
)
def test_scope_and_confirmation_conflicts_map_to_http_409(reason: str) -> None:
    with pytest.raises(HTTPException) as raised:
        history_import_routes._raise_service_error(HistoryImportValidationError(reason))

    assert raised.value.status_code == 409
    assert raised.value.detail == reason


def test_deleted_history_import_preview_maps_to_http_404() -> None:
    with pytest.raises(HTTPException) as raised:
        history_import_routes._raise_service_error(HistoryImportNotFoundError())

    assert raised.value.status_code == 404
    assert raised.value.detail == "history_import_not_found"


def test_history_import_scope_accepts_large_complete_exports() -> None:
    source_ids = [f"source-{index}" for index in range(501)]

    selection = history_import_routes.HistoryImportSelectionBody(
        included_source_ids=source_ids,
    )
    confirmation = history_import_routes.HistoryImportConfirmBody(
        included_source_ids=source_ids,
        self_participant_ids=source_ids,
    )

    assert selection.included_source_ids == source_ids
    assert confirmation.self_participant_ids == source_ids


def test_history_import_scope_rejects_unbounded_source_lists() -> None:
    source_ids = ["source"] * (MAX_HISTORY_IMPORT_SOURCES + 1)

    with pytest.raises(ValidationError):
        history_import_routes.HistoryImportSelectionBody(
            included_source_ids=source_ids,
        )

    with pytest.raises(ValidationError):
        history_import_routes.HistoryImportConfirmBody(
            self_participant_ids=source_ids,
        )
