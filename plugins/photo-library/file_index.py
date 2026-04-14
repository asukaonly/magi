"""Local file index cache for avoiding redundant EXIF extraction.

Stores ``path → (mtime, size, quick_hash, exif_json)`` in a SQLite database
under the plugin cache directory.  When the file's *mtime* and *size* haven't
changed, the cached EXIF data is returned directly — skipping the expensive
binary parse.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


_SCHEMA = """\
CREATE TABLE IF NOT EXISTS file_index (
    path        TEXT PRIMARY KEY,
    mtime       REAL NOT NULL,
    file_size   INTEGER NOT NULL,
    quick_hash  TEXT NOT NULL DEFAULT '',
    exif_json   TEXT NOT NULL DEFAULT '{}',
    updated_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_file_index_mtime ON file_index (mtime);
"""


class FileIndexCache:
    """SQLite-backed file metadata cache.

    The database file is created lazily under *cache_dir* on first access.
    All operations are synchronous (intended to be called from a thread via
    ``asyncio.to_thread``).
    """

    def __init__(self, cache_dir: Path) -> None:
        self._db_path = cache_dir / "file_index.db"
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path), timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(_SCHEMA)
        self._conn = conn
        return conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, path: str, mtime: float, file_size: int) -> dict[str, Any] | None:
        """Return cached EXIF dict if *path* has an up-to-date entry, else ``None``."""
        try:
            conn = self._connect()
        except (sqlite3.Error, OSError):
            return None
        try:
            row = conn.execute(
                "SELECT exif_json FROM file_index WHERE path = ? AND mtime = ? AND file_size = ?",
                (path, mtime, file_size),
            ).fetchone()
        except sqlite3.Error:
            return None
        if row is None:
            return None
        try:
            return json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            return None

    def put(
        self,
        path: str,
        mtime: float,
        file_size: int,
        quick_hash: str,
        exif: dict[str, Any],
        updated_at: float,
    ) -> None:
        """Insert or replace a cache entry for *path*."""
        try:
            conn = self._connect()
        except (sqlite3.Error, OSError):
            return
        try:
            conn.execute(
                """
                INSERT INTO file_index (path, mtime, file_size, quick_hash, exif_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    mtime      = excluded.mtime,
                    file_size  = excluded.file_size,
                    quick_hash = excluded.quick_hash,
                    exif_json  = excluded.exif_json,
                    updated_at = excluded.updated_at
                """,
                (path, mtime, file_size, quick_hash, json.dumps(exif, ensure_ascii=False), updated_at),
            )
            conn.commit()
        except sqlite3.Error:
            pass

    def put_batch(
        self,
        entries: list[tuple[str, float, int, str, dict[str, Any], float]],
    ) -> None:
        """Bulk insert/replace cache entries.

        Each entry is ``(path, mtime, file_size, quick_hash, exif, updated_at)``.
        """
        if not entries:
            return
        try:
            conn = self._connect()
        except (sqlite3.Error, OSError):
            return
        try:
            conn.executemany(
                """
                INSERT INTO file_index (path, mtime, file_size, quick_hash, exif_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    mtime      = excluded.mtime,
                    file_size  = excluded.file_size,
                    quick_hash = excluded.quick_hash,
                    exif_json  = excluded.exif_json,
                    updated_at = excluded.updated_at
                """,
                [
                    (path, mtime, file_size, quick_hash, json.dumps(exif, ensure_ascii=False), updated_at)
                    for path, mtime, file_size, quick_hash, exif, updated_at in entries
                ],
            )
            conn.commit()
        except sqlite3.Error:
            pass

    def prune(self, older_than: float) -> int:
        """Remove entries not updated since *older_than* (Unix timestamp).

        Returns the number of rows deleted.
        """
        conn = self._connect()
        cursor = conn.execute(
            "DELETE FROM file_index WHERE updated_at < ?",
            (older_than,),
        )
        conn.commit()
        return cursor.rowcount
