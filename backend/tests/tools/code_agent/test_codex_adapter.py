"""Tests for CodexAdapter using a fake `codex` binary."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from magi.tools.code_agent.adapters.base import CancelToken
from magi.tools.code_agent.adapters.codex import CodexAdapter
from magi.tools.code_agent.contracts import DelegateConstraints, DelegateRequest, RunEvent


def _make_fake_codex(
    dir_path: Path,
    stdout: str,
    last_message: str = "",
    exit_code: int = 0,
) -> Path:
    """Write a fake codex shim that:

    * Reads -o <path> from argv (writes last_message to it).
    * Ignores other flags.
    * Prints stdout, exits with exit_code.
    """
    dir_path.mkdir(parents=True, exist_ok=True)
    target = dir_path / "codex"
    encoded_stdout = stdout.replace("\\", "\\\\").replace('"', '\\"')
    encoded_msg = last_message.replace("\\", "\\\\").replace('"', '\\"')
    target.write_text(
        "#!/bin/sh\n"
        "out_file=\n"
        "while [ \"$1\" != \"\" ]; do\n"
        "  case \"$1\" in\n"
        "    -o) out_file=\"$2\"; shift 2;;\n"
        "    --output-last-message) out_file=\"$2\"; shift 2;;\n"
        "    -) shift;;\n"
        "    *) shift;;\n"
        "  esac\n"
        "done\n"
        "cat > /dev/null\n"
        f"if [ -n \"$out_file\" ]; then printf \"%s\" \"{encoded_msg}\" > \"$out_file\"; fi\n"
        f'printf "%s" "{encoded_stdout}"\n'
        f"exit {exit_code}\n"
    )
    target.chmod(0o755)
    return target


def _make_env_node_codex_launcher(root_dir: Path) -> Path:
    node_bin = root_dir / "bin"
    node_bin.mkdir(parents=True, exist_ok=True)
    node = node_bin / "node"
    node.write_text(
        "#!/bin/sh\n"
        "out_file=\n"
        "script_path=\"$1\"\n"
        "shift\n"
        "while [ \"$1\" != \"\" ]; do\n"
        "  case \"$1\" in\n"
        "    -o) out_file=\"$2\"; shift 2;;\n"
        "    --output-last-message) out_file=\"$2\"; shift 2;;\n"
        "    -) shift;;\n"
        "    *) shift;;\n"
        "  esac\n"
        "done\n"
        "cat > /dev/null\n"
        "if [ -n \"$out_file\" ]; then printf \"%s\" \"Done from env-node shim.\" > \"$out_file\"; fi\n"
        "printf '%s\\n' '{\"type\":\"task_finished\",\"ok\":true}'\n"
        "exit 0\n"
    )
    node.chmod(0o755)

    launcher_dir = root_dir / "lib" / "node_modules" / "@openai" / "codex" / "bin"
    launcher_dir.mkdir(parents=True, exist_ok=True)
    launcher = launcher_dir / "codex"
    launcher.write_text("#!/usr/bin/env node\n// fake codex launcher\n")
    launcher.chmod(0o755)
    return launcher


def _request(tmp_path: Path) -> DelegateRequest:
    return DelegateRequest(
        delegation_id="b" * 32,
        session_id="s1",
        turn_id="turn-1",
        adapter="codex",
        prompt="add max_retries to connect()",
        files_hint=["src/net.py"],
        workspace_root=str(tmp_path),
        constraints=DelegateConstraints(),
        timeout_s=30,
        model=None,
    )


async def _noop_on_event(ev: RunEvent) -> None:
    return None


def test_codex_adapter_targets_isolated_worktree(tmp_path: Path) -> None:
    adapter = CodexAdapter()
    worktree = tmp_path / "isolated-worktree"
    argv = adapter._build_argv(
        _request(tmp_path),
        bundle_dir=tmp_path / "_bundle",
        binary_path="/usr/bin/codex",
        last_message_path=tmp_path / "last.txt",
        working_directory=worktree,
    )

    assert argv[argv.index("--cd") + 1] == str(worktree)
    assert str(tmp_path) != str(worktree)


@pytest.mark.asyncio
async def test_codex_adapter_summary_from_last_message(tmp_path: Path) -> None:
    transcript = "\n".join([
        json.dumps({"type": "agent_message", "text": "starting"}),
        json.dumps({"type": "task_finished", "ok": True}),
    ]) + "\n"
    bin_dir = tmp_path / "bin"
    fake = _make_fake_codex(bin_dir, transcript, last_message="Done. Edited src/net.py.")
    cwd = tmp_path / "cwd"
    cwd.mkdir()

    events: list[RunEvent] = []

    async def on_event(ev: RunEvent) -> None:
        events.append(ev)

    adapter = CodexAdapter()
    outcome = await adapter.run(
        _request(tmp_path),
        cwd=cwd,
        bundle_dir=tmp_path / "_bundle",
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        on_event=on_event,
        cancel_token=CancelToken(),
        binary_path=str(fake),
    )
    assert outcome.exit_code == 0
    assert outcome.summary == "Done. Edited src/net.py."
    assert outcome.cost is None


@pytest.mark.asyncio
async def test_codex_adapter_records_nonzero_exit(tmp_path: Path) -> None:
    fake = _make_fake_codex(tmp_path / "bin", "", exit_code=3)
    adapter = CodexAdapter()
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
    assert outcome.exit_code == 3
    assert outcome.error is not None


@pytest.mark.asyncio
async def test_codex_adapter_persists_logs(tmp_path: Path) -> None:
    fake = _make_fake_codex(tmp_path / "bin", "{\"type\":\"task_finished\"}\n")
    stdout_path = tmp_path / "stdout.log"
    stderr_path = tmp_path / "stderr.log"
    adapter = CodexAdapter()
    await adapter.run(
        _request(tmp_path),
        cwd=tmp_path,
        bundle_dir=tmp_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        on_event=_noop_on_event,
        cancel_token=CancelToken(),
        binary_path=str(fake),
    )
    assert stdout_path.is_file()
    assert "task_finished" in stdout_path.read_text()


@pytest.mark.asyncio
async def test_codex_adapter_surfaces_stderr_in_error(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    target = bin_dir / "codex"
    target.write_text(
        "#!/bin/sh\n"
        "cat > /dev/null\n"
        ">&2 echo 'fatal: workspace not allowed'\n"
        "exit 1\n"
    )
    target.chmod(0o755)

    events: list[RunEvent] = []

    async def on_event(ev: RunEvent) -> None:
        events.append(ev)

    adapter = CodexAdapter()
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
    assert "workspace not allowed" in outcome.error
    error_events = [e for e in events if e.kind == "error"]
    assert error_events
    assert "workspace not allowed" in error_events[-1].payload.get("message", "")


@pytest.mark.asyncio
async def test_codex_adapter_runs_env_node_launcher_with_stripped_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher = _make_env_node_codex_launcher(
        tmp_path / "nvm" / "versions" / "node" / "v25.5.0"
    )
    monkeypatch.setenv("PATH", os.pathsep.join(["/usr/bin", "/bin"]))

    adapter = CodexAdapter()
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
    assert outcome.summary == "Done from env-node shim."
