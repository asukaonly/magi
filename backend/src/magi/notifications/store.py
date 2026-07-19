"""Durable per-user notification store (sqlite). Mirrors RuntimeStatusStore.

Lives in the runtime_trace DB but is a SEPARATE table from the ephemeral
runtime_notifications; its retention is independent (see runtime_operational_gc).
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_VISIBLE_STATUSES = ("unread", "read")  # default feed excludes dismissed + actioned


@dataclass
class NotificationRow:
    user_id: str
    kind: str
    dedupe_key: str
    title: str
    body: str
    payload_json: str = "{}"
    status: str = "unread"
    created_at_ms: int = 0
    read_at_ms: Optional[int] = None
    actioned_at_ms: Optional[int] = None
    dismissed_at_ms: Optional[int] = None
    dismiss_kind: Optional[str] = None
    id: int = 0


def _now_ms() -> int:
    return int(time.time() * 1000)


class NotificationStore:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def ensure_schema(self) -> None:
        """Create the table if missing — used by tests and as a boot safety net
        (production also gets it via the 0002 migration)."""
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS user_notifications (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT NOT NULL DEFAULT 'default_user',
                        kind TEXT NOT NULL,
                        dedupe_key TEXT NOT NULL,
                        title TEXT NOT NULL,
                        body TEXT NOT NULL,
                        payload_json TEXT NOT NULL DEFAULT '{}',
                        status TEXT NOT NULL DEFAULT 'unread',
                        created_at_ms INTEGER NOT NULL,
                        read_at_ms INTEGER,
                        actioned_at_ms INTEGER,
                        dismissed_at_ms INTEGER,
                        dismiss_kind TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_user_notifications_feed
                        ON user_notifications(user_id, created_at_ms DESC);
                    CREATE INDEX IF NOT EXISTS idx_user_notifications_dedup
                        ON user_notifications(user_id, kind, dedupe_key);
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def _to_row(self, r: sqlite3.Row) -> NotificationRow:
        return NotificationRow(
            id=int(r["id"]), user_id=r["user_id"], kind=r["kind"],
            dedupe_key=r["dedupe_key"], title=r["title"], body=r["body"],
            payload_json=r["payload_json"], status=r["status"],
            created_at_ms=int(r["created_at_ms"]),
            read_at_ms=r["read_at_ms"], actioned_at_ms=r["actioned_at_ms"],
            dismissed_at_ms=r["dismissed_at_ms"], dismiss_kind=r["dismiss_kind"],
        )

    def insert(self, row: NotificationRow) -> int:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    """
                    INSERT INTO user_notifications
                        (user_id, kind, dedupe_key, title, body, payload_json,
                         status, created_at_ms)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (row.user_id, row.kind, row.dedupe_key, row.title, row.body,
                     row.payload_json, row.status, row.created_at_ms or _now_ms()),
                )
                conn.commit()
                return int(cur.lastrowid or 0)
            finally:
                conn.close()

    def bump(self, notification_id: int, *, body: str, created_at_ms: int) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE user_notifications SET body=?, created_at_ms=? WHERE id=?",
                    (body, created_at_ms, notification_id),
                )
                conn.commit()
            finally:
                conn.close()

    def find_active_by_dedup(self, user_id: str, kind: str, dedupe_key: str) -> Optional[NotificationRow]:
        conn = self._connect()
        try:
            r = conn.execute(
                """
                SELECT * FROM user_notifications
                WHERE user_id=? AND kind=? AND dedupe_key=?
                  AND status IN ('unread','read')
                ORDER BY id DESC LIMIT 1
                """,
                (user_id, kind, dedupe_key),
            ).fetchone()
            return self._to_row(r) if r else None
        finally:
            conn.close()

    def get(self, notification_id: int) -> Optional[NotificationRow]:
        conn = self._connect()
        try:
            r = conn.execute(
                "SELECT * FROM user_notifications WHERE id=?",
                (notification_id,),
            ).fetchone()
            return self._to_row(r) if r else None
        finally:
            conn.close()

    def find_latest_by_dedup(self, user_id: str, kind: str, dedupe_key: str) -> Optional[NotificationRow]:
        conn = self._connect()
        try:
            r = conn.execute(
                """
                SELECT * FROM user_notifications
                WHERE user_id=? AND kind=? AND dedupe_key=?
                ORDER BY id DESC LIMIT 1
                """,
                (user_id, kind, dedupe_key),
            ).fetchone()
            return self._to_row(r) if r else None
        finally:
            conn.close()

    def list_for_user(
        self,
        user_id: str,
        *,
        limit: int = 50,
        before_id: Optional[int] = None,
        exclude_profile_conflicts: bool = False,
    ) -> list[NotificationRow]:
        conn = self._connect()
        try:
            sql = (
                "SELECT * FROM user_notifications "
                "WHERE user_id=? AND status IN ('unread','read') "
            )
            params: list = [user_id]
            if exclude_profile_conflicts:
                sql += "AND dedupe_key NOT LIKE 'profile_conflict:%' "
            if before_id is not None:
                sql += "AND id < ? "
                params.append(before_id)
            sql += "ORDER BY created_at_ms DESC, id DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, tuple(params)).fetchall()
            return [self._to_row(r) for r in rows]
        finally:
            conn.close()

    def unread_count(
        self,
        user_id: str,
        *,
        exclude_profile_conflicts: bool = False,
    ) -> int:
        conn = self._connect()
        try:
            profile_filter = (
                " AND dedupe_key NOT LIKE 'profile_conflict:%'"
                if exclude_profile_conflicts
                else ""
            )
            r = conn.execute(
                "SELECT COUNT(*) AS c FROM user_notifications "
                "WHERE user_id=? AND status='unread'"
                f"{profile_filter}",
                (user_id,),
            ).fetchone()
            return int(r["c"] or 0)
        finally:
            conn.close()

    def mark_read(self, ids: list[int]) -> None:
        if not ids:
            return
        with self._lock:
            conn = self._connect()
            try:
                q = ",".join("?" for _ in ids)
                conn.execute(
                    f"UPDATE user_notifications SET status='read', read_at_ms=? "
                    f"WHERE id IN ({q}) AND status='unread'",
                    (_now_ms(), *ids),
                )
                conn.commit()
            finally:
                conn.close()

    def mark_read_all(self, user_id: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE user_notifications SET status='read', read_at_ms=? "
                    "WHERE user_id=? AND status='unread'",
                    (_now_ms(), user_id),
                )
                conn.commit()
            finally:
                conn.close()

    def mark_dismissed(self, notification_id: int, dismiss_kind: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE user_notifications SET status='dismissed', dismissed_at_ms=?, dismiss_kind=? WHERE id=?",
                    (_now_ms(), dismiss_kind, notification_id),
                )
                conn.commit()
            finally:
                conn.close()

    def mark_dismissed_all(self, user_id: str, dismiss_kind: str) -> int:
        """Dismiss every still-visible (unread/read) notification for the user.

        Returns the number of rows dismissed. Actioned/already-dismissed rows
        are left untouched (they're not in the feed anyway).
        """
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "UPDATE user_notifications SET status='dismissed', dismissed_at_ms=?, dismiss_kind=? "
                    "WHERE user_id=? AND status IN ('unread','read')",
                    (_now_ms(), dismiss_kind, user_id),
                )
                conn.commit()
                return int(cur.rowcount or 0)
            finally:
                conn.close()

    def mark_actioned(self, notification_id: int) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE user_notifications SET status='actioned', actioned_at_ms=? WHERE id=?",
                    (_now_ms(), notification_id),
                )
                conn.commit()
            finally:
                conn.close()

    def delete_expired_user_notifications(self, cutoff_ms: int) -> int:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "DELETE FROM user_notifications WHERE status != 'unread' AND created_at_ms < ?",
                    (cutoff_ms,),
                )
                conn.commit()
                return cur.rowcount
            finally:
                conn.close()


_STORE: NotificationStore | None = None


def get_notification_store() -> NotificationStore:
    """Singleton pointed at the runtime_trace DB (same file as runtime_notifications,
    different table). The path comes from runtime_paths (same DB the runtime-trace
    store + GC use)."""
    global _STORE
    if _STORE is None:
        from magi.utils.runtime import get_runtime_paths
        db_path = str(get_runtime_paths().runtime_trace_db_path)
        _STORE = NotificationStore(db_path)
        _STORE.ensure_schema()
    return _STORE
