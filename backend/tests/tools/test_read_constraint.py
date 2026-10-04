"""Tests for the file-tool read-before-edit constraint helper."""
from __future__ import annotations

import pytest

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


@pytest.mark.parametrize("session_id", [None, "   "])
def test_missing_session_skips_both_cache_recording_and_guard(tmp_path, session_id, monkeypatch):
    from unittest.mock import Mock
    from magi.tools.builtin import _read_constraint

    target = tmp_path / "f.txt"
    target.write_text("hello")
    resolver = Mock(side_effect=AssertionError("No cache should be created"))
    monkeypatch.setattr(_read_constraint, "resolve_session_cache", resolver)
    ctx = _ctx(tmp_path, session_id=session_id)
    record_read_in_session(ctx, str(target))
    assert require_prior_read(ctx, str(target)) is None
    resolver.assert_not_called()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["f.txt"]


def test_external_path_is_not_cached_or_authorized_by_attempted_read(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("external")
    ctx = _ctx(workspace)
    record_read_in_session(ctx, str(outside))
    assert list(resolve_session_cache(workspace, "s1").iter_reads()) == []
    message = require_prior_read(ctx, str(outside))
    assert message is not None and str(outside) in message
    assert outside.read_text() == "external"
