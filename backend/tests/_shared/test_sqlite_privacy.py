from pathlib import Path

from _shared.sqlite_privacy import (
    assert_sqlite_fragment_absent,
    sqlite_fragment_present,
)


def test_privacy_scan_tolerates_disappearing_sqlite_sidecars(
    monkeypatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime_trace.db"
    db_path.write_bytes(b"safe database content")
    original_read_bytes = Path.read_bytes

    def read_with_disappearing_sidecars(path: Path) -> bytes:
        if path == db_path:
            return original_read_bytes(path)
        raise FileNotFoundError(path)

    monkeypatch.setattr(Path, "read_bytes", read_with_disappearing_sidecars)

    assert sqlite_fragment_present(db_path, b"private marker") is False
    assert_sqlite_fragment_absent(db_path, b"private marker")
