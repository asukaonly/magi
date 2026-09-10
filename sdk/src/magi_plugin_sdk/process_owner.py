"""Unix plugin-family owner, executed directly with only the standard library.

The host alone holds the lifetime pipe's writer. EOF kills this entire process
group even when plugin code holds the GIL or blocks its event loop. Only this
trusted owner retains the runtime lease; plugin code cannot unlock it.
"""

from __future__ import annotations

import os
import select
import signal
import subprocess
import sys


def main() -> None:
    owner_fd, lease_fd = map(int, sys.argv[1:3])
    command = sys.argv[3:]
    if os.getpgrp() != os.getpid() or not command:
        raise RuntimeError("Plugin owner requires a dedicated process group and command")
    os.set_inheritable(owner_fd, False)
    if lease_fd >= 0:
        os.set_inheritable(lease_fd, False)
    child = None
    try:
        # The confinement wrapper applies only to the child, never the owner.
        child = subprocess.Popen(command, start_new_session=True)
        while child.poll() is None:
            readable, _, _ = select.select([owner_fd], [], [], 0.1)
            if readable:
                break
    finally:
        if child is not None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            # Keep the lease until the kernel confirms this worker has exited.
            child.wait()


if __name__ == "__main__":
    main()
