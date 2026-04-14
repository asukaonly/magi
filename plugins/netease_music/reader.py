from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .normalizers import extract_track_info

_MACOS_DB_PATH = "~/Library/Containers/com.netease.163music/Data/Documents/storage/sqlite_storage.sqlite3"
_WINDOWS_DB_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "NetEase", "CloudMusic", "Library", "webdb.dat"
)

DEFAULT_DB_PATH = _WINDOWS_DB_PATH if sys.platform == "win32" else _MACOS_DB_PATH


class NeteaseMusicReader:
    def resolve_db_path(self, source_path: str | None = None) -> Path:
        """Resolve the database file path."""
        if source_path:
            return Path(source_path).expanduser()
        return Path(DEFAULT_DB_PATH).expanduser()

    def _copy_database(self, source_path: str | None = None) -> Path:
        """Copy database to temp location to avoid lock issues."""
        db_path = self.resolve_db_path(source_path)

        # Create a temporary copy
        temp_dir = Path(tempfile.gettempdir()) / "netease_music"
        temp_dir.mkdir(exist_ok=True)

        temp_path = temp_dir / f"temp_{datetime.now().timestamp()}.db"

        try:
            # Try direct file copy first
            shutil.copy2(db_path, temp_path)
        except (IOError, OSError):
            # If direct copy fails, try using SQLite to create a copy
            source_conn = sqlite3.connect(str(db_path))
            target_conn = sqlite3.connect(str(temp_path))

            source_conn.backup(target_conn)

            source_conn.close()
            target_conn.close()

        return temp_path

    def get_liked_playlist_id(self, conn: sqlite3.Connection) -> int | None:
        """Find the liked songs playlist ID (specialType = 5)."""
        cursor = conn.cursor()
        cursor.execute(
            "SELECT pid FROM web_playlist WHERE json_extract(playlist, '$.specialType') = 5 LIMIT 1"
        )
        result = cursor.fetchone()
        return result[0] if result else None

    def get_liked_track_ids(self, conn: sqlite3.Connection, playlist_id: int) -> set[str]:
        """Get set of liked track IDs from a playlist."""
        cursor = conn.cursor()
        cursor.execute(
            "SELECT tid FROM web_playlist_track WHERE pid = ?",
            (playlist_id,)
        )
        results = cursor.fetchall()
        return {row[0] for row in results}

    def read_play_records(
        self,
        *,
        source_path: str | None = None,
        min_play_duration: int = 20,
        limit: int = 200,
        last_cursor: str | None = None,
    ) -> list[dict[str, Any]]:
        """Read play records with track info and liked status."""
        # Copy database to avoid lock issues
        temp_db_path = self._copy_database(source_path)

        conn = sqlite3.connect(temp_db_path)
        conn.row_factory = sqlite3.Row

        # Get liked playlist ID and track IDs
        liked_playlist_id = self.get_liked_playlist_id(conn)
        liked_track_ids = set()

        if liked_playlist_id:
            liked_track_ids = self.get_liked_track_ids(conn, liked_playlist_id)

        # Build the query with cursor if provided
        query = """
        SELECT pc.resourceId, pc.playDuration, pc.updateTime, pc.source, ht.jsonStr
        FROM playingCount pc
        LEFT JOIN historyTracks ht ON pc.resourceId = ht.id
        WHERE pc.playDuration >= ? AND pc.resourceType = 'track' AND ht.id IS NOT NULL
        """
        params = [min_play_duration]

        if last_cursor:
            query += " AND pc.updateTime > ?"
            params.append(int(last_cursor))

        query += " ORDER BY pc.updateTime ASC LIMIT ?"
        params.append(limit)

        cursor = conn.cursor()
        cursor.execute(query, params)

        records = []
        for row in cursor.fetchall():
            track_json = json.loads(row['jsonStr'])
            track_info = extract_track_info(track_json)

            record = {
                'track_id': row['resourceId'],
                'play_duration_sec': row['playDuration'],  # Already in seconds
                'update_time': row['updateTime'],
                'source': row['source'],
                'is_liked': row['resourceId'] in liked_track_ids,
                **track_info
            }

            records.append(record)

        conn.close()

        # Clean up temp file
        try:
            temp_db_path.unlink()
        except OSError:
            pass

        return records

    def get_latest_update_time(self, *, source_path: str | None = None) -> int:
        """Get the latest updateTime from playingCount."""
        temp_db_path = self._copy_database(source_path)

        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT MAX(updateTime) FROM playingCount WHERE resourceType = 'track'"
        )
        result = cursor.fetchone()
        conn.close()

        # Clean up temp file
        try:
            temp_db_path.unlink()
        except OSError:
            pass

        return result[0] if result and result[0] else 0