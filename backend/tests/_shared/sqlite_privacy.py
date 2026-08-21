"""Assertions for sensitive bytes in SQLite database files and sidecars."""

from __future__ import annotations

from pathlib import Path


def sqlite_fragment_present(db_path: str | Path, fragment: str | bytes) -> bool:
    """Return whether one fragment remains in the database or known sidecars."""

    encoded = fragment.encode() if isinstance(fragment, str) else fragment
    return any(
        content is not None and encoded in content
        for candidate in _sqlite_files(db_path)
        if (content := _read_existing_file(candidate)) is not None
    )


def assert_sqlite_fragment_absent(
    db_path: str | Path,
    fragment: str | bytes,
) -> None:
    """Assert that one fragment is absent from the database and sidecars."""

    encoded = fragment.encode() if isinstance(fragment, str) else fragment
    for candidate in _sqlite_files(db_path):
        content = _read_existing_file(candidate)
        if content is not None:
            assert encoded not in content, candidate


def _read_existing_file(path: Path) -> bytes | None:
    """Read one SQLite file unless SQLite removed the sidecar concurrently."""

    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _sqlite_files(db_path: str | Path) -> tuple[Path, ...]:
    path = Path(db_path)
    return tuple(
        Path(f"{path}{suffix}")
        for suffix in ("", "-wal", "-shm", "-journal")
    )


__all__ = ["assert_sqlite_fragment_absent", "sqlite_fragment_present"]
