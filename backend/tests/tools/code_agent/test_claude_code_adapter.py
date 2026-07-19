"""Tests for ClaudeCodeAdapter using a fake `claude` binary."""
from __future__ import annotations

import json
import os
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


def _make_env_node_claude_launcher(root_dir: Path, stdout: str) -> Path:
    node_bin = root_dir / "bin"
    node_bin.mkdir(parents=True, exist_ok=True)
    encoded = stdout.replace("\\", "\\\\").replace('"', '\\"')
    node = node_bin / "node"
    node.write_text(
        "#!/bin/sh\n"
        "cat > /dev/null\n"
        f'printf "%s" "{encoded}"\n'
        "exit 0\n"
    )
    node.chmod(0o755)

    launcher_dir = root_dir / "lib" / "node_modules" / "@anthropic-ai" / "claude-code" / "bin"
    launcher_dir.mkdir(parents=True, exist_ok=True)
    launcher = launcher_dir / "claude"
    launcher.write_text("#!/usr/bin/env node\n// fake claude launcher\n")
    launcher.chmod(0o755)
    return launcher


def _request(tmp_path: Path) -> DelegateRequest:
    return DelegateRequest(
        delegation_id="a" * 32,
        session_id="s1",
        turn_id="turn-1",
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


def test_format_uuid_canonicalises_hex_id() -> None:
    from magi.tools.code_agent.adapters.claude_code import _format_uuid
    raw = "971d75ebd3f54acdb4191a7528ff222d"
    assert _format_uuid(raw) == "971d75eb-d3f5-4acd-b419-1a7528ff222d"


def test_format_uuid_passes_through_invalid_input() -> None:
    from magi.tools.code_agent.adapters.claude_code import _format_uuid
    assert _format_uuid("not-a-uuid") == "not-a-uuid"


def test_build_argv_passes_uuid_session_id(tmp_path: Path) -> None:
    adapter = ClaudeCodeAdapter()
    argv = adapter._build_argv(
        _request(tmp_path),
        bundle_dir=tmp_path,
        binary_path="/usr/bin/claude",
    )
    idx = argv.index("--session-id")
    session_id = argv[idx + 1]
    # 8-4-4-4-12 hex grouping
    assert len(session_id) == 36
    assert session_id.count("-") == 4


@pytest.mark.asyncio
async def test_claude_adapter_surfaces_stderr_in_error(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    target = bin_dir / "claude"
    target.write_text(
        "#!/bin/sh\n"
        "cat > /dev/null\n"
        ">&2 echo 'Error: Invalid session ID. Must be a valid UUID.'\n"
        "exit 1\n"
    )
    target.chmod(0o755)

    events: list[RunEvent] = []

    async def on_event(ev: RunEvent) -> None:
        events.append(ev)

    adapter = ClaudeCodeAdapter()
    outcome = await adapter.run(
        _request(tmp_path),
        cwd=tmp_path,
        bundle_dir=tmp_path,
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        on_event=on_event,
        cancel_token=CancelToken(),
        binary_path=str(target),
    )
    assert outcome.exit_code == 1
    assert outcome.error is not None
    assert "Invalid session ID" in outcome.error
    error_events = [e for e in events if e.kind == "error"]
    assert error_events, "expected an error RunEvent"
    assert "Invalid session ID" in error_events[-1].payload.get("message", "")


@pytest.mark.asyncio
async def test_claude_adapter_filters_stream_events(tmp_path: Path) -> None:
    """Verify adapter drops noisy stream_event (content_block_delta) records."""
    # Simulate claude-code output with many stream_events plus a real assistant message
    transcript = "\n".join([
        json.dumps({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"text": "H"}}}),
        json.dumps({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"text": "i"}}}),
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Actual useful message"}]}}),
        json.dumps({"type": "result", "subtype": "success",
                    "total_cost_usd": 0.05,
                    "usage": {"input_tokens": 500, "output_tokens": 100}}),
    ]) + "\n"
    bin_dir = tmp_path / "bin"
    fake = _make_fake_claude(bin_dir, transcript)

    events: list[RunEvent] = []

    async def on_event(ev: RunEvent) -> None:
        events.append(ev)

    adapter = ClaudeCodeAdapter()
    outcome = await adapter.run(
        _request(tmp_path),
        cwd=tmp_path,
        bundle_dir=tmp_path,
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        on_event=on_event,
        cancel_token=CancelToken(),
        binary_path=str(fake),
    )
    assert outcome.exit_code == 0
    # Should have assistant_text but no stream_event status entries
    event_kinds = [e.kind for e in events]
    assert "assistant_text" in event_kinds
    # Count status events with stream_event payload
    stream_event_statuses = [
        e for e in events
        if e.kind == "status" and e.payload.get("event") == "stream_event"
    ]
    assert len(stream_event_statuses) == 0, "stream_event noise should be filtered"


