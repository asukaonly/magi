"""Bounded one-shot and crash-resistant long-lived subprocess helpers.

``run_bounded_subprocess`` is the shared path for one-shot commands. It drains
stdout and stderr concurrently, keeps only a bounded tail in memory, and tears
down the entire process tree when the deadline expires or the caller is
cancelled.

The default `asyncio.create_subprocess_exec(...)` flow has a sharp edge: if
the parent process is killed unexpectedly (SIGKILL, crash, panic kernel),
the child keeps running with PPID=1. For a sensor plugin that spawns a
long-lived native helper, this means orphan processes accumulate on every
backend restart — see the screenshot_timeline incident where five
`magi-vision-helper` processes were found alive at once.

`ManagedSubprocess` fixes this with two complementary mechanisms:

1. **Per-instance graceful shutdown.** `shutdown()` closes stdin (signalling
   EOF to any stdio-protocol child), then SIGTERM, then SIGKILL — each
   step with a configurable grace period. The child is removed from the
   registry as soon as it exits.

2. **Crash recovery via a PID registry.** Every spawn writes a record to
   `~/.magi/runtime/child_processes.json` keyed by PID. On backend
   startup, `ManagedSubprocess.cleanup_orphans()` reads the registry and
   kills any process whose registered parent is no longer alive (i.e.
   the child was orphaned during the previous run).

For long-lived stdio children, the cleanest belt-and-braces is to *also*
have the child detect parent death itself (e.g. `readLine` returning nil
on stdin EOF). See screenshot_timeline's main.swift for a reference
implementation. ManagedSubprocess covers the case where the child can't
be modified (third-party CLIs like `claude`, `codex`, MCP servers).
"""

from __future__ import annotations

import asyncio
import ctypes
import json
import logging
import os
import signal
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import IO, Any, BinaryIO

logger = logging.getLogger(__name__)

DEFAULT_REGISTRY_PATH = Path.home() / ".magi" / "runtime" / "child_processes.json"
DEFAULT_OUTPUT_TAIL_BYTES = 64 * 1024
DEFAULT_OUTPUT_SPILL_BYTES = 64 * 1024 * 1024
_READ_CHUNK_BYTES = 64 * 1024
_FORCE_KILL_WAIT_SECONDS = 5.0
_CREATE_SUSPENDED = 0x00000004
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100
_THREAD_SUSPEND_RESUME = 0x0002
_TH32CS_SNAPTHREAD = 0x00000004
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _JobObjectBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("per_process_user_time_limit", ctypes.c_int64),
        ("per_job_user_time_limit", ctypes.c_int64),
        ("limit_flags", ctypes.c_uint32),
        ("minimum_working_set_size", ctypes.c_size_t),
        ("maximum_working_set_size", ctypes.c_size_t),
        ("active_process_limit", ctypes.c_uint32),
        ("affinity", ctypes.c_size_t),
        ("priority_class", ctypes.c_uint32),
        ("scheduling_class", ctypes.c_uint32),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("read_operation_count", ctypes.c_uint64),
        ("write_operation_count", ctypes.c_uint64),
        ("other_operation_count", ctypes.c_uint64),
        ("read_transfer_count", ctypes.c_uint64),
        ("write_transfer_count", ctypes.c_uint64),
        ("other_transfer_count", ctypes.c_uint64),
    ]


class _JobObjectExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("basic_limit_information", _JobObjectBasicLimitInformation),
        ("io_info", _IoCounters),
        ("process_memory_limit", ctypes.c_size_t),
        ("job_memory_limit", ctypes.c_size_t),
        ("peak_process_memory_used", ctypes.c_size_t),
        ("peak_job_memory_used", ctypes.c_size_t),
    ]


class _ThreadEntry32(ctypes.Structure):
    _fields_ = [
        ("size", ctypes.c_uint32),
        ("usage_count", ctypes.c_uint32),
        ("thread_id", ctypes.c_uint32),
        ("owner_process_id", ctypes.c_uint32),
        ("base_priority", ctypes.c_int32),
        ("priority_delta", ctypes.c_int32),
        ("flags", ctypes.c_uint32),
    ]


