"""End-to-end concurrency test for SessionCache JSONL append paths."""
from __future__ import annotations

import threading
from pathlib import Path

from magi_plugin_sdk.workspace_cache import resolve_session_cache


def test_parallel_record_read_no_truncation(tmp_path: Path) -> None:
    sc = resolve_session_cache(tmp_path, "concurrency")

    targets = []
    for i in range(20):
        p = tmp_path / f"f_{i}.txt"
        p.write_text(f"file {i}\n")
        targets.append(p)

    errors = []

    def worker(p: Path) -> None:
        try:
            sc.record_read(p)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(p,)) for p in targets]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    records = list(sc.iter_reads())
    assert len(records) == len(targets)
    assert {r.path for r in records} == {p.name for p in targets}
