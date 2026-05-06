"""Tests for ClaudeCodeAdapter using a fake `claude` binary."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from magi.tools.code_agent.adapters.base import CancelToken
from magi.tools.code_agent.adapters.claude_code import ClaudeCodeAdapter
from magi.tools.code_agent.contracts import (
    DelegateConstraints,
    DelegateRequest,
    RunEvent,
)


def _make_fake_claude(dir_path: Path, stdout: str, exit_code: int = 0) -> Path:
    """Write a fake claude shim that ignores all flags and prints stdout."""
    dir_path.mkdir(parents=True, exist_ok=True)
    target = dir_path / "claude"
    encoded = stdout.replace("\\", "\\\\").replace('"', '\\"')
    target.write_text(
        "#!/bin/sh\n"
        "cat > /dev/null\n"
        f'printf "%s" "{encoded}"\n'
        f"exit {exit_code}\n"
    )
    target.chmod(0o755)
    return target


def _request(tmp_path: Path) -> DelegateRequest:
    return DelegateRequest(
        delegation_id="a" * 32,
        session_id="s1",
        adapter="claude_code",
        prompt="add max_retries to connect()",
        files_hint=["src/net.py"],
        workspace_root=str(tmp_path),
        constraints=DelegateConstraints(),
        timeout_s=30,
        model=None,
    )


@pytest.mark.asyncio
async def test_claude_adapter_emits_events_and_summary(tmp_path: Path) -> None:
    transcript = "\n".join([
        json.dumps({"type": "system", "subtype": "init"}),
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Working on it..."}]}}),
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Done. Edited src/net.py."}]}}),
        json.dumps({"type": "result", "subtype": "success",
                    "total_cost_usd": 0.18,
                    "usage": {"input_tokens": 1000, "output_tokens": 200}}),
    ]) + "\n"
    bin_dir = tmp_path / "bin"
    fake = _make_fake_claude(bin_dir, transcript)

    bundle_dir = tmp_path / "_bundle"
    bundle_dir.mkdir()
    stdout_path = tmp_path / "stdout.log"
    stderr_path = tmp_path / "stderr.log"
    cwd = tmp_path / "cwd"
    cwd.mkdir()

    events: list[RunEvent] = []

    async def on_event(ev: RunEvent) -> None:
        events.append(ev)

    adapter = ClaudeCodeAdapter()
    outcome = await adapter.run(
        _request(tmp_path),
        cwd=cwd,
        bundle_dir=bundle_dir,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        on_event=on_event,
        cancel_token=CancelToken(),
        binary_path=str(fake),
    )
    assert outcome.exit_code == 0
    assert outcome.summary and "Done" in outcome.summary
    assert outcome.cost is not None
    assert outcome.cost.usd == pytest.approx(0.18)
    assert outcome.cost.input_tokens == 1000
    kinds = [e.kind for e in events]
    assert "assistant_text" in kinds


async def _noop_on_event(ev: RunEvent) -> None:
    return None


@pytest.mark.asyncio
async def test_claude_adapter_records_nonzero_exit(tmp_path: Path) -> None:
    fake = _make_fake_claude(tmp_path / "bin", "", exit_code=2)
    adapter = ClaudeCodeAdapter()
    outcome = await adapter.run(
        _request(tmp_path),
        cwd=tmp_path,
        bundle_dir=tmp_path,
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        on_event=_noop_on_event,
        cancel_token=CancelToken(),
        binary_path=str(fake),
    )
    assert outcome.exit_code == 2
    assert outcome.error is not None


@pytest.mark.asyncio
async def test_claude_adapter_persists_stdout_log(tmp_path: Path) -> None:
    transcript = json.dumps({"type": "result", "subtype": "success"}) + "\n"
    fake = _make_fake_claude(tmp_path / "bin", transcript)
    stdout_path = tmp_path / "stdout.log"
    adapter = ClaudeCodeAdapter()
    await adapter.run(
        _request(tmp_path),
        cwd=tmp_path,
        bundle_dir=tmp_path,
        stdout_path=stdout_path,
        stderr_path=tmp_path / "stderr.log",
        on_event=_noop_on_event,
        cancel_token=CancelToken(),
        binary_path=str(fake),
    )
    assert stdout_path.is_file()
    assert "result" in stdout_path.read_text()
