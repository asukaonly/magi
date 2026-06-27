"""Boundary tests for root-level magi package modules."""

from __future__ import annotations

from pathlib import Path


_BACKEND_SRC = Path(__file__).resolve().parents[2] / "src"
_MAGI_ROOT = _BACKEND_SRC / "magi"


def test_magi_root_contains_no_runtime_modules() -> None:
    root_modules = sorted(
        path.name
        for path in _MAGI_ROOT.glob("*.py")
        if path.name != "__init__.py"
    )

    assert root_modules == []
