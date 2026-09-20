"""Real OS observations must preserve child ownership until cleanup."""

import os
import subprocess
import sys
import threading
import time

import pytest

pytestmark = pytest.mark.skipif(os.name == "nt", reason="Unix process owner")


@pytest.mark.parametrize("trigger", ["child_exit", "already_exited", "owner_exit"])
def test_exit_observation_does_not_reap_child(trigger: str) -> None:
    from magi_plugin_sdk.process_owner import wait_for_exit_or_owner

    owner_read, owner_write = os.pipe()
    child = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.read()"],
        stdin=subprocess.PIPE,
    )
    errors: list[Exception] = []

    def observe() -> None:
        try:
            wait_for_exit_or_owner(child.pid, owner_read)
        except Exception as error:  # noqa: BLE001 - Propagate watcher failures to the test thread.
            errors.append(error)

    if trigger == "already_exited":
        child.stdin.close()
        time.sleep(0.2)
    watcher = threading.Thread(target=observe, daemon=True)
    watcher.start()
    try:
        if trigger == "owner_exit":
            os.close(owner_write)
            owner_write = -1
        elif trigger == "child_exit":
            child.stdin.close()
        watcher.join(timeout=5)
        assert not watcher.is_alive(), "Exit observation did not finish"
        assert not errors
        if trigger == "owner_exit":
            assert child.poll() is None
        else:
            pid, status = os.waitpid(child.pid, 0)
            assert pid == child.pid
            child.returncode = os.waitstatus_to_exitcode(status)
            assert child.returncode == 0
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=5)
        if not child.stdin.closed:
            child.stdin.close()
        watcher.join(timeout=5)
        os.close(owner_read)
        if owner_write >= 0:
            os.close(owner_write)
