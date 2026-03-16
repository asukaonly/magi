from __future__ import annotations

from pathlib import Path


def test_scheduler_runtime_shim_removed() -> None:
    runtime_shim = Path(__file__).resolve().parents[2] / "src/magi/scheduler/runtime.py"

    assert not runtime_shim.exists()
