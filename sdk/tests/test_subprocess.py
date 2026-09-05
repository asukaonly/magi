"""Tests for subprocess lifecycle helpers."""

from __future__ import annotations

import asyncio
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from magi_plugin_sdk import subprocess as managed_subprocess


def test_hidden_process_kwargs_is_empty_off_windows(monkeypatch) -> None:
    monkeypatch.setattr(managed_subprocess.os, "name", "posix")

    assert managed_subprocess.hidden_process_kwargs() == {}


def test_hidden_process_kwargs_hides_windows_console(monkeypatch) -> None:
    class FakeStartupInfo:
        def __init__(self) -> None:
            self.dwFlags = 0
            self.wShowWindow = -1

    monkeypatch.setattr(managed_subprocess.os, "name", "nt")
    monkeypatch.setattr(
        managed_subprocess.subprocess,
        "STARTUPINFO",
        FakeStartupInfo,
        raising=False,
    )
    monkeypatch.setattr(
        managed_subprocess.subprocess,
        "STARTF_USESHOWWINDOW",
        1,
        raising=False,
    )
    monkeypatch.setattr(
        managed_subprocess.subprocess,
        "SW_HIDE",
        0,
        raising=False,
    )
    monkeypatch.setattr(
        managed_subprocess.subprocess,
        "CREATE_NO_WINDOW",
        0x08000000,
        raising=False,
    )

    kwargs = managed_subprocess.hidden_process_kwargs()

    assert kwargs["creationflags"] == 0x08000000
    assert kwargs["startupinfo"].dwFlags == 1
    assert kwargs["startupinfo"].wShowWindow == 0


@pytest.mark.parametrize(
    ("exit_code", "expected"),
    [
        (managed_subprocess._STILL_ACTIVE, True),
        (0, False),
    ],
)
def test_windows_pid_probe_is_read_only(
    monkeypatch: pytest.MonkeyPatch,
    exit_code: int,
    expected: bool,
) -> None:
    calls: list[tuple[str, int]] = []

    class FakeKernel32:
        @staticmethod
        def OpenProcess(access: int, inherit: int, pid: int) -> int:
            calls.append(("open", access))
            assert inherit == 0
            assert pid == 42
            return 123

        @staticmethod
        def GetExitCodeProcess(handle: int, output: object) -> int:
            assert handle == 123
            output._obj.value = exit_code  # type: ignore[attr-defined]
            return 1

        @staticmethod
        def CloseHandle(handle: int) -> int:
            calls.append(("close", handle))
            return 1

    monkeypatch.setattr(managed_subprocess.os, "name", "nt")
    monkeypatch.setattr(managed_subprocess, "_windows_kernel32", lambda: FakeKernel32())

    assert managed_subprocess._pid_alive(42) is expected
    assert calls == [
        ("open", managed_subprocess._PROCESS_QUERY_LIMITED_INFORMATION),
        ("close", 123),
    ]


def _cleanup_spills(*paths: Path | None) -> None:
    parents = {path.parent for path in paths if path is not None}
    for parent in parents:
        shutil.rmtree(parent, ignore_errors=True)


def _heartbeat_script(
    pid_path: Path,
    heartbeat_path: Path,
    *,
    root_exits_first: bool = False,
) -> str:
    child = (
        "import pathlib,sys,time; "
        "path=pathlib.Path(sys.argv[1]); "
        "[(path.write_text(str(time.time()), encoding='utf-8'), time.sleep(0.05)) "
        "for _ in iter(int, 1)]"
    )
    script = (
        "import pathlib,subprocess,sys,time; "
        f"child=subprocess.Popen([sys.executable, '-c', {child!r}, {str(heartbeat_path)!r}]); "
        f"pathlib.Path({str(pid_path)!r}).write_text(str(child.pid), encoding='utf-8'); "
        "print(child.pid, flush=True)"
    )
    if not root_exits_first:
        script += "; time.sleep(60)"
    return script


async def _wait_for_path(path: Path, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not path.exists():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"Timed out waiting for {path}")
        await asyncio.sleep(0.02)


async def _assert_heartbeat_stopped(path: Path) -> None:
    await _wait_for_path(path)
    await asyncio.sleep(0.15)
    first = path.read_text(encoding="utf-8")
    await asyncio.sleep(0.2)
    assert path.read_text(encoding="utf-8") == first


