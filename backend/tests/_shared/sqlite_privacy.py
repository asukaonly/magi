"""Assertions for sensitive bytes in SQLite database files and sidecars."""

from __future__ import annotations

from pathlib import Path


def sqlite_fragment_present(db_path: str | Path, fragment: str | bytes) -> bool:
    """Return whether one fragment remains in the database or known sidecars."""

    encoded = fragment.encode() if isinstance(fragment, str) else fragment
    return any(
        encoded in candidate.read_bytes()
        for candidate in _sqlite_files(db_path)
        if candidate.exists()
    )


def assert_sqlite_fragment_absent(
    db_path: str | Path,
    fragment: str | bytes,
) -> None:
    """Assert that one fragment is absent from the database and sidecars."""

    encoded = fragment.encode() if isinstance(fragment, str) else fragment
    for candidate in _sqlite_files(db_path):
        if candidate.exists():
            assert encoded not in candidate.read_bytes(), candidate


def _sqlite_files(db_path: str | Path) -> tuple[Path, ...]:
    path = Path(db_path)
    return tuple(
        Path(f"{path}{suffix}")
        for suffix in ("", "-wal", "-shm", "-journal")
    )


__all__ = ["assert_sqlite_fragment_absent", "sqlite_fragment_present"]
