"""Reader-facing contract tests for history import routes."""

from types import SimpleNamespace

import pytest
from magi_plugin_sdk import HistoryImporterSpec

from magi.api.routers.memory import history_import_routes
from magi.api.routers.memory.history_import_routes import _warning_summary


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