def _force_kill_for_test(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **managed_subprocess.hidden_process_kwargs(),
        )
        return
    try:
        os.kill(pid, 9)
    except ProcessLookupError:
        pass


@pytest.mark.asyncio
async def test_bounded_runner_captures_utf8_streams() -> None:
    script = (
        "import sys; "
        "sys.stdout.buffer.write('输出-OK'.encode('utf-8')); "
        "sys.stderr.buffer.write('错误-OK'.encode('utf-8'))"
    )

    result = await managed_subprocess.run_bounded_subprocess(
        [sys.executable, "-c", script],
        shell=False,
        timeout=5,
    )

    assert result.returncode == 0
    assert result.timed_out is False
    assert result.stdout.tail.decode("utf-8") == "输出-OK"
    assert result.stderr.tail.decode("utf-8") == "错误-OK"
    assert result.stdout.total_bytes == len("输出-OK".encode())
    assert result.stderr.total_bytes == len("错误-OK".encode())
    assert result.stdout.truncated is False
    assert result.stderr.truncated is False
    assert result.stdout.spill_path is None
    assert result.stderr.spill_path is None


@pytest.mark.asyncio
async def test_bounded_runner_drains_streams_concurrently() -> None:
    stream_bytes = 512 * 1024
    script = (
        "import sys; "
        f"sys.stdout.buffer.write(b'o' * {stream_bytes}); sys.stdout.flush(); "
        f"sys.stderr.buffer.write(b'e' * {stream_bytes}); sys.stderr.flush()"
    )

    result = await managed_subprocess.run_bounded_subprocess(
        [sys.executable, "-c", script],
        shell=False,
        timeout=10,
        max_output_bytes=1024,
        max_spill_bytes=0,
    )

    assert result.returncode == 0
    assert result.stdout.total_bytes == stream_bytes
    assert result.stderr.total_bytes == stream_bytes
    assert result.stdout.tail == b"o" * 1024
    assert result.stderr.tail == b"e" * 1024


@pytest.mark.asyncio
async def test_bounded_runner_keeps_complete_spill_with_private_permissions() -> None:
    payload = b"0123456789"
    script = f"import sys; sys.stdout.buffer.write({payload!r})"

    result = await managed_subprocess.run_bounded_subprocess(
        [sys.executable, "-c", script],
        shell=False,
        timeout=5,
        max_output_bytes=4,
        max_spill_bytes=100,
    )

    spill_path = result.stdout.spill_path
    try:
        assert result.stdout.tail == b"6789"
        assert result.stdout.total_bytes == 10
        assert result.stdout.truncated is True
        assert spill_path is not None
        assert spill_path.read_bytes() == payload
        if os.name != "nt":
            assert stat.S_IMODE(spill_path.parent.stat().st_mode) == 0o700
            assert stat.S_IMODE(spill_path.stat().st_mode) == 0o600
    finally:
        _cleanup_spills(spill_path, result.stderr.spill_path)


def test_capture_deletes_spill_once_stream_exceeds_cap() -> None:
    directory = managed_subprocess._SpillDirectory()
    capture = managed_subprocess._BoundedStreamCapture(
        name="stdout",
        max_tail_bytes=4,
        max_spill_bytes=8,
        spill_directory=directory,
    )
    capture.feed(b"123456")
    spill_path = directory.path / "stdout.bin"
    assert spill_path.exists()

    capture.feed(b"789")
    capture.mark_eof()
    output = capture.finalize(keep_complete_spill=True)
    directory.remove_if_empty()

    assert output.tail == b"6789"
    assert output.total_bytes == 9
    assert output.truncated is True
    assert output.spill_path is None
    assert not spill_path.exists()
    assert directory.path is not None
    assert not directory.path.exists()


@pytest.mark.asyncio
async def test_bounded_runner_returns_partial_output_on_timeout() -> None:
    script = (
        "import sys,time; "
        "sys.stdout.buffer.write('开始'.encode('utf-8')); sys.stdout.flush(); "
        "time.sleep(60)"
    )

    result = await managed_subprocess.run_bounded_subprocess(
        [sys.executable, "-c", script],
        shell=False,
        timeout=0.3,
        terminate_grace_seconds=0.1,
    )

    assert result.timed_out is True
    assert result.returncode != 0
    assert result.stdout.tail.decode("utf-8") == "开始"
    assert result.stdout.total_bytes == len("开始".encode())


