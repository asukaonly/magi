"""Tests for the file-tool read-before-edit constraint helper."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from magi_plugin_sdk.workspace_cache import resolve_session_cache
from magi.tools.builtin._read_constraint import (
    record_read_in_session,
    require_prior_read,
)


def _ctx(workspace: Path, session_id: str | None = "s1") -> SimpleNamespace:
    """Build the minimal context shape the helpers need.

    The helpers only touch ``context.workspace`` and
    ``context.env_vars.get("session_id")``; a SimpleNamespace is enough to
    keep these tests independent of the SDK BaseModel surface.
    """
    return SimpleNamespace(
        workspace=str(workspace),
        env_vars={"session_id": session_id} if session_id else {},
    )


def test_require_prior_read_allows_after_record(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("hello")
    ctx = _ctx(tmp_path)
    record_read_in_session(ctx, str(target))
    assert require_prior_read(ctx, str(target)) is None


def test_require_prior_read_blocks_when_unread(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("hello")
    ctx = _ctx(tmp_path)
    msg = require_prior_read(ctx, str(target))
    assert msg is not None
    assert "read" in msg.lower()
    assert str(target) in msg or "f.txt" in msg


def test_require_prior_read_blocks_when_content_changed_after_read(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("hello")
    ctx = _ctx(tmp_path)
    record_read_in_session(ctx, str(target))
    target.write_text("changed externally")
    msg = require_prior_read(ctx, str(target))
    assert msg is not None


def test_require_prior_read_disabled_when_no_session_id(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("hello")
    ctx = _ctx(tmp_path, session_id=None)
    assert require_prior_read(ctx, str(target)) is None


def test_require_prior_read_disabled_when_session_id_blank(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("hello")
    ctx = _ctx(tmp_path, session_id="   ")
    assert require_prior_read(ctx, str(target)) is None


def test_record_read_silent_when_no_session_id(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("hello")
    ctx = _ctx(tmp_path, session_id=None)
    record_read_in_session(ctx, str(target))


def test_record_read_silent_when_path_outside_workspace(tmp_path: Path) -> None:
    outside = tmp_path.parent / "elsewhere.txt"
    outside.write_text("x")
    inside_workspace = tmp_path / "ws"
    inside_workspace.mkdir()
    ctx = _ctx(inside_workspace)
    try:
        record_read_in_session(ctx, str(outside))
    finally:
        outside.unlink(missing_ok=True)


def test_require_prior_read_blocks_path_outside_workspace(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}_outside.txt"
    outside.write_text("x")
    ctx = _ctx(tmp_path)
    try:
        msg = require_prior_read(ctx, str(outside))
        assert msg is not None
    finally:
        outside.unlink(missing_ok=True)


def test_record_read_writes_to_session_cache(tmp_path: Path) -> None:
    target = tmp_path / "src" / "a.py"
    target.parent.mkdir()
    target.write_text("print(1)\n")
    ctx = _ctx(tmp_path, session_id="s2")
    record_read_in_session(ctx, str(target))
    sc = resolve_session_cache(tmp_path, "s2")
    paths = [r.path for r in sc.iter_reads()]
    assert "src/a.py" in paths