@cache
def _windows_kernel32() -> Any:
    """Load the small Win32 surface needed for suspended job assignment."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    kernel32.CreateJobObjectW.restype = ctypes.c_void_p
    kernel32.SetInformationJobObject.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    kernel32.SetInformationJobObject.restype = ctypes.c_int
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel32.AssignProcessToJobObject.restype = ctypes.c_int
    kernel32.CreateToolhelp32Snapshot.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel32.Thread32First.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_ThreadEntry32),
    ]
    kernel32.Thread32First.restype = ctypes.c_int
    kernel32.Thread32Next.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_ThreadEntry32),
    ]
    kernel32.Thread32Next.restype = ctypes.c_int
    kernel32.OpenThread.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenThread.restype = ctypes.c_void_p
    kernel32.ResumeThread.argtypes = [ctypes.c_void_p]
    kernel32.ResumeThread.restype = ctypes.c_uint32
    kernel32.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.TerminateJobObject.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    return kernel32


def _windows_error(operation: str) -> OSError:
    error_code = ctypes.get_last_error()
    return OSError(error_code, f"{operation} failed: {ctypes.FormatError(error_code)}")


def _close_windows_handle(kernel32: Any, handle: int | None) -> None:
    if handle:
        kernel32.CloseHandle(handle)


def _resume_suspended_process(kernel32: Any, pid: int) -> None:
    snapshot = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
    if snapshot == _INVALID_HANDLE_VALUE:
        raise _windows_error("CreateToolhelp32Snapshot")

    resumed_threads = 0
    try:
        entry = _ThreadEntry32()
        entry.size = ctypes.sizeof(entry)
        has_entry = kernel32.Thread32First(snapshot, ctypes.byref(entry))
        while has_entry:
            if entry.owner_process_id == pid:
                thread = kernel32.OpenThread(
                    _THREAD_SUSPEND_RESUME,
                    False,
                    entry.thread_id,
                )
                if not thread:
                    raise _windows_error("OpenThread")
                try:
                    if kernel32.ResumeThread(thread) == 0xFFFFFFFF:
                        raise _windows_error("ResumeThread")
                    resumed_threads += 1
                finally:
                    _close_windows_handle(kernel32, thread)
            has_entry = kernel32.Thread32Next(snapshot, ctypes.byref(entry))
    finally:
        _close_windows_handle(kernel32, snapshot)

    if resumed_threads == 0:
        raise RuntimeError(f"No suspended thread found for process {pid}")


class _WindowsJob:
    """Kill-on-close Job Object owning one complete subprocess tree."""

    def __init__(self, kernel32: Any, handle: int) -> None:
        self._kernel32 = kernel32
        self._handle: int | None = handle

    @classmethod
    def attach_and_resume(cls, pid: int) -> _WindowsJob:
        """Assign a suspended process before allowing any child creation."""
        kernel32 = _windows_kernel32()
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise _windows_error("CreateJobObjectW")

        try:
            information = _JobObjectExtendedLimitInformation()
            information.basic_limit_information.limit_flags = (
                _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            )
            configured = kernel32.SetInformationJobObject(
                job,
                _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(information),
                ctypes.sizeof(information),
            )
            if not configured:
                raise _windows_error("SetInformationJobObject")

            process_handle = kernel32.OpenProcess(
                _PROCESS_TERMINATE | _PROCESS_SET_QUOTA,
                False,
                pid,
            )
            if not process_handle:
                raise _windows_error("OpenProcess")
            try:
                if not kernel32.AssignProcessToJobObject(job, process_handle):
                    raise _windows_error("AssignProcessToJobObject")
            finally:
                _close_windows_handle(kernel32, process_handle)

            _resume_suspended_process(kernel32, pid)
            return cls(kernel32, job)
        except BaseException:
            # Kill-on-close also covers a process assigned successfully but not
            # resumed because a later setup step failed.
            _close_windows_handle(kernel32, job)
            raise

    def terminate(self) -> None:
        """Terminate every process still associated with this job."""
        if self._handle is None:
            return
        if not self._kernel32.TerminateJobObject(self._handle, 1):
            error = _windows_error("TerminateJobObject")
            logger.warning("bounded_subprocess.job_terminate_failed err=%r", error)
            self.close()

    def close(self) -> None:
        """Close the job handle, enforcing kill-on-close for any survivor."""
        handle = self._handle
        self._handle = None
        if handle and not self._kernel32.CloseHandle(handle):
            error = _windows_error("CloseHandle")
            logger.warning("bounded_subprocess.job_close_failed err=%r", error)


def hidden_process_kwargs() -> dict[str, Any]:
    """Return options that prevent transient child consoles on Windows."""
    if os.name != "nt":
        return {}

    startup_info = subprocess.STARTUPINFO()
    startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup_info.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": subprocess.CREATE_NO_WINDOW,
        "startupinfo": startup_info,
    }


@dataclass(frozen=True)
class BoundedStreamOutput:
    """Captured output for one subprocess stream.

    ``tail`` contains at most the configured in-memory limit. When output was
    truncated and the complete stream fit inside the spill limit,
    ``spill_path`` points to the full binary stream in a private temporary
    directory. The caller owns removal of that file and its parent directory.
    An incomplete spill is always removed.
    """

    tail: bytes
    total_bytes: int
    truncated: bool
    spill_path: Path | None


@dataclass(frozen=True)
class BoundedSubprocessResult:
    """Result of a bounded one-shot subprocess execution."""

    returncode: int | None
    stdout: BoundedStreamOutput
    stderr: BoundedStreamOutput
    timed_out: bool


class _SpillDirectory:
    """Lazily managed private directory shared by both captured streams."""

    def __init__(self) -> None:
        self.path: Path | None = None

    def create_file(self, name: str) -> tuple[BinaryIO, Path]:
        if self.path is None:
            self.path = Path(tempfile.mkdtemp(prefix="magi-subprocess-"))
            try:
                self.path.chmod(0o700)
            except OSError:
                logger.warning(
                    "bounded_subprocess.spill_dir_chmod_failed path=%s", self.path
                )

        path = self.path / name
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        descriptor = os.open(path, flags, 0o600)
        try:
            os.chmod(path, 0o600)
            return os.fdopen(descriptor, "wb"), path
        except BaseException:
            os.close(descriptor)
            path.unlink(missing_ok=True)
            raise

    def remove_if_empty(self) -> None:
        if self.path is None:
            return
        try:
            self.path.rmdir()
        except FileNotFoundError:
            pass
        except OSError:
            # A retained complete spill still lives in the directory.
            pass


class _BoundedStreamCapture:
    """Incremental bounded tail plus an optional complete-stream spill."""

    def __init__(
        self,
        *,
        name: str,
        max_tail_bytes: int,
        max_spill_bytes: int,
        spill_directory: _SpillDirectory,
    ) -> None:
        self._name = name
        self._max_tail_bytes = max_tail_bytes
        self._max_spill_bytes = max_spill_bytes
        self._spill_directory = spill_directory
        self._tail = bytearray()
        self._total_bytes = 0
        self._spill_bytes = 0
        self._spill_file: BinaryIO | None = None
        self._spill_path: Path | None = None
        self._spill_available = max_spill_bytes > 0
        self._reached_eof = False

    def feed(self, chunk: bytes) -> None:
        if not chunk:
            return

        self._total_bytes += len(chunk)
        if self._max_tail_bytes:
            self._tail.extend(chunk)
            overflow = len(self._tail) - self._max_tail_bytes
            if overflow > 0:
                del self._tail[:overflow]

        if not self._spill_available:
            return
        if self._spill_bytes + len(chunk) > self._max_spill_bytes:
            self._discard_spill()
            self._spill_available = False
            return
        try:
            if self._spill_file is None:
                self._spill_file, self._spill_path = self._spill_directory.create_file(
                    f"{self._name}.bin"
                )
            self._spill_file.write(chunk)
            self._spill_bytes += len(chunk)
        except OSError as exc:
            logger.warning(
                "bounded_subprocess.spill_write_failed stream=%s err=%r",
                self._name,
                exc,
            )
            self._discard_spill()
            self._spill_available = False

    def mark_eof(self) -> None:
        self._reached_eof = True

    def finalize(self, *, keep_complete_spill: bool) -> BoundedStreamOutput:
        self._close_spill()
        tail = bytes(self._tail)
        truncated = self._total_bytes > len(tail)
        complete_spill = (
            self._reached_eof
            and self._spill_available
            and self._spill_path is not None
            and self._spill_bytes == self._total_bytes
        )
        spill_path = (
            self._spill_path
            if keep_complete_spill and truncated and complete_spill
            else None
        )
        if spill_path is None:
            self._delete_spill_path()
        return BoundedStreamOutput(
            tail=tail,
            total_bytes=self._total_bytes,
            truncated=truncated,
            spill_path=spill_path,
        )

    def _close_spill(self) -> None:
        if self._spill_file is None:
            return
        spill_file = self._spill_file
        self._spill_file = None
        try:
            spill_file.close()
        except OSError as exc:
            logger.warning(
                "bounded_subprocess.spill_close_failed path=%s err=%r",
                self._spill_path,
                exc,
            )
            self._spill_available = False
            self._delete_spill_path()

    def _delete_spill_path(self) -> None:
        if self._spill_path is None:
            return
        try:
            self._spill_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning(
                "bounded_subprocess.spill_delete_failed path=%s err=%r",
                self._spill_path,
                exc,
            )
        finally:
            self._spill_path = None

    def _discard_spill(self) -> None:
        self._close_spill()
        self._delete_spill_path()


async def _drain_stream(
    reader: asyncio.StreamReader,
    capture: _BoundedStreamCapture,
) -> None:
    while True:
        chunk = await reader.read(_READ_CHUNK_BYTES)
        if not chunk:
            capture.mark_eof()
            return
        capture.feed(chunk)


def _process_group_alive(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


async def _wait_for_process_group_exit(process_group_id: int, timeout: float) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while _process_group_alive(process_group_id):
        if asyncio.get_running_loop().time() >= deadline:
            return False
        await asyncio.sleep(0.05)
    return True


async def _run_windows_taskkill(pid: int, *, force: bool) -> bool:
    """Invoke taskkill without opening a transient console window."""
    command = ["taskkill", "/PID", str(pid), "/T"]
    if force:
        command.append("/F")
    try:
        helper = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            **hidden_process_kwargs(),
        )
    except (FileNotFoundError, OSError) as exc:
        logger.warning(
            "bounded_subprocess.taskkill_start_failed pid=%d err=%r", pid, exc
        )
        return False

    try:
        returncode = await asyncio.wait_for(
            helper.wait(),
            timeout=_FORCE_KILL_WAIT_SECONDS,
        )
    except asyncio.TimeoutError:
        try:
            helper.kill()
        except ProcessLookupError:
            pass
        await helper.wait()
        return False
    return returncode == 0


async def _wait_for_process_exit(
    process: asyncio.subprocess.Process,
    timeout: float,
) -> bool:
    if process.returncode is not None:
        return True
    try:
        await asyncio.wait_for(asyncio.shield(process.wait()), timeout=timeout)
    except asyncio.TimeoutError:
        return False
    return True


async def _terminate_windows_process_tree(
    process: asyncio.subprocess.Process,
    grace_seconds: float,
    windows_job: _WindowsJob,
) -> None:
    if process.returncode is None:
        graceful_started = await _run_windows_taskkill(process.pid, force=False)
        if graceful_started:
            await _wait_for_process_exit(process, grace_seconds)

    # PID-based traversal no longer works after the root exits. The Job Object
    # remains authoritative for every descendant regardless of root lifetime.
    windows_job.terminate()
    await _wait_for_process_exit(process, _FORCE_KILL_WAIT_SECONDS)


async def _terminate_posix_process_tree(
    process: asyncio.subprocess.Process,
    grace_seconds: float,
) -> None:
    process_group_id = process.pid
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except ProcessLookupError:
        if process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass

    group_exited = await _wait_for_process_group_exit(process_group_id, grace_seconds)
    if not group_exited:
        try:
            os.killpg(process_group_id, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    await _wait_for_process_exit(process, _FORCE_KILL_WAIT_SECONDS)
    if not group_exited:
        await _wait_for_process_group_exit(process_group_id, _FORCE_KILL_WAIT_SECONDS)


async def _terminate_process_tree(
    process: asyncio.subprocess.Process,
    grace_seconds: float,
    windows_job: _WindowsJob | None,
) -> None:
    if os.name == "nt":
        if windows_job is None:
            raise RuntimeError("Windows subprocess is missing its Job Object")
        await _terminate_windows_process_tree(process, grace_seconds, windows_job)
    else:
        await _terminate_posix_process_tree(process, grace_seconds)


async def _settle_completion(
    completion: asyncio.Future[Any],
    component_tasks: Sequence[asyncio.Task[Any]],
) -> None:
    done, _ = await asyncio.wait(
        {completion},
        timeout=_FORCE_KILL_WAIT_SECONDS,
    )
    if completion not in done:
        for task in component_tasks:
            if not task.done():
                task.cancel()
    else:
        # gather() finishes immediately when one component raises and leaves
        # siblings running. Settle them before capture state is finalized.
        for task in component_tasks:
            if not task.done():
                task.cancel()
    await asyncio.gather(*component_tasks, return_exceptions=True)
    if not completion.done():
        completion.cancel()
    await asyncio.gather(completion, return_exceptions=True)


async def _terminate_and_settle(
    process: asyncio.subprocess.Process,
    completion: asyncio.Future[Any],
    component_tasks: Sequence[asyncio.Task[Any]],
    grace_seconds: float,
    windows_job: _WindowsJob | None,
) -> None:
    try:
        await _terminate_process_tree(process, grace_seconds, windows_job)
    finally:
        await _settle_completion(completion, component_tasks)


async def _shield_cleanup(cleanup: asyncio.Task[None]) -> None:
    """Wait for cleanup even if the caller receives repeated cancellation."""
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            continue
    outcomes = await asyncio.gather(cleanup, return_exceptions=True)
    if outcomes and isinstance(outcomes[0], BaseException):
        logger.warning("bounded_subprocess.cleanup_failed err=%r", outcomes[0])


def _validate_bounded_subprocess_arguments(
    *,
    command: str | Sequence[str],
    shell: bool,
    timeout: float,
    max_output_bytes: int,
    max_spill_bytes: int,
    terminate_grace_seconds: float,
) -> None:
    if shell:
        if not isinstance(command, str) or not command:
            raise ValueError("shell commands must be non-empty strings")
    else:
        if (
            isinstance(command, str)
            or not command
            or not all(isinstance(part, str) and part for part in command)
        ):
            raise ValueError("exec commands must be non-empty sequences of strings")
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    if max_output_bytes < 0:
        raise ValueError("max_output_bytes must be non-negative")
    if max_spill_bytes < 0:
        raise ValueError("max_spill_bytes must be non-negative")
    if terminate_grace_seconds < 0:
        raise ValueError("terminate_grace_seconds must be non-negative")


async def _collect_bounded_subprocess(
    process: asyncio.subprocess.Process,
    *,
    max_output_bytes: int,
    max_spill_bytes: int,
    timeout: float,
    terminate_grace_seconds: float,
    windows_job: _WindowsJob | None,
) -> BoundedSubprocessResult:
    assert process.stdout is not None
    assert process.stderr is not None
    spill_directory = _SpillDirectory()
    stdout_capture = _BoundedStreamCapture(
        name="stdout",
        max_tail_bytes=max_output_bytes,
        max_spill_bytes=max_spill_bytes,
        spill_directory=spill_directory,
    )
    stderr_capture = _BoundedStreamCapture(
        name="stderr",
        max_tail_bytes=max_output_bytes,
        max_spill_bytes=max_spill_bytes,
        spill_directory=spill_directory,
    )
    wait_task = asyncio.create_task(process.wait())
    stdout_task = asyncio.create_task(_drain_stream(process.stdout, stdout_capture))
    stderr_task = asyncio.create_task(_drain_stream(process.stderr, stderr_capture))
    component_tasks = (wait_task, stdout_task, stderr_task)
    completion = asyncio.gather(*component_tasks)
    finalized = False

    try:
        timed_out = False
        try:
            await asyncio.wait_for(asyncio.shield(completion), timeout=timeout)
        except asyncio.TimeoutError:
            timed_out = True
            await _terminate_and_settle(
                process,
                completion,
                component_tasks,
                terminate_grace_seconds,
                windows_job,
            )

        stdout = stdout_capture.finalize(keep_complete_spill=True)
        stderr = stderr_capture.finalize(keep_complete_spill=True)
        finalized = True
        spill_directory.remove_if_empty()
        return BoundedSubprocessResult(
            returncode=process.returncode,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
        )
    except asyncio.CancelledError:
        cleanup = asyncio.create_task(
            _terminate_and_settle(
                process,
                completion,
                component_tasks,
                terminate_grace_seconds,
                windows_job,
            )
        )
        await _shield_cleanup(cleanup)
        raise
    except BaseException:
        cleanup = asyncio.create_task(
            _terminate_and_settle(
                process,
                completion,
                component_tasks,
                terminate_grace_seconds,
                windows_job,
            )
        )
        await _shield_cleanup(cleanup)
        raise
    finally:
        if not finalized:
            stdout_capture.finalize(keep_complete_spill=False)
            stderr_capture.finalize(keep_complete_spill=False)
            spill_directory.remove_if_empty()


async def run_bounded_subprocess(
    command: str | Sequence[str],
    *,
    shell: bool,
    timeout: float,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    max_output_bytes: int = DEFAULT_OUTPUT_TAIL_BYTES,
    max_spill_bytes: int = DEFAULT_OUTPUT_SPILL_BYTES,
    terminate_grace_seconds: float = 3.0,
) -> BoundedSubprocessResult:
    """Run a one-shot command with bounded output and process-tree cleanup.

    Timeout returns a structured partial result. Caller cancellation is
    re-raised only after the process tree has been terminated and capture tasks
    have settled. Windows children start suspended and are assigned to a
    kill-on-close Job Object before any user code can create descendants.
    """
    _validate_bounded_subprocess_arguments(
        command=command,
        shell=shell,
        timeout=timeout,
        max_output_bytes=max_output_bytes,
        max_spill_bytes=max_spill_bytes,
        terminate_grace_seconds=terminate_grace_seconds,
    )

    spawn_kwargs: dict[str, Any] = {
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
        "cwd": cwd,
        "env": dict(env) if env is not None else None,
        **hidden_process_kwargs(),
    }
    if os.name == "nt":
        spawn_kwargs["creationflags"] = (
            int(spawn_kwargs.get("creationflags", 0)) | _CREATE_SUSPENDED
        )
    else:
        spawn_kwargs["start_new_session"] = True

    if shell:
        process = await asyncio.create_subprocess_shell(str(command), **spawn_kwargs)
    else:
        process = await asyncio.create_subprocess_exec(*command, **spawn_kwargs)

    windows_job: _WindowsJob | None = None
    if os.name == "nt":
        try:
            windows_job = _WindowsJob.attach_and_resume(process.pid)
        except BaseException:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()
            raise

    try:
        return await _collect_bounded_subprocess(
            process,
            max_output_bytes=max_output_bytes,
            max_spill_bytes=max_spill_bytes,
            timeout=timeout,
            terminate_grace_seconds=terminate_grace_seconds,
            windows_job=windows_job,
        )
    finally:
        if windows_job is not None:
            windows_job.close()


def _default_registry_path() -> Path:
    """Resolve the on-disk registry path.

    Overridable via the `MAGI_CHILD_PROCESS_REGISTRY` env var for tests
    and for non-default user-data directories.
    """
    override = os.environ.get("MAGI_CHILD_PROCESS_REGISTRY")
    return Path(override) if override else DEFAULT_REGISTRY_PATH


@dataclass(frozen=True)
class RegistryEntry:
    pid: int
    label: str
    argv0: str
    parent_pid: int
    started_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "label": self.label,
            "argv0": self.argv0,
            "parent_pid": self.parent_pid,
            "started_at": self.started_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RegistryEntry:
        return cls(
            pid=int(data["pid"]),
            label=str(data["label"]),
            argv0=str(data["argv0"]),
            parent_pid=int(data["parent_pid"]),
            started_at=float(data["started_at"]),
        )


def _load_registry(path: Path) -> list[RegistryEntry]:
    """Read the registry. Returns empty list on missing/corrupt files —
    we never want registry I/O to block boot."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        logger.warning(
            "managed_subprocess.registry_read_failed path=%s err=%r", path, exc
        )
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("managed_subprocess.registry_corrupt path=%s err=%r", path, exc)
        return []
    if not isinstance(data, list):
        logger.warning("managed_subprocess.registry_bad_shape path=%s", path)
        return []
    out: list[RegistryEntry] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            out.append(RegistryEntry.from_dict(item))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _save_registry(path: Path, entries: list[RegistryEntry]) -> None:
    """Atomic write — temp file + rename. Safe across crashes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps([e.to_dict() for e in entries], indent=2)
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        logger.warning(
            "managed_subprocess.registry_write_failed path=%s err=%r", path, exc
        )


def _register(entry: RegistryEntry, *, registry_path: Path | None = None) -> None:
    path = registry_path or _default_registry_path()
    entries = _load_registry(path)
    # Replace any stale entry with the same PID (PIDs get reused).
    entries = [e for e in entries if e.pid != entry.pid]
    entries.append(entry)
    _save_registry(path, entries)


def _unregister(pid: int, *, registry_path: Path | None = None) -> None:
    path = registry_path or _default_registry_path()
    entries = _load_registry(path)
    keep = [e for e in entries if e.pid != pid]
    if len(keep) != len(entries):
        _save_registry(path, keep)


def _pid_alive(pid: int) -> bool:
    """True if a process with this PID currently exists."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we can't signal it (probably not ours, but it's there).
        return True
    return True


