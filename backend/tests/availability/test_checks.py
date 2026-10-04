"""Per check-kind unit tests for availability probes."""

from __future__ import annotations

import subprocess
from pathlib import Path

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


@pytest.mark.parametrize("exists", [True, False])
def test_file_probe_reports_the_selected_platform_path(tmp_path, monkeypatch, exists):
    monkeypatch.setattr("magi.availability.checks._current_platform_key", lambda: "linux")
    target = tmp_path / "history.db"
    if exists:
        target.write_text("")
    req = LocalRequirementFileExists(
        check_kind="file_exists",
        paths_per_platform={"linux": str(target), "darwin": str(tmp_path / "wrong-platform")},
    )
    assert check_file_exists(req) == (
        (True, None) if exists else (False, f"path missing: {target}")
    )


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


@pytest.mark.parametrize(
    "found,expected_calls",
    [("first", ["first"]), ("second", ["first", "second"]), (None, ["first", "second"])],
)
def test_executable_probe_stops_at_first_declared_hit(monkeypatch, found, expected_calls):
    from unittest.mock import Mock, call

    lookup = Mock(side_effect=lambda name: f"/controlled/bin/{name}" if name == found else None)
    monkeypatch.setattr("magi.availability.checks.shutil.which", lookup)
    req = LocalRequirementExecutableInPath(
        check_kind="executable_in_path", names=["first", "second"]
    )
    assert check_executable_in_path(req) == (
        (True, None) if found else (False, "no executable found for any of: first, second")
    )
    assert lookup.call_args_list == [call(name) for name in expected_calls]


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


@pytest.mark.parametrize("outcome", ["found", "empty", "failed", "timeout", "missing_binary"])
def test_macos_app_probe_uses_bounded_bundle_query(monkeypatch, outcome):
    from unittest.mock import Mock

    req = LocalRequirementAppInstalled(
        check_kind="app_installed", identifier_per_platform={"darwin": "com.google.Chrome"}
    )
    monkeypatch.setattr("magi.availability.checks._current_platform_key", lambda: "darwin")
    monkeypatch.setattr("magi.availability.checks.hidden_process_kwargs", lambda: {})
    run = Mock()
    if outcome == "timeout":
        run.side_effect = subprocess.TimeoutExpired("mdfind", 5)
    elif outcome == "missing_binary":
        run.side_effect = FileNotFoundError("mdfind unavailable")
    else:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=7 if outcome == "failed" else 0,
            stdout="/Applications/Chrome.app\n" if outcome in {"found", "failed"} else "  \n",
        )
    monkeypatch.setattr("magi.availability.checks.subprocess.run", run)
    ok, detail = check_app_installed(req)
    run.assert_called_once_with(
        ["mdfind", "kMDItemCFBundleIdentifier == 'com.google.Chrome'"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert ok is (outcome == "found")
    if outcome == "found":
        assert detail is None
    elif outcome == "empty":
        assert detail == "bundle id not installed: com.google.Chrome"
    elif outcome == "failed":
        assert detail == "mdfind exit 7"
    else:
        assert detail.startswith("mdfind failed:")


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


@pytest.mark.parametrize(
    "platform,identifiers,detail",
    [
        ("win32", {"win32": "Google Chrome"}, "windows app detection not yet implemented"),
        ("linux", {"darwin": "com.google.Chrome"}, "no identifier declared for platform 'linux'"),
        (
            "unsupported",
            {"unsupported": "Chrome"},
            "app_installed check not supported on unsupported",
        ),
    ],
)
def test_app_probe_reports_unsupported_or_missing_platform_without_searching(
    monkeypatch, platform, identifiers, detail
):
    from unittest.mock import Mock

    monkeypatch.setattr("magi.availability.checks._current_platform_key", lambda: platform)
    process = Mock()
    disk = Mock()
    monkeypatch.setattr("magi.availability.checks.subprocess.run", process)
    monkeypatch.setattr(Path, "exists", disk)
    req = LocalRequirementAppInstalled(
        check_kind="app_installed", identifier_per_platform=identifiers
    )
    assert check_app_installed(req) == (False, detail)
    process.assert_not_called()
    disk.assert_not_called()
