"""Tests for code_agent contracts."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from magi.tools.code_agent.contracts import (
    DelegateConstraints,
    DelegateRequest,
    ProbeResult,
    RunEvent,
)


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


def test_run_event_validates_kind():
    RunEvent(kind="stdout", ts_ms=1, payload={"line": "hi"})
    with pytest.raises(ValidationError):
        RunEvent(kind="not-a-kind", ts_ms=1, payload={})  # type: ignore[arg-type]