def _argv0_of(pid: int) -> str | None:
    """Best-effort lookup of /proc/<pid>/comm equivalent. Returns None if
    unavailable. Used to defend against PID reuse — if the process at
    `pid` no longer matches the binary we registered, skip the kill."""
    try:
        # macOS + Linux both have `ps -p PID -o comm=`. comm gives the
        # last-path-component of argv[0], which is enough to distinguish
        # `magi-vision-helper` from an unrelated reused PID.
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "comm="],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
            **hidden_process_kwargs(),
        )
        out = result.stdout.strip()
        return out or None
    except Exception:  # noqa: BLE001
        return None


@dataclass
class ManagedSubprocess:
    """A long-lived child process whose lifetime is tracked across crashes.

    Construct via `await ManagedSubprocess.spawn(...)`. Always await
    `.shutdown()` (or rely on `cleanup_orphans()` on next boot, which is
    the whole point of this class).
    """

    label: str
    argv: list[str]
    proc: asyncio.subprocess.Process
    registry_path: Path = field(default_factory=_default_registry_path)
    _registered: bool = field(default=False, init=False)

    @classmethod
    async def spawn(
        cls,
        argv: list[str],
        *,
        label: str,
        stdin: IO | int | None = asyncio.subprocess.PIPE,
        stdout: IO | int | None = asyncio.subprocess.PIPE,
        stderr: IO | int | None = asyncio.subprocess.PIPE,
        env: dict[str, str] | None = None,
        cwd: str | os.PathLike | None = None,
        registry_path: Path | None = None,
    ) -> ManagedSubprocess:
        """Spawn `argv` and register the PID for crash-recovery cleanup.

        `label` is a short, stable identifier for the process used in
        logs and registry rows (e.g. `"screenshot_timeline.helper"` or
        `"mcp.<server-id>"`). Use the same label across restarts of the
        same logical child so that operators can correlate.
        """
        if not argv:
            raise ValueError("argv must be non-empty")
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            env=env,
            cwd=cwd,
            **hidden_process_kwargs(),
        )
        path = registry_path or _default_registry_path()
        instance = cls(
            label=label,
            argv=list(argv),
            proc=proc,
            registry_path=path,
        )
        try:
            _register(
                RegistryEntry(
                    pid=proc.pid,
                    label=label,
                    argv0=argv[0],
                    parent_pid=os.getpid(),
                    started_at=time.time(),
                ),
                registry_path=path,
            )
            instance._registered = True
            logger.info(
                "managed_subprocess.spawned label=%s pid=%d argv0=%s",
                label,
                proc.pid,
                argv[0],
            )
        except Exception:
            # Registry write failed — log and continue. Worst case: this
            # child becomes an orphan on next crash, but the running
            # backend can still use it normally.
            logger.exception(
                "managed_subprocess.register_failed label=%s pid=%d", label, proc.pid
            )
        return instance

    @property
    def pid(self) -> int:
        return self.proc.pid

    @property
    def returncode(self) -> int | None:
        return self.proc.returncode

    def _cleanup_registry(self) -> None:
        if not self._registered:
            return
        try:
            _unregister(self.proc.pid, registry_path=self.registry_path)
            self._registered = False
        except Exception:
            logger.exception(
                "managed_subprocess.unregister_failed label=%s pid=%d",
                self.label,
                self.proc.pid,
            )

    async def wait(self) -> int:
        """Wait for the process to exit. Always deregisters on return."""
        try:
            rc = await self.proc.wait()
        finally:
            self._cleanup_registry()
        return rc

    async def shutdown(
        self,
        *,
        close_stdin: bool = True,
        sigterm_grace_seconds: float = 2.0,
        sigkill_grace_seconds: float = 1.0,
    ) -> int:
        """Gracefully terminate the child.

        Sequence:
          1. Close stdin (signals EOF to stdio-protocol children).
          2. Wait `sigterm_grace_seconds` for clean exit.
          3. SIGTERM, wait `sigkill_grace_seconds`.
          4. SIGKILL.

        Returns the process exit code (which may be negative under SIGKILL).
        """
        proc = self.proc
        if proc.returncode is not None:
            self._cleanup_registry()
            return proc.returncode

        # Step 1: stdin EOF
        if close_stdin and proc.stdin is not None and not proc.stdin.is_closing():
            try:
                proc.stdin.close()
            except (BrokenPipeError, ConnectionResetError):
                pass

        # Step 2: wait for graceful exit
        try:
            rc = await asyncio.wait_for(proc.wait(), timeout=sigterm_grace_seconds)
            logger.info(
                "managed_subprocess.exited_gracefully label=%s pid=%d rc=%d",
                self.label,
                proc.pid,
                rc,
            )
            self._cleanup_registry()
            return rc
        except asyncio.TimeoutError:
            pass

        # Step 3: SIGTERM
        try:
            proc.terminate()
        except ProcessLookupError:
            self._cleanup_registry()
            return proc.returncode if proc.returncode is not None else -1
        try:
            rc = await asyncio.wait_for(proc.wait(), timeout=sigkill_grace_seconds)
            logger.info(
                "managed_subprocess.exited_after_sigterm label=%s pid=%d rc=%d",
                self.label,
                proc.pid,
                rc,
            )
            self._cleanup_registry()
            return rc
        except asyncio.TimeoutError:
            pass

        # Step 4: SIGKILL
        try:
            proc.kill()
        except ProcessLookupError:
            self._cleanup_registry()
            return proc.returncode if proc.returncode is not None else -1
        try:
            rc = await asyncio.wait_for(proc.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            # Truly stuck. Log and give up — the registry will keep the
            # entry so cleanup_orphans() can retry on next boot.
            logger.warning(
                "managed_subprocess.kill_did_not_terminate label=%s pid=%d",
                self.label,
                proc.pid,
            )
            return -1
        logger.warning(
            "managed_subprocess.killed label=%s pid=%d rc=%d",
            self.label,
            proc.pid,
            rc,
        )
        self._cleanup_registry()
        return rc

    @classmethod
    def cleanup_orphans(cls, *, registry_path: Path | None = None) -> int:
        """Scan the registry and kill orphans from prior runs.

        An entry is an orphan iff:
          - Its PID is still alive, AND
          - Its `parent_pid` is no longer alive (or is not us — pid
            reuse is possible but a parent process taking over the same
            PID is implausible enough to ignore), AND
          - The process at that PID still has a matching `argv0`
            (defense against PID reuse: if the comm name changed,
            someone else has the PID).

        Stale entries (PID gone) are simply pruned.

        Returns the number of orphans killed. Call this once during
        backend startup, BEFORE any plugin starts spawning its own
        managed subprocesses. Safe to call when the registry doesn't
        exist; safe to call multiple times.
        """
        path = registry_path or _default_registry_path()
        entries = _load_registry(path)
        if not entries:
            return 0

        my_pid = os.getpid()
        survivors: list[RegistryEntry] = []
        killed = 0

        for entry in entries:
            if not _pid_alive(entry.pid):
                # Already gone — drop the entry.
                continue
            if entry.parent_pid == my_pid:
                # This shouldn't happen at boot, but if it does, keep it.
                survivors.append(entry)
                continue
            if _pid_alive(entry.parent_pid):
                # Parent still alive (another backend instance? unlikely
                # but possible during dev). Don't touch it.
                survivors.append(entry)
                continue

            # PID-reuse defense: macOS `ps -o comm=` reports the resolved
            # framework binary (e.g. ".../Python.app/Contents/MacOS/Python"
            # for a venv-launched interpreter), so we can't expect an exact
            # match against argv[0]. Use case-insensitive substring on the
            # basename of the registered argv0: if neither name appears in
            # the current comm, treat it as PID reuse and skip the kill.
            current_comm = _argv0_of(entry.pid)
            expected_comm = Path(entry.argv0).name
            if current_comm is not None:
                lhs = current_comm.lower()
                rhs = expected_comm.lower()
                if rhs not in lhs and lhs.rsplit("/", 1)[-1] not in rhs:
                    logger.info(
                        "managed_subprocess.skip_pid_reused pid=%d expected=%s found=%s",
                        entry.pid,
                        expected_comm,
                        current_comm,
                    )
                    continue

            # It's an orphan. SIGTERM then SIGKILL.
            logger.warning(
                "managed_subprocess.orphan_kill label=%s pid=%d parent_pid=%d (dead)",
                entry.label,
                entry.pid,
                entry.parent_pid,
            )
            try:
                os.kill(entry.pid, signal.SIGTERM)
            except ProcessLookupError:
                continue
            # Brief synchronous wait — boot is the only caller, so we can
            # afford ~1s of latency before SIGKILL.
            for _ in range(20):
                time.sleep(0.05)
                if not _pid_alive(entry.pid):
                    break
            if _pid_alive(entry.pid):
                try:
                    os.kill(entry.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            killed += 1

        _save_registry(path, survivors)
        if killed:
            logger.warning("managed_subprocess.cleanup_orphans killed=%d", killed)
        return killed


__all__ = [
    "DEFAULT_OUTPUT_SPILL_BYTES",
    "DEFAULT_OUTPUT_TAIL_BYTES",
    "DEFAULT_REGISTRY_PATH",
    "BoundedStreamOutput",
    "BoundedSubprocessResult",
    "ManagedSubprocess",
    "RegistryEntry",
    "hidden_process_kwargs",
    "run_bounded_subprocess",
]
