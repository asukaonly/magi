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
    transcript = (
        "\n".join(
            [
                json.dumps({"type": "system", "subtype": "init"}),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {"content": [{"type": "text", "text": "Working on it..."}]},
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "content": [{"type": "text", "text": "Done. Edited src/net.py."}]
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "result",
                        "subtype": "success",
                        "total_cost_usd": 0.18,
                        "usage": {"input_tokens": 1000, "output_tokens": 200},
                    }
                ),
            ]
        )
        + "\n"
    )
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
    assert outcome.summary == "Done. Edited src/net.py."
    assert outcome.cost is not None
    assert outcome.cost.usd == pytest.approx(0.18)
    assert outcome.cost.input_tokens == 1000
    assert outcome.cost.output_tokens == 200
    assert [(event.kind, event.payload.get("text")) for event in events] == [
        ("assistant_text", "Working on it..."),
        ("assistant_text", "Done. Edited src/net.py."),
        ("status", None),
    ]
    assert events[-1].payload["event"] == "result"
    assert stdout_path.read_text() == transcript
    assert stderr_path.read_text() == ""


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


def test_build_argv_uses_exact_request_identity_without_session_persistence(tmp_path):
    request = _request(tmp_path).model_copy(
        update={"delegation_id": "971d75ebd3f54acdb4191a7528ff222d"}
    )
    argv = ClaudeCodeAdapter()._build_argv(
        request, bundle_dir=tmp_path, binary_path="/usr/bin/claude"
    )
    assert argv[argv.index("--session-id") + 1] == "971d75eb-d3f5-4acd-b419-1a7528ff222d"
    assert argv.count("--session-id") == 1
    assert "--no-session-persistence" in argv


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
@pytest.mark.parametrize(
    "noise",
    [
        {
            "type": "stream_event",
            "event": {"type": "content_block_delta", "delta": {"text": "secret delta"}},
        },
        {
            "type": "user",
            "message": {"content": [{"type": "tool_result", "content": "secret file"}]},
        },
        {"type": "system", "subtype": "init"},
    ],
)
async def test_claude_adapter_filters_noise_without_losing_assistant_or_result(tmp_path, noise):
    result = {
        "type": "result",
        "subtype": "success",
        "total_cost_usd": 0.05,
        "usage": {"input_tokens": 500, "output_tokens": 100},
    }
    transcript = (
        "\n".join(
            json.dumps(row)
            for row in [
                noise,
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text": "Useful message"}]},
                },
                noise,
                result,
            ]
        )
        + "\n"
    )
    fake = _make_fake_claude(tmp_path / "bin", transcript)
    events = []

    async def on_event(event):
        events.append(event)

    outcome = await ClaudeCodeAdapter().run(
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
    assert outcome.summary == "Useful message"
    assert [(event.kind, event.payload) for event in events] == [
        ("assistant_text", {"text": "Useful message"}),
        ("status", {"event": "result", "raw": result}),
    ]
    assert (tmp_path / "stdout.log").read_text() == transcript


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
