"""Tests for code_agent CLI probe."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from magi.tools.code_agent.contracts import ProbeResult
from magi.tools.code_agent.probe import (
    PROBE_CACHE_TTL_S,
    load_probe_cache,
    probe_all,
    probe_one,
    save_probe_cache,
)


@pytest.fixture
def isolated_magi_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("MAGI_HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


def _make_fake_binary(dir_path: Path, name: str, exit_code: int = 0, stdout: str = "1.2.3") -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        target = dir_path / f"{name}.cmd"
        target.write_text(f"@echo off\necho {stdout}\nexit /b {exit_code}\n")
    else:
        target = dir_path / name
        target.write_text(f"#!/bin/sh\necho {stdout}\nexit {exit_code}\n")
        target.chmod(0o755)
    return target


def test_probe_one_finds_real_binary(
    isolated_magi_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_dir = tmp_path / "bin"
    fake = _make_fake_binary(bin_dir, "claude")
    monkeypatch.setenv("PATH", str(bin_dir))
    result = probe_one("claude_code")
    assert result.installed
    assert result.binary_path == str(fake.resolve())
    assert result.version is not None
    assert "1.2.3" in result.version
    assert result.error is None


def test_probe_one_missing_binary_returns_not_installed(
    isolated_magi_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "/definitely/not/a/real/path")
    result = probe_one("codex")
    assert not result.installed
    assert result.binary_path is None
    assert result.error and ("not found" in result.error.lower() or "path" in result.error.lower())


def test_probe_one_handles_nonzero_exit_as_installed_no_version(
    isolated_magi_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_dir = tmp_path / "bin"
    _make_fake_binary(bin_dir, "claude", exit_code=1, stdout="garbage")
    monkeypatch.setenv("PATH", str(bin_dir))
    result = probe_one("claude_code")
    assert result.installed
    assert result.error is not None


def test_probe_one_settings_override_path_wins(
    isolated_magi_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pinned = _make_fake_binary(tmp_path / "alt", "anything-name", stdout="9.9.9")
    monkeypatch.setenv("PATH", "/nope")
    result = probe_one("codex", binary_path_override=str(pinned))
    assert result.installed
    assert result.binary_path == str(pinned.resolve())
    assert "9.9.9" in (result.version or "")


def test_probe_all_returns_both_adapters(
    isolated_magi_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "/nope")
    out = probe_all(force=True)
    assert set(out.keys()) == {"claude_code", "codex"}
    assert all(isinstance(p, ProbeResult) for p in out.values())


def test_probe_cache_round_trip(isolated_magi_home: Path) -> None:
    payload = {
        "claude_code": ProbeResult(
            name="claude_code", installed=True, binary_path="/x", version="1",
            detected_at=1, error=None, extras={},
        ),
        "codex": ProbeResult(
            name="codex", installed=False, binary_path=None, version=None,
            detected_at=2, error="missing", extras={},
        ),
    }
    save_probe_cache(payload)
    loaded = load_probe_cache()
    assert loaded is not None
    assert loaded["claude_code"].binary_path == "/x"
    assert loaded["codex"].error == "missing"


def test_probe_cache_returns_none_when_missing(isolated_magi_home: Path) -> None:
    assert load_probe_cache() is None


def test_probe_all_uses_cache_when_fresh(
    isolated_magi_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time
    fresh_at = int(time.time() * 1000)
    save_probe_cache({
        "claude_code": ProbeResult(
            name="claude_code", installed=True, binary_path="/cached/claude",
            version="cached", detected_at=fresh_at, error=None, extras={},
        ),
        "codex": ProbeResult(
            name="codex", installed=True, binary_path="/cached/codex",
            version="cached", detected_at=fresh_at, error=None, extras={},
        ),
    })
    monkeypatch.setenv("PATH", "/nope")
    out = probe_all(force=False)
    assert out["claude_code"].binary_path == "/cached/claude"
    assert out["codex"].version == "cached"


def test_probe_all_force_bypasses_cache(
    isolated_magi_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time
    save_probe_cache({
        "claude_code": ProbeResult(
            name="claude_code", installed=True, binary_path="/cached",
            version="cached", detected_at=int(time.time() * 1000), error=None, extras={},
        ),
        "codex": ProbeResult(
            name="codex", installed=True, binary_path="/cached",
            version="cached", detected_at=int(time.time() * 1000), error=None, extras={},
        ),
    })
    monkeypatch.setenv("PATH", "/nope")
    out = probe_all(force=True)
    assert not out["claude_code"].installed
    assert not out["codex"].installed
