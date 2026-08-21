"""Crash-resistant async subprocess wrapper for Magi plugins.

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
import json
import logging
import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

logger = logging.getLogger(__name__)

DEFAULT_REGISTRY_PATH = Path.home() / ".magi" / "runtime" / "child_processes.json"


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
        logger.warning("managed_subprocess.registry_read_failed path=%s err=%r", path, exc)
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
        logger.warning("managed_subprocess.registry_write_failed path=%s err=%r", path, exc)


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
                label, proc.pid, argv[0],
            )
        except Exception:
            # Registry write failed — log and continue. Worst case: this
            # child becomes an orphan on next crash, but the running
            # backend can still use it normally.
            logger.exception("managed_subprocess.register_failed label=%s pid=%d", label, proc.pid)
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
                self.label, self.proc.pid,
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
                self.label, proc.pid, rc,
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
                self.label, proc.pid, rc,
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
                self.label, proc.pid,
            )
            return -1
        logger.warning(
            "managed_subprocess.killed label=%s pid=%d rc=%d",
            self.label, proc.pid, rc,
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
                        entry.pid, expected_comm, current_comm,
                    )
                    continue

            # It's an orphan. SIGTERM then SIGKILL.
            logger.warning(
                "managed_subprocess.orphan_kill label=%s pid=%d parent_pid=%d (dead)",
                entry.label, entry.pid, entry.parent_pid,
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
    "DEFAULT_REGISTRY_PATH",
    "ManagedSubprocess",
    "RegistryEntry",
    "hidden_process_kwargs",
]
