"""Per check-kind unit tests for availability probes."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from magi.availability.checks import (
    check_app_installed,
    check_executable_in_path,
    check_file_exists,
)
from magi_plugin_sdk.contracts import (
    LocalRequirementAppInstalled,
    LocalRequirementExecutableInPath,
    LocalRequirementFileExists,
)


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


@pytest.mark.parametrize(
    "raw_path",
    [
        r"\\server\share\history.db",
        r"\\?\C:\Users\example\history.db",
        r"\\.\PhysicalDrive0",
        "https://example.test/history.db",
        r"relative\history.db",
        r"C:\Users\example\NUL.txt",
        r"C:\Users\example\history.db:stream",
    ],
)
def test_file_exists_rejects_unsafe_windows_paths_before_touching_disk(
    raw_path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("magi.availability.checks._current_platform_key", lambda: "win32")
    monkeypatch.setattr(
        Path,
        "exists",
        lambda _path: pytest.fail("unsafe Windows path reached Path.exists"),
    )
    req = LocalRequirementFileExists(
        check_kind="file_exists",
        paths_per_platform={"win32": raw_path},
    )

    ok, detail = check_file_exists(req)

    assert ok is False
    assert detail


def test_file_exists_rejects_a_remote_windows_drive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("magi.availability.checks._current_platform_key", lambda: "win32")
    monkeypatch.setattr(
        "magi.availability.checks._windows_drive_is_local",
        lambda _drive: False,
    )
    monkeypatch.setattr(
        Path,
        "exists",
        lambda _path: pytest.fail("remote Windows drive reached Path.exists"),
    )
    req = LocalRequirementFileExists(
        check_kind="file_exists",
        paths_per_platform={"win32": r"Z:\History\history.db"},
    )

    ok, detail = check_file_exists(req)

    assert ok is False
    assert "local drive" in (detail or "")


def test_file_exists_accepts_a_local_absolute_windows_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("magi.availability.checks._current_platform_key", lambda: "win32")
    monkeypatch.setattr(
        "magi.availability.checks._windows_drive_is_local",
        lambda _drive: True,
    )
    monkeypatch.setattr(Path, "exists", lambda _path: True)
    req = LocalRequirementFileExists(
        check_kind="file_exists",
        paths_per_platform={"win32": r"C:\Users\example\history.db"},
    )

    ok, detail = check_file_exists(req)

    assert ok is True
    assert detail is None


def test_executable_in_path_finds_known_binary() -> None:
    """`python` should be on PATH in any developer environment."""
    req = LocalRequirementExecutableInPath(
        check_kind="executable_in_path",
        names=["python", "python3"],
    )
    ok, detail = check_executable_in_path(req)
    assert ok is True
    assert detail is None


def test_executable_in_path_returns_false_for_missing() -> None:
    req = LocalRequirementExecutableInPath(
        check_kind="executable_in_path",
        names=["definitely-not-a-real-binary-xyzzy"],
    )
    ok, detail = check_executable_in_path(req)
    assert ok is False
    assert detail is not None
    assert "xyzzy" in detail


def test_executable_in_path_short_circuits_on_first_hit() -> None:
    req = LocalRequirementExecutableInPath(
        check_kind="executable_in_path",
        names=["python", "definitely-not-a-real-binary"],
    )
    ok, _ = check_executable_in_path(req)
    assert ok is True


@pytest.mark.parametrize(
    "name",
    [
        "../git",
        r"C:\Tools\git.exe",
        "/usr/bin/git",
        "git;open",
        "x" * 65,
    ],
)
def test_executable_in_path_rejects_non_basename_values(
    name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "magi.availability.checks.shutil.which",
        lambda _name: pytest.fail("invalid executable reached shutil.which"),
    )
    req = LocalRequirementExecutableInPath(
        check_kind="executable_in_path",
        names=[name],
    )

    ok, detail = check_executable_in_path(req)

    assert ok is False
    assert detail == "no valid executable basename declared"


def test_app_installed_uses_macos_mdfind(monkeypatch: pytest.MonkeyPatch) -> None:
    """On macOS, the check shells out to `mdfind`."""
    req = LocalRequirementAppInstalled(
        check_kind="app_installed",
        identifier_per_platform={"darwin": "com.google.Chrome"},
    )

    monkeypatch.setattr("magi.availability.checks._current_platform_key", lambda: "darwin")

    fake = subprocess.CompletedProcess(
        args=["mdfind", "..."], returncode=0, stdout="/Applications/Google Chrome.app\n"
    )
    with patch("subprocess.run", return_value=fake):
        ok, _ = check_app_installed(req)
    assert ok is True


def test_app_installed_macos_negative(monkeypatch: pytest.MonkeyPatch) -> None:
    req = LocalRequirementAppInstalled(
        check_kind="app_installed",
        identifier_per_platform={"darwin": "com.does.not.exist"},
    )
    monkeypatch.setattr("magi.availability.checks._current_platform_key", lambda: "darwin")
    fake = subprocess.CompletedProcess(args=["mdfind", "..."], returncode=0, stdout="")
    with patch("subprocess.run", return_value=fake):
        ok, detail = check_app_installed(req)
    assert ok is False
    assert "com.does.not.exist" in detail


@pytest.mark.parametrize(
    "bundle_id",
    [
        "Chrome",
        "com.google.Chrome' || true",
        "com.google/Chrome",
        f"com.{'x' * 253}",
    ],
)
def test_app_installed_rejects_invalid_macos_bundle_ids(
    bundle_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("magi.availability.checks._current_platform_key", lambda: "darwin")
    monkeypatch.setattr(
        "magi.availability.checks._check_macos_app",
        lambda _identifier: pytest.fail("invalid bundle id reached mdfind"),
    )
    req = LocalRequirementAppInstalled(
        check_kind="app_installed",
        identifier_per_platform={"darwin": bundle_id},
    )

    ok, detail = check_app_installed(req)

    assert ok is False
    assert detail == "invalid macOS bundle identifier"


def test_app_installed_linux_finds_desktop_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    desktop_dir = tmp_path / "applications"
    desktop_dir.mkdir()
    (desktop_dir / "google-chrome.desktop").write_text("[Desktop Entry]\nName=Chrome\n")

    monkeypatch.setattr("magi.availability.checks._current_platform_key", lambda: "linux")
    monkeypatch.setattr(
        "magi.availability.checks._LINUX_DESKTOP_DIRS", [desktop_dir], raising=False
    )

    req = LocalRequirementAppInstalled(
        check_kind="app_installed",
        identifier_per_platform={"linux": "google-chrome"},
    )
    ok, _ = check_app_installed(req)
    assert ok is True


@pytest.mark.parametrize(
    "desktop_id",
    [
        "../google-chrome",
        "google/chrome",
        ".hidden",
        "x" * 129,
    ],
)
def test_app_installed_rejects_invalid_linux_desktop_ids(
    desktop_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("magi.availability.checks._current_platform_key", lambda: "linux")
    monkeypatch.setattr(
        "magi.availability.checks._check_linux_app",
        lambda _identifier: pytest.fail("invalid desktop id reached filesystem lookup"),
    )
    req = LocalRequirementAppInstalled(
        check_kind="app_installed",
        identifier_per_platform={"linux": desktop_id},
    )

    ok, detail = check_app_installed(req)

    assert ok is False
    assert detail == "invalid Linux desktop identifier"


def test_app_installed_windows_best_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows path returns honest (False, 'not yet implemented') when winreg isn't usable."""
    monkeypatch.setattr("magi.availability.checks._current_platform_key", lambda: "win32")
    req = LocalRequirementAppInstalled(
        check_kind="app_installed",
        identifier_per_platform={"win32": "Google Chrome"},
    )
    # Force the winreg-availability flag off so the stub path runs deterministically
    monkeypatch.setattr(
        "magi.availability.checks._WINDOWS_REGISTRY_AVAILABLE", False, raising=False
    )
    ok, detail = check_app_installed(req)
    assert ok is False
    assert "not yet implemented" in (detail or "")


def test_app_installed_missing_current_platform() -> None:
    req = LocalRequirementAppInstalled(
        check_kind="app_installed",
        identifier_per_platform={"some-os": "x"},
    )
    ok, detail = check_app_installed(req)
    assert ok is False
