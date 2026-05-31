from pathlib import Path

import pytest

from magi.plugins.installation import (
    UnlockedDependencyError,
    _build_dependency_install_command,
    _resolve_lock_or_policy,
)


def test_build_command_uses_require_hashes_and_lockfile(tmp_path: Path) -> None:
    deps_dir = tmp_path / ".deps"
    lock = tmp_path / "requirements.lock"
    lock.write_text("segno==1.6.1 --hash=sha256:abc\n")

    cmd = _build_dependency_install_command(lock, deps_dir, quiet=True)

    assert "--require-hashes" in cmd
    assert "-r" in cmd
    assert str(lock) in cmd
    assert "--target" in cmd
    assert str(deps_dir) in cmd
    # user mirror config must keep working: never hard-code an index
    assert "--index-url" not in cmd
    assert "-i" not in cmd


def test_lock_present_returns_lock_path(tmp_path: Path) -> None:
    lock = tmp_path / "requirements.lock"
    lock.write_text("segno==1.6.1 --hash=sha256:abc\n")
    result = _resolve_lock_or_policy(["segno>=1.6.1"], tmp_path, allow_unlocked=False)
    assert result == lock


def test_no_deps_returns_none(tmp_path: Path) -> None:
    assert _resolve_lock_or_policy([], tmp_path, allow_unlocked=False) is None


def test_deps_without_lock_rejected_by_default(tmp_path: Path) -> None:
    with pytest.raises(UnlockedDependencyError):
        _resolve_lock_or_policy(["segno>=1.6.1"], tmp_path, allow_unlocked=False)


def test_deps_without_lock_allowed_in_developer_mode(tmp_path: Path) -> None:
    result = _resolve_lock_or_policy(["segno>=1.6.1"], tmp_path, allow_unlocked=True)
    assert result == ["segno>=1.6.1"]


import subprocess as _subprocess


def test_require_hashes_rejects_tampered_lock(tmp_path: Path) -> None:
    """A lockfile whose hash does not match the real artifact must fail install.

    This is the core supply-chain property: a poisoned/mismatched artifact is
    refused by pip before it lands in .deps/.
    """
    deps_dir = tmp_path / ".deps"
    lock = tmp_path / "requirements.lock"
    # Real package name + version, deliberately WRONG hash.
    lock.write_text(
        "segno==1.6.1 "
        "--hash=sha256:0000000000000000000000000000000000000000000000000000000000000000\n"
    )
    cmd = _build_dependency_install_command(lock, deps_dir, quiet=True)
    proc = _subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    assert proc.returncode != 0
    assert "hash" in (proc.stdout + proc.stderr).lower()
    assert not deps_dir.exists() or not any(deps_dir.iterdir())
