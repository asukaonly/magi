"""Unix plugin-family owner, executed directly with only the standard library.

The outer owner watches the host. A trusted group guardian watches the owner;
plugin code shares the guardian's group but inherits neither lifetime pipes nor
the runtime lease. Either supervisor can die without orphaning plugin work.
"""

from __future__ import annotations

import errno
import os
import select
import signal
import subprocess
import sys
from contextlib import closing


def wait_for_exit_or_owner(child_pid: int, owner_fd: int) -> None:
    """Observe exit without reaping the process-group leader before cleanup."""
    if sys.platform == "darwin":
        with closing(select.kqueue()) as events:
            changes = [
                select.kevent(child_pid, filter=select.KQ_FILTER_PROC,
                              flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                              fflags=select.KQ_NOTE_EXIT),
                select.kevent(owner_fd, filter=select.KQ_FILTER_READ,
                              flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT),
            ]
            try:
                observed = events.control(changes, 1, None)
                for event in observed:
                    if event.flags & select.KQ_EV_ERROR and event.data:
                        if event.data == errno.ESRCH:
                            return
                        raise OSError(event.data, os.strerror(event.data))
            except ProcessLookupError:
                # The child exited before the process watch was registered.
                return
        return
    while os.waitid(os.P_PID, child_pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
        readable, _, _ = select.select([owner_fd], [], [], 0.1)
        if readable:
            return


def guard(owner_fd: int, lease_fd: int, command: list[str]) -> None:
    """Keep the group identity alive until all group members receive SIGKILL."""
    os.set_inheritable(owner_fd, False)
    if lease_fd >= 0:
        os.set_inheritable(lease_fd, False)
    try:
        child = subprocess.Popen(command)
        wait_for_exit_or_owner(child.pid, owner_fd)
    finally:
        # This guardian is the live group leader, so the group ID cannot be reused.
        # SIGKILL reaches descendants even if plugin code blocks or ignores signals.
        os.killpg(os.getpid(), signal.SIGKILL)


def main() -> None:
    guarded = sys.argv[1] == "--guard"
    args = sys.argv[2:] if guarded else sys.argv[1:]
    owner_fd, lease_fd = map(int, args[:2])
    command = args[2:]
    if os.getpgrp() != os.getpid() or not command:
        raise RuntimeError("Plugin owner requires a dedicated process group and command")
    os.set_inheritable(owner_fd, False)
    if lease_fd >= 0:
        os.set_inheritable(lease_fd, False)
    if guarded:
        guard(owner_fd, lease_fd, command)
        return
    child = None
    guard_read, guard_write = os.pipe()
    try:
        child = subprocess.Popen(
            [sys.executable, "-I", "-S", __file__, "--guard", str(guard_read), str(lease_fd), *command],
            start_new_session=True,
            pass_fds=(guard_read,) + (() if lease_fd < 0 else (lease_fd,)),
        )
        os.close(guard_read)
        guard_read = -1
        # Retain the leader PID until group cleanup; reaping first permits reuse.
        wait_for_exit_or_owner(child.pid, owner_fd)
    finally:
        os.close(guard_write)
        if guard_read >= 0:
            os.close(guard_read)
        if child is not None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            # Keep the lease until the kernel confirms this worker has exited.
            child.wait()


if __name__ == "__main__":
    main()
