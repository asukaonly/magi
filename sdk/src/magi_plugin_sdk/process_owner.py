"""Unix plugin-family owner, executed directly with only the standard library.

The host alone holds the lifetime pipe's writer. EOF kills this entire process
group even when plugin code holds the GIL or blocks its event loop. The plugin
inherits the runtime lease, but never the lifetime pipe or its writer.
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
    leases = () if lease_fd < 0 else (lease_fd,)
    try:
        # The confinement wrapper applies only to the child, never the owner.
        child = subprocess.Popen(command, pass_fds=leases)
        while child.poll() is None:
            readable, _, _ = select.select([owner_fd], [], [], 0.1)
            if readable:
                break
    finally:
        # Also remove ordinary descendants after the plugin itself exits.
        os.killpg(os.getpid(), signal.SIGKILL)


if __name__ == "__main__":
    main()
