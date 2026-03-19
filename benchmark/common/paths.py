"""Shared path helpers for benchmark run outputs."""

from __future__ import annotations

import re
from pathlib import Path


def build_run_output_dir(*, root_dir: str | Path, benchmark_name: str, run_id: str) -> Path:
    root = Path(root_dir)
    output_dir = root / _sanitize_component(benchmark_name) / _sanitize_component(run_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _sanitize_component(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(value or "").strip().lower())
    normalized = re.sub(r"_+", "_", normalized).strip("._-")
    return normalized or "unknown"