@pytest.mark.asyncio
async def test_timeout_terminates_descendant_process(tmp_path: Path) -> None:
    pid_path = tmp_path / "timeout-child.pid"
    heartbeat_path = tmp_path / "timeout-heartbeat.txt"
    script = _heartbeat_script(pid_path, heartbeat_path)

    result = await managed_subprocess.run_bounded_subprocess(
        [sys.executable, "-c", script],
        shell=False,
        timeout=0.5,
        terminate_grace_seconds=0.1,
    )

    child_pid = int(pid_path.read_text(encoding="utf-8"))
    try:
        assert result.timed_out is True
        await _assert_heartbeat_stopped(heartbeat_path)
    finally:
        _force_kill_for_test(child_pid)


@pytest.mark.asyncio
async def test_timeout_terminates_descendant_after_root_exits(tmp_path: Path) -> None:
    pid_path = tmp_path / "orphan-timeout-child.pid"
    heartbeat_path = tmp_path / "orphan-timeout-heartbeat.txt"
    script = _heartbeat_script(pid_path, heartbeat_path, root_exits_first=True)

    result = await managed_subprocess.run_bounded_subprocess(
        [sys.executable, "-c", script],
        shell=False,
        timeout=0.5,
        terminate_grace_seconds=0.1,
    )

    child_pid = int(pid_path.read_text(encoding="utf-8"))
    try:
        assert result.timed_out is True
        assert result.returncode == 0
        await _assert_heartbeat_stopped(heartbeat_path)
    finally:
        _force_kill_for_test(child_pid)


@pytest.mark.asyncio
async def test_successful_root_exit_terminates_detached_descendant(tmp_path: Path) -> None:
    pid_path = tmp_path / "success-child.pid"
    heartbeat_path = tmp_path / "success-heartbeat.txt"
    child = (
        "import pathlib,sys,time; "
        "path=pathlib.Path(sys.argv[1]); "
        "[(path.write_text(str(time.time()), encoding='utf-8'), time.sleep(0.05)) "
        "for _ in iter(int, 1)]"
    )
    script = (
        "import pathlib,subprocess,sys,time; "
        f"child=subprocess.Popen([sys.executable, '-c', {child!r}, "
        f"{str(heartbeat_path)!r}], stdin=subprocess.DEVNULL, "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
        "time.sleep(0.2); "
        f"pathlib.Path({str(pid_path)!r}).write_text(str(child.pid), encoding='utf-8')"
    )

    result = await managed_subprocess.run_bounded_subprocess(
        [sys.executable, "-c", script],
        shell=False,
        timeout=5,
        terminate_grace_seconds=0.1,
    )

    child_pid = int(pid_path.read_text(encoding="utf-8"))
    try:
        assert result.timed_out is False
        assert result.returncode == 0
        await _assert_heartbeat_stopped(heartbeat_path)
    finally:
        _force_kill_for_test(child_pid)


@pytest.mark.asyncio
async def test_cancellation_terminates_descendant_and_is_reraised(
    tmp_path: Path,
) -> None:
    pid_path = tmp_path / "cancel-child.pid"
    heartbeat_path = tmp_path / "cancel-heartbeat.txt"
    script = _heartbeat_script(pid_path, heartbeat_path)
    task = asyncio.create_task(
        managed_subprocess.run_bounded_subprocess(
            [sys.executable, "-c", script],
            shell=False,
            timeout=60,
            terminate_grace_seconds=0.1,
        )
    )

    await _wait_for_path(pid_path)
    child_pid = int(pid_path.read_text(encoding="utf-8"))
    await _wait_for_path(heartbeat_path)
    task.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await task
        await _assert_heartbeat_stopped(heartbeat_path)
    finally:
        _force_kill_for_test(child_pid)


