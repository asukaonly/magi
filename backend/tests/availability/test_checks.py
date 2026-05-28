"""Per check-kind unit tests for availability probes."""

from __future__ import annotations

from pathlib import Path

import pytest

from magi.availability.checks import check_file_exists
from magi_plugin_sdk.contracts import LocalRequirementFileExists


def test_file_exists_passes_for_existing_path(tmp_path: Path) -> None:
    target = tmp_path / "history.db"
    target.write_text("")
    req = LocalRequirementFileExists(
        check_kind="file_exists",
        paths_per_platform={
            "darwin": str(target),
            "win32": str(target),
            "linux": str(target),
        },
    )
    ok, detail = check_file_exists(req)
    assert ok is True
    assert detail is None


def test_file_exists_fails_for_missing_path(tmp_path: Path) -> None:
    req = LocalRequirementFileExists(
        check_kind="file_exists",
        paths_per_platform={
            "darwin": str(tmp_path / "does-not-exist"),
            "win32": str(tmp_path / "does-not-exist"),
            "linux": str(tmp_path / "does-not-exist"),
        },
    )
    ok, detail = check_file_exists(req)
    assert ok is False
    assert detail is not None
    assert "does-not-exist" in detail


def test_file_exists_fails_when_current_platform_missing(tmp_path: Path) -> None:
    """If no entry for the current platform key, the check fails."""
    req = LocalRequirementFileExists(
        check_kind="file_exists",
        paths_per_platform={"some-other-os": "/nope"},
    )
    ok, detail = check_file_exists(req)
    assert ok is False


def test_file_exists_expands_tilde(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "x.txt"
    target.write_text("")
    req = LocalRequirementFileExists(
        check_kind="file_exists",
        paths_per_platform={
            "darwin": "~/x.txt",
            "win32": "~/x.txt",
            "linux": "~/x.txt",
        },
    )
    ok, _ = check_file_exists(req)
    assert ok is True


def test_file_exists_expands_env_vars(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAGI_TEST_DIR", str(tmp_path))
    target = tmp_path / "x.txt"
    target.write_text("")
    req = LocalRequirementFileExists(
        check_kind="file_exists",
        paths_per_platform={
            "darwin": "$MAGI_TEST_DIR/x.txt",
            "win32": "%MAGI_TEST_DIR%/x.txt",
            "linux": "$MAGI_TEST_DIR/x.txt",
        },
    )
    ok, _ = check_file_exists(req)
    assert ok is True
