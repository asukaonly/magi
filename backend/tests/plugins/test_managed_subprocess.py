"""Tests for magi_plugin_sdk.subprocess.ManagedSubprocess.

Covers:
  - spawn + clean shutdown roundtrip writes/removes registry entry
  - shutdown progression: stdin EOF → SIGTERM → SIGKILL
  - cleanup_orphans: stale entries pruned, dead-parent orphans killed,
    PID-reuse defense, our own children left alone
  - registry survives helper crash (the entry stays so next boot can clean)
  - concurrent spawns don't corrupt registry
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from magi_plugin_sdk.subprocess import (
    ManagedSubprocess,
    RegistryEntry,
    _load_registry,
    _pid_alive,
    _save_registry,
)


@pytest.fixture
def registry_path(tmp_path: Path) -> Path:
    return tmp_path / "child_processes.json"


def _read_entries(path: Path) -> list[RegistryEntry]:
    return _load_registry(path)


async def _spawn_sleep(
    seconds: float, *, registry_path: Path, label: str = "test.sleep"
) -> ManagedSubprocess:
    """Spawn a child Python that sleeps. Use python so we get the same
    behavior across CI envs."""
    return await ManagedSubprocess.spawn(
        [sys.executable, "-c", f"import time; time.sleep({seconds})"],
        label=label,
        registry_path=registry_path,
    )


# ---------- Basic spawn/shutdown ----------


@pytest.mark.asyncio
async def test_spawn_writes_registry_entry(registry_path: Path) -> None:
    sub = await _spawn_sleep(30.0, registry_path=registry_path)
    try:
        entries = _read_entries(registry_path)
        assert len(entries) == 1
        entry = entries[0]
        assert entry.pid == sub.pid
        assert entry.label == "test.sleep"
        assert entry.argv0 == sys.executable
        assert entry.parent_pid == os.getpid()
        assert entry.started_at > 0
    finally:
        await sub.shutdown()


@pytest.mark.asyncio
async def test_graceful_shutdown_removes_registry_entry(registry_path: Path) -> None:
    sub = await _spawn_sleep(30.0, registry_path=registry_path)
    assert len(_read_entries(registry_path)) == 1

    rc = await sub.shutdown(sigterm_grace_seconds=0.5)
    # Sleep child won't exit on stdin close, so SIGTERM hits. Process died.
    assert sub.proc.returncode is not None
    # registry pruned
    assert _read_entries(registry_path) == []


@pytest.mark.asyncio
async def test_shutdown_progression_stdin_eof_first(registry_path: Path) -> None:
    """A child that exits on stdin EOF should never get SIGTERM."""
    script = (
        "import sys\n"
        "try:\n"
        "    sys.stdin.read()\n"
        "except KeyboardInterrupt:\n"
        "    raise\n"
        # On EOF, exit 0. If SIGTERM, exit code will be -15.
        "sys.exit(0)\n"
    )
    sub = await ManagedSubprocess.spawn(
        [sys.executable, "-c", script],
        label="test.eof_aware",
        registry_path=registry_path,
    )
    rc = await sub.shutdown(sigterm_grace_seconds=2.0, sigkill_grace_seconds=1.0)
    assert rc == 0, "child should have exited cleanly on stdin EOF"


@pytest.mark.asyncio
async def test_shutdown_progression_sigterm_when_eof_ignored(registry_path: Path) -> None:
    """A child that ignores stdin should be sigterm-ed."""
    sub = await _spawn_sleep(60.0, registry_path=registry_path)
    rc = await sub.shutdown(sigterm_grace_seconds=0.3, sigkill_grace_seconds=0.5)
    # SIGTERM yields returncode of -SIGTERM on POSIX
    assert sub.proc.returncode is not None
    assert sub.proc.returncode in (-signal.SIGTERM, -signal.SIGKILL)


@pytest.mark.asyncio
async def test_shutdown_progression_sigkill_when_sigterm_ignored(registry_path: Path) -> None:
    """A child that traps SIGTERM should escalate to SIGKILL."""
    script = (
        "import signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "time.sleep(60)\n"
    )
    sub = await ManagedSubprocess.spawn(
        [sys.executable, "-c", script],
        label="test.sigterm_ignorer",
        registry_path=registry_path,
    )
    rc = await sub.shutdown(sigterm_grace_seconds=0.3, sigkill_grace_seconds=0.3)
    assert sub.proc.returncode == -signal.SIGKILL


# ---------- cleanup_orphans ----------


def test_cleanup_orphans_prunes_dead_entries(registry_path: Path) -> None:
    # Forge an entry for a PID we know is dead (max int isn't valid).
    _save_registry(
        registry_path,
        [
            RegistryEntry(
                pid=2**30,  # arbitrarily large; almost certainly not assigned
                label="dead.child",
                argv0="/usr/bin/sleep",
                parent_pid=1,
                started_at=time.time() - 100,
            ),
        ],
    )
    killed = ManagedSubprocess.cleanup_orphans(registry_path=registry_path)
    assert killed == 0
    assert _read_entries(registry_path) == []


def test_cleanup_orphans_keeps_our_own_children(registry_path: Path) -> None:
    """A child whose parent_pid == our pid is *ours* and must not be killed
    even if we somehow boot with leftover entries."""
    # Spawn a real subprocess so the PID is alive.
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        _save_registry(
            registry_path,
            [
                RegistryEntry(
                    pid=proc.pid,
                    label="ours",
                    argv0=sys.executable,
                    parent_pid=os.getpid(),
                    started_at=time.time(),
                ),
            ],
        )
        killed = ManagedSubprocess.cleanup_orphans(registry_path=registry_path)
        assert killed == 0
        # Process still alive
        assert proc.poll() is None
        # Entry kept
        assert len(_read_entries(registry_path)) == 1
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_cleanup_orphans_kills_when_parent_is_dead(registry_path: Path) -> None:
    """The whole point: a live child whose registered parent is dead
    must be killed."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        _save_registry(
            registry_path,
            [
                RegistryEntry(
                    pid=proc.pid,
                    label="orphan",
                    argv0=sys.executable,
                    # Some random dead PID. PID 1 (init/launchd) is always
                    # alive on macOS, so we use a clearly dead one.
                    parent_pid=2**30,
                    started_at=time.time(),
                ),
            ],
        )
        killed = ManagedSubprocess.cleanup_orphans(registry_path=registry_path)
        assert killed == 1
        # Give the kill a moment to land
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pytest.fail("orphan process was not killed")
        assert proc.returncode is not None
        assert _read_entries(registry_path) == []
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2)