@pytest.mark.asyncio
async def test_claude_adapter_filters_user_events(tmp_path: Path) -> None:
    """Verify adapter drops noisy user (tool_result) events."""
    # Mix of user/tool_result events and assistant message
    transcript = "\n".join([
        json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": "some file content"}]}}),
        json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": "more content"}]}}),
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Done"}]}}),
        json.dumps({"type": "result", "subtype": "success",
                    "total_cost_usd": 0.02,
                    "usage": {"input_tokens": 300, "output_tokens": 50}}),
    ]) + "\n"
    bin_dir = tmp_path / "bin"
    fake = _make_fake_claude(bin_dir, transcript)

    events: list[RunEvent] = []

    async def on_event(ev: RunEvent) -> None:
        events.append(ev)

    adapter = ClaudeCodeAdapter()
    outcome = await adapter.run(
        _request(tmp_path),
        cwd=tmp_path,
        bundle_dir=tmp_path,
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        on_event=on_event,
        cancel_token=CancelToken(),
        binary_path=str(fake),
    )
    assert outcome.exit_code == 0
    # Should have assistant_text but no user status entries
    event_kinds = [e.kind for e in events]
    assert "assistant_text" in event_kinds
    # Count status events with user payload
    user_statuses = [
        e for e in events
        if e.kind == "status" and e.payload.get("event") == "user"
    ]
    assert len(user_statuses) == 0, "user/tool_result events should be filtered"


@pytest.mark.asyncio
async def test_claude_adapter_filters_system_events(tmp_path: Path) -> None:
    """Verify adapter drops noisy system events."""
    # Mix of system events and assistant message
    transcript = "\n".join([
        json.dumps({"type": "system", "subtype": "init"}),
        json.dumps({"type": "system", "subtype": "config"}),
        json.dumps({"type": "system", "subtype": "ready"}),
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Done"}]}}),
        json.dumps({"type": "result", "subtype": "success",
                    "total_cost_usd": 0.02,
                    "usage": {"input_tokens": 300, "output_tokens": 50}}),
    ]) + "\n"
    bin_dir = tmp_path / "bin"
    fake = _make_fake_claude(bin_dir, transcript)

    events: list[RunEvent] = []

    async def on_event(ev: RunEvent) -> None:
        events.append(ev)

    adapter = ClaudeCodeAdapter()
    outcome = await adapter.run(
        _request(tmp_path),
        cwd=tmp_path,
        bundle_dir=tmp_path,
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        on_event=on_event,
        cancel_token=CancelToken(),
        binary_path=str(fake),
    )
    assert outcome.exit_code == 0
    # Should have assistant_text but no system status entries
    event_kinds = [e.kind for e in events]
    assert "assistant_text" in event_kinds
    # Count status events with system payload
    system_statuses = [
        e for e in events
        if e.kind == "status" and e.payload.get("event") == "system"
    ]
    assert len(system_statuses) == 0, "system events should be filtered"


@pytest.mark.asyncio
async def test_claude_adapter_runs_env_node_launcher_with_stripped_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transcript = json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "Done via env-node"}]},
    }) + "\n"
    transcript += json.dumps({
        "type": "result",
        "subtype": "success",
        "total_cost_usd": 0.01,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }) + "\n"
    launcher = _make_env_node_claude_launcher(
        tmp_path / "nvm" / "versions" / "node" / "v25.5.0",
        transcript,
    )
    monkeypatch.setenv("PATH", os.pathsep.join(["/usr/bin", "/bin"]))

    adapter = ClaudeCodeAdapter()
    outcome = await adapter.run(
        _request(tmp_path),
        cwd=tmp_path,
        bundle_dir=tmp_path,
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        on_event=_noop_on_event,
        cancel_token=CancelToken(),
        binary_path=str(launcher),
    )

    assert outcome.exit_code == 0
    assert outcome.summary == "Done via env-node"