@pytest.mark.asyncio
async def test_cancellation_terminates_descendant_after_root_exits(
    tmp_path: Path,
) -> None:
    pid_path = tmp_path / "orphan-cancel-child.pid"
    heartbeat_path = tmp_path / "orphan-cancel-heartbeat.txt"
    script = _heartbeat_script(pid_path, heartbeat_path, root_exits_first=True)
    task = asyncio.create_task(
        managed_subprocess.run_bounded_subprocess(
            [sys.executable, "-c", script],
            shell=False,
            timeout=60,
            terminate_grace_seconds=0.1,
        )
    )

    await _wait_for_path(pid_path)
    await _wait_for_path(heartbeat_path)
    child_pid = int(pid_path.read_text(encoding="utf-8"))
    await asyncio.sleep(0.15)
    task.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await task
        await _assert_heartbeat_stopped(heartbeat_path)
    finally:
        _force_kill_for_test(child_pid)


@pytest.mark.asyncio
async def test_settle_completion_cancels_siblings_after_component_error() -> None:
    sibling_cancelled = asyncio.Event()

    async def fail() -> None:
        raise RuntimeError("drain failed")

    async def wait_forever() -> None:
        try:
            await asyncio.Future()
        finally:
            sibling_cancelled.set()

    failed_task = asyncio.create_task(fail())
    sibling_task = asyncio.create_task(wait_forever())
    component_tasks = (failed_task, sibling_task)
    completion = asyncio.gather(*component_tasks)
    await asyncio.sleep(0)

    await managed_subprocess._settle_completion(completion, component_tasks)

    assert sibling_task.cancelled()
    assert sibling_cancelled.is_set()


@pytest.mark.asyncio
async def test_cancellation_removes_unreturned_spill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_directories: list[Path] = []

    def fake_mkdtemp(*, prefix: str) -> str:
        path = tmp_path / f"{prefix}{len(created_directories)}"
        path.mkdir(mode=0o700)
        created_directories.append(path)
        return str(path)

    monkeypatch.setattr(managed_subprocess.tempfile, "mkdtemp", fake_mkdtemp)
    ready_path = tmp_path / "spill-ready.txt"
    script = (
        "import pathlib,sys,time; "
        "sys.stdout.buffer.write(b'x' * 100); sys.stdout.flush(); "
        f"pathlib.Path({str(ready_path)!r}).write_text('ready', encoding='utf-8'); "
        "time.sleep(60)"
    )
    task = asyncio.create_task(
        managed_subprocess.run_bounded_subprocess(
            [sys.executable, "-c", script],
            shell=False,
            timeout=60,
            max_output_bytes=4,
            max_spill_bytes=1024,
            terminate_grace_seconds=0.1,
        )
    )

    await _wait_for_path(ready_path)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert created_directories
    assert all(not path.exists() for path in created_directories)


@pytest.mark.asyncio
async def test_windows_taskkill_helper_is_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    class FakeHelper:
        async def wait(self) -> int:
            return 0

    async def fake_create(*command: str, **kwargs: object) -> FakeHelper:
        calls.append((command, kwargs))
        return FakeHelper()

    monkeypatch.setattr(
        managed_subprocess.asyncio, "create_subprocess_exec", fake_create
    )
    monkeypatch.setattr(
        managed_subprocess,
        "hidden_process_kwargs",
        lambda: {"creationflags": 0x08000000, "startupinfo": "hidden"},
    )

    succeeded = await managed_subprocess._run_windows_taskkill(42, force=True)

    assert succeeded is True
    command, kwargs = calls[0]
    assert command == ("taskkill", "/PID", "42", "/T", "/F")
    assert kwargs["creationflags"] == 0x08000000
    assert kwargs["startupinfo"] == "hidden"


def test_windows_orphan_termination_uses_hidden_tree_kill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command: list[str], **kwargs: object) -> object:
        calls.append((command, kwargs))
        return object()

    monkeypatch.setattr(managed_subprocess.os, "name", "nt")
    monkeypatch.setattr(managed_subprocess.subprocess, "run", fake_run)
    monkeypatch.setattr(
        managed_subprocess,
        "hidden_process_kwargs",
        lambda: {"creationflags": 0x08000000, "startupinfo": "hidden"},
    )

    managed_subprocess._terminate_registered_orphan(42, force=False)
    managed_subprocess._terminate_registered_orphan(42, force=True)

    assert calls[0][0] == ["taskkill", "/PID", "42", "/T"]
    assert calls[1][0] == ["taskkill", "/PID", "42", "/T", "/F"]
    for _, kwargs in calls:
        assert kwargs["creationflags"] == 0x08000000
        assert kwargs["startupinfo"] == "hidden"
        assert kwargs["stdin"] is subprocess.DEVNULL
