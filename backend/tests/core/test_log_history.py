from __future__ import annotations

from logging.handlers import RotatingFileHandler
import logging
from pathlib import Path

import pytest

from magi.core import log_history
from magi.core.log_history import clear_diagnostic_log_history


@pytest.mark.asyncio
async def test_clear_diagnostic_log_history_erases_active_rotated_and_backend_logs(
    tmp_path: Path,
) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    active_log = logs_dir / "magi.log"
    handler = RotatingFileHandler(active_log, maxBytes=1024, backupCount=2, encoding="utf-8")
    logger = logging.getLogger(f"test.log-history.{id(handler)}")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    logger.info("old active secret")
    (logs_dir / "magi.log.1").write_text("old rotated secret", encoding="utf-8")
    (logs_dir / "backend.log").write_text("old sidecar secret", encoding="utf-8")
    desktop_log = logs_dir / "desktop_2026-07-31.log"
    desktop_log.write_text(
        "old desktop secret",
        encoding="utf-8",
    )
    external_log = tmp_path / "custom-backend.log"
    external_log.write_text("old custom secret", encoding="utf-8")
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("must stay", encoding="utf-8")

    try:
        result = await clear_diagnostic_log_history(
            logs_dir=logs_dir,
            extra_log_paths=[external_log],
            handlers=[handler],
        )

        assert result.failed_entries == 0
        assert result.cleared_entries == 4
        assert active_log.read_text(encoding="utf-8") == ""
        assert (logs_dir / "magi.log.1").read_text(encoding="utf-8") == ""
        assert (logs_dir / "backend.log").read_text(encoding="utf-8") == ""
        assert desktop_log.read_text(encoding="utf-8") == "old desktop secret"
        assert external_log.read_text(encoding="utf-8") == ""
        assert outside_file.read_text(encoding="utf-8") == "must stay"

        logger.info("fresh diagnostic")
        handler.flush()
        refreshed = active_log.read_text(encoding="utf-8")
        assert "fresh diagnostic" in refreshed
        assert "old active secret" not in refreshed
    finally:
        logger.removeHandler(handler)
        handler.close()


@pytest.mark.asyncio
async def test_clear_diagnostic_log_history_uses_configured_dev_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    configured_log = tmp_path / "configured" / "backend-hot.log"
    configured_log.parent.mkdir()
    configured_log.write_text("old dev output", encoding="utf-8")
    monkeypatch.setenv("MAGI_BACKEND_LOG_FILE", str(configured_log))

    result = await clear_diagnostic_log_history(logs_dir=logs_dir, handlers=[])

    assert result.failed_entries == 0
    assert configured_log.read_text(encoding="utf-8") == ""


@pytest.mark.asyncio
async def test_clear_diagnostic_log_history_rejects_hard_links(
    tmp_path: Path,
) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("must stay", encoding="utf-8")
    linked_log = logs_dir / "magi.log.1"
    linked_log.hardlink_to(outside_file)

    result = await clear_diagnostic_log_history(
        logs_dir=logs_dir,
        extra_log_paths=[],
        handlers=[],
    )

    assert result.cleared_entries == 0
    assert result.failed_entries == 1
    assert linked_log.read_text(encoding="utf-8") == "must stay"
    assert outside_file.read_text(encoding="utf-8") == "must stay"


@pytest.mark.asyncio
async def test_clear_diagnostic_log_history_rejects_an_active_hard_link(
    tmp_path: Path,
) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    active_log = logs_dir / "magi.log"
    handler = RotatingFileHandler(active_log, maxBytes=1024, backupCount=1, encoding="utf-8")
    logger = logging.getLogger(f"test.log-history-hard-link.{id(handler)}")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.info("old active secret")
    handler.flush()
    outside_link = tmp_path / "outside.log"
    outside_link.hardlink_to(active_log)

    try:
        result = await clear_diagnostic_log_history(
            logs_dir=logs_dir,
            extra_log_paths=[],
            handlers=[handler],
        )

        assert result.cleared_entries == 0
        assert result.failed_entries >= 1
        assert "old active secret" in active_log.read_text(encoding="utf-8")
        assert "old active secret" in outside_link.read_text(encoding="utf-8")
    finally:
        logger.removeHandler(handler)
        handler.close()


@pytest.mark.asyncio
async def test_clear_diagnostic_log_history_rejects_symlinked_entries(
    tmp_path: Path,
) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("must stay", encoding="utf-8")
    linked_log = logs_dir / "magi.log.1"
    linked_log.symlink_to(outside_file)

    result = await clear_diagnostic_log_history(
        logs_dir=logs_dir,
        extra_log_paths=[],
        handlers=[],
    )

    assert result.cleared_entries == 0
    assert result.failed_entries == 1
    assert linked_log.is_symlink()
    assert outside_file.read_text(encoding="utf-8") == "must stay"


@pytest.mark.asyncio
async def test_clear_diagnostic_log_history_flushes_redirected_process_output(
    tmp_path: Path,
) -> None:
    class _RedirectedOutput:
        def __init__(self) -> None:
            self.flush_count = 0

        def write(self, _value: str) -> int:
            return 0

        def flush(self) -> None:
            self.flush_count += 1

        def fileno(self) -> int:
            return 1

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    stream = _RedirectedOutput()
    handler = logging.StreamHandler(stream)  # type: ignore[arg-type]

    result = await clear_diagnostic_log_history(
        logs_dir=logs_dir,
        extra_log_paths=[],
        handlers=[handler],
    )

    assert result.failed_entries == 0
    assert stream.flush_count == 1


@pytest.mark.asyncio
async def test_clear_diagnostic_log_history_refuses_symlinked_log_directory(
    tmp_path: Path,
) -> None:
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_log = outside_dir / "private.log"
    outside_log.write_text("must stay", encoding="utf-8")
    linked_logs_dir = tmp_path / "logs"
    linked_logs_dir.symlink_to(outside_dir, target_is_directory=True)

    result = await clear_diagnostic_log_history(
        logs_dir=linked_logs_dir,
        extra_log_paths=[],
        handlers=[],
    )

    assert result.cleared_entries == 0
    assert result.failed_entries == 1
    assert outside_log.read_text(encoding="utf-8") == "must stay"


@pytest.mark.asyncio
async def test_clear_diagnostic_log_history_detects_parent_directory_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    original_log = logs_dir / "magi.log"
    original_log.write_text("old local log", encoding="utf-8")
    moved_logs = tmp_path / "logs-moved"
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_log = outside_dir / "magi.log"
    outside_log.write_text("must stay", encoding="utf-8")
    original_walk = log_history._walk_log_entries

    def _replace_root_after_listing(path: Path) -> tuple[list[Path], int]:
        entries, failures = original_walk(path)
        path.rename(moved_logs)
        path.symlink_to(outside_dir, target_is_directory=True)
        return entries, failures

    monkeypatch.setattr(log_history, "_walk_log_entries", _replace_root_after_listing)

    result = await clear_diagnostic_log_history(
        logs_dir=logs_dir,
        extra_log_paths=[],
        handlers=[],
    )

    assert result.cleared_entries == 0
    assert result.failed_entries == 1
    assert (moved_logs / "magi.log").read_text(encoding="utf-8") == "old local log"
    assert outside_log.read_text(encoding="utf-8") == "must stay"
