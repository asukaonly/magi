"""Tests for code_agent contracts."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from magi.tools.code_agent.contracts import (
    AdapterName,
    DelegateConstraints,
    DelegateRequest,
    DelegateResult,
    DiffSnapshot,
    DiffStats,
    ProbeResult,
    RunEvent,
)


def test_probe_result_round_trip():
    p = ProbeResult(
        name="claude_code",
        installed=True,
        binary_path="/usr/local/bin/claude",
        version="2.1.126",
        detected_at=1_700_000_000_000,
        error=None,
        extras={},
    )
    assert ProbeResult.model_validate(p.model_dump()) == p


def test_probe_result_rejects_unknown_adapter_name():
    with pytest.raises(ValidationError):
        ProbeResult(
            name="some-other-cli",  # type: ignore[arg-type]
            installed=False,
            binary_path=None,
            version=None,
            detected_at=0,
            error=None,
            extras={},
        )


def test_delegate_constraints_defaults():
    c = DelegateConstraints()
    assert c.forbid_git_commit is True
    assert c.forbid_git_push is True
    assert c.forbid_paths == []
    assert c.allow_tools is None


def test_delegate_request_round_trip():
    req = DelegateRequest(
        delegation_id="d" * 32,
        session_id="s1",
        turn_id="turn-1",
        adapter="codex",
        prompt="add max_retries to connect()",
        files_hint=["src/net.py"],
        workspace_root="/repo",
        constraints=DelegateConstraints(),
        timeout_s=600,
        model=None,
    )
    assert DelegateRequest.model_validate(req.model_dump()) == req


def test_delegate_request_rejects_short_delegation_id():
    with pytest.raises(ValidationError):
        DelegateRequest(
            delegation_id="abc",
            session_id="s",
            turn_id="turn-1",
            adapter="codex",
            prompt="x",
            files_hint=[],
            workspace_root="/r",
            constraints=DelegateConstraints(),
            timeout_s=60,
            model=None,
        )


@pytest.mark.parametrize(
    "session_id",
    ["../s1", "s1/child", "s1!", "", "x" * 129],
)
def test_delegate_request_rejects_unsafe_session_id(session_id: str) -> None:
    with pytest.raises(ValidationError):
        DelegateRequest(
            delegation_id="a" * 32,
            session_id=session_id,
            turn_id="turn-1",
            adapter="codex",
            prompt="x",
            files_hint=[],
            workspace_root="/r",
            constraints=DelegateConstraints(),
            timeout_s=60,
            model=None,
        )


def test_delegate_request_canonicalizes_delegation_id() -> None:
    req = DelegateRequest(
        delegation_id="A" * 32,
        session_id="s1",
        turn_id="turn-1",
        adapter="codex",
        prompt="x",
        files_hint=[],
        workspace_root="/r",
        constraints=DelegateConstraints(),
        timeout_s=60,
        model=None,
    )
    assert req.delegation_id == "a" * 32


def test_diff_snapshot_default_empty():
    snap = DiffSnapshot(stats=DiffStats(), files_changed=[], unified_diff="", status_porcelain="")
    assert snap.stats.files_changed == 0


def test_run_event_validates_kind():
    RunEvent(kind="stdout", ts_ms=1, payload={"line": "hi"})
    with pytest.raises(ValidationError):
        RunEvent(kind="not-a-kind", ts_ms=1, payload={})  # type: ignore[arg-type]


def test_delegate_result_round_trip(tmp_path):
    res = DelegateResult(
        delegation_id="d" * 32,
        success=True,
        exit_code=0,
        duration_ms=5,
        diff_path=str(tmp_path / "x.patch"),
        diff_stats=DiffStats(files_changed=1, additions=2, deletions=1),
        files_changed=["a.py"],
        summary="done",
        logs_path=str(tmp_path / "logs"),
        events_path=str(tmp_path / "events.jsonl"),
        error=None,
        cost=None,
        adapter="claude_code",
    )
    assert DelegateResult.model_validate(res.model_dump()) == res


def test_adapter_name_literal():
    valid: list[AdapterName] = ["claude_code", "codex"]
    assert valid == ["claude_code", "codex"]