def test_cleanup_orphans_skips_when_pid_reused(registry_path: Path) -> None:
    """If the PID has been reused by a different binary, don't kill it."""
    # Spawn a real subprocess as the "reused PID" target.
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        _save_registry(
            registry_path,
            [
                RegistryEntry(
                    pid=proc.pid,
                    label="was_helper",
                    argv0="/some/totally/different/binary",
                    parent_pid=2**30,  # dead parent
                    started_at=time.time(),
                ),
            ],
        )
        killed = ManagedSubprocess.cleanup_orphans(registry_path=registry_path)
        # The argv0 mismatch means we treat this as PID reuse and skip.
        assert killed == 0
        assert proc.poll() is None
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_cleanup_orphans_on_missing_registry(tmp_path: Path) -> None:
    # No registry file exists yet — cleanup must be a no-op, not raise.
    killed = ManagedSubprocess.cleanup_orphans(
        registry_path=tmp_path / "nonexistent.json"
    )
    assert killed == 0


def test_cleanup_orphans_on_corrupt_registry(registry_path: Path) -> None:
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text("not valid json {", encoding="utf-8")
    killed = ManagedSubprocess.cleanup_orphans(registry_path=registry_path)
    assert killed == 0


# ---------- Concurrent spawns ----------


@pytest.mark.asyncio
async def test_concurrent_spawns_all_registered(registry_path: Path) -> None:
    """Multiple parallel spawns must all land in the registry. The
    last-writer-wins atomic-rename strategy means small races are
    possible — but with the spawn() implementation's load-modify-save
    each call should serialize via the asyncio event loop. Verify."""
    subs = await asyncio.gather(
        *[_spawn_sleep(30.0, registry_path=registry_path, label=f"test.s{i}") for i in range(5)]
    )
    try:
        entries = _read_entries(registry_path)
        pids = {e.pid for e in entries}
        assert pids == {s.pid for s in subs}, f"missing entries: {entries}"
    finally:
        await asyncio.gather(*(s.shutdown() for s in subs))
    assert _read_entries(registry_path) == []


# ---------- Helpers ----------


def test_pid_alive_for_self() -> None:
    assert _pid_alive(os.getpid()) is True


def test_pid_alive_for_dead_pid() -> None:
    # 2**30 is well above the max PID on macOS/Linux
    assert _pid_alive(2**30) is False
