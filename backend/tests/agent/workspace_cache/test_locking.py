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


def test_file_lock_releases_on_exception(tmp_path: Path) -> None:
    target = tmp_path / "data.txt"
    target.write_text("")
    with open(target, "a", encoding="utf-8") as f:
        try:
            with file_lock(f):
                raise RuntimeError("boom")
        except RuntimeError:
            pass
    with open(target, "a", encoding="utf-8") as f2:
        with file_lock(f2):
            f2.write("ok\n")
    assert target.read_text() == "ok\n"
