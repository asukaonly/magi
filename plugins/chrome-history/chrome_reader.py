"""Read local Chrome history from the profile SQLite database."""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from .normalizers import chrome_time_to_unix_seconds, normalize_domain

DEFAULT_MACOS_CHROME_ROOT = "~/Library/Application Support/Google/Chrome"


class ChromeHistoryReader:
    """Read and normalize Google Chrome history visits."""

    def resolve_root(self, source_path: str | None = None) -> Path:
        root = Path(source_path or DEFAULT_MACOS_CHROME_ROOT).expanduser()
        return root

    def resolve_profile_dir(self, source_path: str | None = None, profile: str = "Default") -> Path:
        root = self.resolve_root(source_path)
        candidate = root / profile
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"Chrome profile not found: {candidate}")

    def _copy_history_database(self, profile_dir: Path) -> Path:
        history_file = profile_dir / "History"
        if not history_file.exists():
            raise FileNotFoundError(f"Chrome history database not found: {history_file}")
        temp_dir = Path(tempfile.mkdtemp(prefix="magi-chrome-history-"))
        copy_path = temp_dir / "History"
        shutil.copy2(history_file, copy_path)
        return copy_path

    def read_visits(
        self,
        *,
        source_path: str | None = None,
        profile: str = "Default",
        limit: int = 200,
        last_cursor: str | None = None,
        lookback_hours: int = 24,
    ) -> list[dict[str, Any]]:
        profile_dir = self.resolve_profile_dir(source_path=source_path, profile=profile)
        copy_path = self._copy_history_database(profile_dir)
        try:
            return self._query_visits(
                copy_path=copy_path,
                profile=profile,
                limit=limit,
                last_cursor=last_cursor,
                lookback_hours=lookback_hours,
            )
        finally:
            shutil.rmtree(copy_path.parent, ignore_errors=True)

    def _query_visits(
        self,
        *,
        copy_path: Path,
        profile: str,
        limit: int,
        last_cursor: str | None,
        lookback_hours: int,
    ) -> list[dict[str, Any]]:
        last_visit_id = int(last_cursor) if str(last_cursor or "").isdigit() else 0
        connection = sqlite3.connect(str(copy_path))
        connection.row_factory = sqlite3.Row
        try:
            if last_visit_id > 0:
                cursor = connection.execute(
                    """
                    SELECT
                        visits.id AS visit_id,
                        urls.url AS url,
                        urls.title AS title,
                        urls.visit_count AS visit_count,
                        visits.visit_time AS raw_visit_time,
                        visits.from_visit AS from_visit,
                        visits.transition AS transition
                    FROM visits
                    JOIN urls ON visits.url = urls.id
                    WHERE visits.id > ?
                    ORDER BY visits.id ASC
                    LIMIT ?
                    """,
                    (last_visit_id, max(1, limit)),
                )
            else:
                lookback_microseconds = max(1, lookback_hours) * 3600 * 1_000_000
                cursor = connection.execute(
                    """
                    SELECT
                        visits.id AS visit_id,
                        urls.url AS url,
                        urls.title AS title,
                        urls.visit_count AS visit_count,
                        visits.visit_time AS raw_visit_time,
                        visits.from_visit AS from_visit,
                        visits.transition AS transition
                    FROM visits
                    JOIN urls ON visits.url = urls.id
                    WHERE visits.visit_time >= (
                        SELECT COALESCE(MAX(visit_time), 0) - ?
                        FROM visits
                    )
                    ORDER BY visits.id ASC
                    LIMIT ?
                    """,
                    (lookback_microseconds, max(1, limit)),
                )
            rows = cursor.fetchall()
        finally:
            connection.close()

        visits: list[dict[str, Any]] = []
        for row in rows:
            visit_time = chrome_time_to_unix_seconds(row["raw_visit_time"])
            url = str(row["url"] or "")
            visits.append(
                {
                    "visit_id": str(row["visit_id"]),
                    "url": url,
                    "title": str(row["title"] or ""),
                    "visit_time": visit_time,
                    "visit_count": int(row["visit_count"] or 0),
                    "from_visit": str(row["from_visit"] or ""),
                    "transition": str(row["transition"] or ""),
                    "profile": profile,
                    "domain": normalize_domain(url),
                }
            )
        return visits
