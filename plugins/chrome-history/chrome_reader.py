"""Read local Chrome history from the profile SQLite database."""
from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

from .normalizers import (
    burst_merge_key,
    canonicalize_url,
    chrome_time_to_unix_seconds,
    normalize_domain,
    normalize_title,
    should_merge_visit,
)

DEFAULT_MACOS_CHROME_ROOT = "~/Library/Application Support/Google/Chrome"
DEFAULT_WINDOWS_CHROME_ROOT = "~/AppData/Local/Google/Chrome/User Data"
DEFAULT_LINUX_CHROME_ROOT = "~/.config/google-chrome"


def _default_chrome_root() -> str:
    """Return the platform-appropriate default Chrome profile root."""
    if sys.platform == "win32":
        return DEFAULT_WINDOWS_CHROME_ROOT
    if sys.platform == "linux":
        return DEFAULT_LINUX_CHROME_ROOT
    return DEFAULT_MACOS_CHROME_ROOT


class ChromeHistoryReader:
    """Read and normalize Google Chrome history visits."""

    def resolve_root(self, source_path: str | None = None) -> Path:
        root = Path(source_path or _default_chrome_root()).expanduser()
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
        lookback_hours: int | None = 24,
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

    def get_latest_visit_id(
        self,
        *,
        source_path: str | None = None,
        profile: str = "Default",
    ) -> int:
        profile_dir = self.resolve_profile_dir(source_path=source_path, profile=profile)
        copy_path = self._copy_history_database(profile_dir)
        try:
            connection = sqlite3.connect(str(copy_path))
            try:
                cursor = connection.execute("SELECT COALESCE(MAX(id), 0) FROM visits")
                row = cursor.fetchone()
                return int(row[0] or 0) if row else 0
            finally:
                connection.close()
        finally:
            shutil.rmtree(copy_path.parent, ignore_errors=True)

    def _query_visits(
        self,
        *,
        copy_path: Path,
        profile: str,
        limit: int,
        last_cursor: str | None,
        lookback_hours: int | None,
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
            elif lookback_hours is not None:
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
            else:
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
                    ORDER BY visits.id ASC
                    LIMIT ?
                    """,
                    (max(1, limit),),
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
                    "canonical_url": canonicalize_url(url),
                    "burst_merge_key": burst_merge_key(url, row["title"]),
                    "title": str(row["title"] or ""),
                    "normalized_title": normalize_title(row["title"]),
                    "visit_time": visit_time,
                    "visit_count": int(row["visit_count"] or 0),
                    "from_visit": str(row["from_visit"] or ""),
                    "transition": str(row["transition"] or ""),
                    "profile": profile,
                    "domain": normalize_domain(url),
                }
            )
        return self._aggregate_visits(visits)

    def _aggregate_visits(self, visits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not visits:
            return []

        aggregated: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for visit in visits:
            if current is None:
                current = self._new_group(visit)
                continue
            if should_merge_visit(current, visit):
                current = self._merge_group(current, visit)
                continue
            aggregated.append(current)
            current = self._new_group(visit)

        if current is not None:
            aggregated.append(current)
        return aggregated

    def _new_group(self, visit: dict[str, Any]) -> dict[str, Any]:
        visit_id = str(visit.get("visit_id") or "")
        item = dict(visit)
        item.update(
            {
                "source_item_id": visit_id,
                "first_visit_id": visit_id,
                "last_visit_id": visit_id,
                "merged_visit_count": 1,
                "burst_start_time": float(visit.get("visit_time") or 0.0),
                "burst_end_time": float(visit.get("visit_time") or 0.0),
            }
        )
        if item.get("canonical_url"):
            item["url"] = item["canonical_url"]
        return item

    def _merge_group(self, current: dict[str, Any], visit: dict[str, Any]) -> dict[str, Any]:
        merged = dict(current)
        first_visit_id = str(current.get("first_visit_id") or current.get("visit_id") or "")
        last_visit_id = str(visit.get("visit_id") or current.get("last_visit_id") or "")
        merged_visit_count = int(current.get("merged_visit_count") or 1) + 1
        visit_time = float(visit.get("visit_time") or current.get("visit_time") or 0.0)
        merged.update(
            {
                "source_item_id": f"{first_visit_id}-{last_visit_id}",
                "visit_id": last_visit_id,
                "last_visit_id": last_visit_id,
                "merged_visit_count": merged_visit_count,
                "burst_end_time": visit_time,
                "visit_time": visit_time,
                "visit_count": max(
                    int(current.get("visit_count") or 0),
                    int(visit.get("visit_count") or 0),
                ),
                "from_visit": str(visit.get("from_visit") or current.get("from_visit") or ""),
                "transition": str(visit.get("transition") or current.get("transition") or ""),
                "title": str(visit.get("title") or current.get("title") or ""),
                "normalized_title": str(
                    visit.get("normalized_title")
                    or current.get("normalized_title")
                    or ""
                ),
                "canonical_url": str(visit.get("canonical_url") or current.get("canonical_url") or ""),
            }
        )
        if merged.get("canonical_url"):
            merged["url"] = merged["canonical_url"]
        return merged
