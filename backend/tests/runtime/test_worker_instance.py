"""Process ownership must survive stale files and reject concurrent workers."""

from pathlib import Path
import os
import queue
import subprocess
import sys
import threading

import pytest

from magi.utils.worker_instance import WorkerInstance


def test_worker_lease_excludes_another_owner_until_shutdown(tmp_path: Path) -> None:
    root = tmp_path / "instance"
    with WorkerInstance(root):
        with pytest.raises(RuntimeError, match="already owns"):
            with WorkerInstance(root):
                pass
    assert (root / "runtime" / "worker.lock").exists()
    with WorkerInstance(root):
        pass


def test_worker_rejects_an_unrelated_supervisor(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="no longer"):
        with WorkerInstance(tmp_path / "instance", os.getpid()):
            pass
    with WorkerInstance(tmp_path / "instance"):
        pass


def test_closing_owner_pipe_stops_worker_and_releases_lease(tmp_path: Path) -> None:
    root = tmp_path / "owned-worker"
    script = (
        "import os,sys,time; from pathlib import Path; "
        "from magi.utils.worker_instance import WorkerInstance; "
        "guard=WorkerInstance(Path(sys.argv[1]), os.getppid()); "
        "guard.__enter__(); print('ready',flush=True); time.sleep(60)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(root)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    assert process.stdout is not None
    lines: queue.Queue[str] = queue.Queue()
    threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True).start()
    try:
        assert lines.get(timeout=5).strip() == "ready"
        with pytest.raises(RuntimeError, match="already owns"):
            with WorkerInstance(root):
                pass
        process.communicate(timeout=5)
        assert process.returncode != 0
        with WorkerInstance(root):
            pass
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
