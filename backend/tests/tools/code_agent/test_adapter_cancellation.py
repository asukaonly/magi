"""Process-level cancellation tests for external code adapters."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from magi.tools.code_agent.adapters.base import CancelToken
from magi.tools.code_agent.adapters.claude_code import ClaudeCodeAdapter
from magi.tools.code_agent.adapters.codex import CodexAdapter
from magi.tools.code_agent.contracts import (
    DelegateConstraints,
    DelegateRequest,
    RunEvent,
)


def _make_hanging_cli(directory: Path, binary_name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / binary_name
    target.write_text(
        f"#!{sys.executable}\n"
        "import os\n"
        "import time\n"
        "from pathlib import Path\n"
        "Path(os.environ['CODE_AGENT_TEST_PID_FILE']).write_text(str(os.getpid()))\n"
        "while True:\n"
        "    time.sleep(60)\n",
        encoding="utf-8",
    )
    target.chmod(0o755)
    return target


def _request(tmp_path: Path, *, adapter_name: str, delegation_id: str) -> DelegateRequest:
    return DelegateRequest(
        delegation_id=delegation_id,
        session_id="s1",
        turn_id="turn-1",
        adapter=adapter_name,
        prompt="wait until cancelled",
        files_hint=[],
        workspace_root=str(tmp_path),
        constraints=DelegateConstraints(),
        timeout_s=30,
        model=None,
    )


async def _noop_on_event(_event: RunEvent) -> None:
    return None


async def _wait_for_pid(pid_path: Path) -> int:
    for _ in range(200):
        if pid_path.is_file():
            return int(pid_path.read_text(encoding="utf-8"))
        await asyncio.sleep(0.01)
    raise AssertionError("adapter child process did not start")


def _process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


async def _assert_process_exited(pid: int) -> None:
    for _ in range(200):
        if not _process_is_alive(pid):
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"adapter child process is still alive: {pid}")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("adapter", "adapter_name", "binary_name", "delegation_id"),
    [
        (ClaudeCodeAdapter(), "claude_code", "claude", "a" * 32),
        (CodexAdapter(), "codex", "codex", "b" * 32),
    ],
)
async def test_adapter_cooperative_cancel_terminates_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    adapter: Any,
    adapter_name: str,
    binary_name: str,
    delegation_id: str,
) -> None:
    pid_path = tmp_path / "child.pid"
    monkeypatch.setenv("CODE_AGENT_TEST_PID_FILE", str(pid_path))
    monkeypatch.setenv(
        "MAGI_CHILD_PROCESS_REGISTRY",
        str(tmp_path / "children.json"),
    )
    binary = _make_hanging_cli(tmp_path / "bin", binary_name)
    cancel_token = CancelToken()

    task = asyncio.create_task(
        adapter.run(
            _request(
                tmp_path,
                adapter_name=adapter_name,
                delegation_id=delegation_id,
            ),
            cwd=tmp_path,
            bundle_dir=tmp_path,
            stdout_path=tmp_path / "stdout.log",
            stderr_path=tmp_path / "stderr.log",
            on_event=_noop_on_event,
            cancel_token=cancel_token,
            binary_path=str(binary),
        )
    )
    pid = await _wait_for_pid(pid_path)
    cancel_token.cancel("user_requested")
    outcome = await asyncio.wait_for(task, timeout=6)

    assert outcome.cancelled is True
    assert "user_requested" in (outcome.error or "")
    await _assert_process_exited(pid)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("adapter", "adapter_name", "binary_name", "delegation_id"),
    [
        (ClaudeCodeAdapter(), "claude_code", "claude", "c" * 32),
        (CodexAdapter(), "codex", "codex", "d" * 32),
    ],
)
async def test_adapter_task_cancel_terminates_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    adapter: Any,
    adapter_name: str,
    binary_name: str,
    delegation_id: str,
) -> None:
    pid_path = tmp_path / "child.pid"
    monkeypatch.setenv("CODE_AGENT_TEST_PID_FILE", str(pid_path))
    monkeypatch.setenv(
        "MAGI_CHILD_PROCESS_REGISTRY",
        str(tmp_path / "children.json"),
    )
    binary = _make_hanging_cli(tmp_path / "bin", binary_name)

    task = asyncio.create_task(
        adapter.run(
            _request(
                tmp_path,
                adapter_name=adapter_name,
                delegation_id=delegation_id,
            ),
            cwd=tmp_path,
            bundle_dir=tmp_path,
            stdout_path=tmp_path / "stdout.log",
            stderr_path=tmp_path / "stderr.log",
            on_event=_noop_on_event,
            cancel_token=CancelToken(),
            binary_path=str(binary),
        )
    )
    pid = await _wait_for_pid(pid_path)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=6)
    await _assert_process_exited(pid)
