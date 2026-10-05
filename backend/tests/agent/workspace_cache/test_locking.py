"""Tests for cross-platform file lock context manager."""
from __future__ import annotations

import threading
import time
from pathlib import Path

from magi_plugin_sdk.fs import file_lock


def test_file_lock_serializes_writes(tmp_path: Path) -> None:
    """Two threads taking the lock should not interleave critical section."""
    target = tmp_path / "data.txt"
    target.write_text("")
    in_section = []
    max_concurrent = [0]
    lock_state = {"count": 0}
    state_lock = threading.Lock()

    def worker(idx: int) -> None:
        with open(target, "a", encoding="utf-8") as f:
            with file_lock(f):
                with state_lock:
                    lock_state["count"] += 1
                    max_concurrent[0] = max(max_concurrent[0], lock_state["count"])
                time.sleep(0.05)
                with state_lock:
                    lock_state["count"] -= 1
                f.write(f"{idx}\n")
                f.flush()
                in_section.append(idx)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(in_section) == [0, 1, 2, 3, 4]
    assert max_concurrent[0] == 1, "Lock failed to serialize"


def test_file_lock_releases_after_error_before_the_original_handle_closes(tmp_path):
    import subprocess
    import sys
    import pytest

    target = tmp_path / "data.txt"
    target.write_bytes(b"0")
    child_code = """
import sys
from magi_plugin_sdk.fs import file_lock
with open(sys.argv[1], "r+b") as stream:
    with file_lock(stream):
        stream.write(b"ok")
        stream.flush()
"""
    with open(target, "r+b") as first:
        with pytest.raises(RuntimeError, match="injected lock body failure"):
            with file_lock(first):
                raise RuntimeError("injected lock body failure")
        assert not first.closed
        child = subprocess.run(
            [sys.executable, "-c", child_code, str(target)],
            capture_output=True,
            text=True,
            timeout=3,
        )
        assert child.returncode == 0, child.stderr
        assert not first.closed
        assert target.read_bytes() == b"ok"
