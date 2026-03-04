"""L5 capability memory with SQLite persistence."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class Capability:
    capability_id: str
    name: str
    description: str
    category: str
    proficiency: float = 0.0
    usage_count: int = 0
    success_count: int = 0
    last_used: float = 0.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "proficiency": self.proficiency,
            "usage_count": self.usage_count,
            "success_count": self.success_count,
            "last_used": self.last_used,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Capability":
        return cls(
            capability_id=str(row["capability_id"]),
            name=str(row["name"]),
            description=str(row["description"] or ""),
            category=str(row["category"]),
            proficiency=float(row["proficiency"]),
            usage_count=int(row["usage_count"]),
            success_count=int(row["success_count"]),
            last_used=float(row["last_used"] or 0),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    def matches(self, context: Dict[str, Any]) -> float:
        """Simple matching based on category and proficiency."""
        score = self.proficiency
        event_type = str(context.get("event_type", ""))
        if event_type and self.category and event_type.lower() in self.category.lower():
            score += 0.3
        return min(1.0, score)


class CapabilityMemory:
    """Stores extracted capabilities and provides retrieval by context matching."""

    def __init__(self, persist_path: Optional[str] = None):
        self.persist_path = str(Path(persist_path or "~/.magi/data/memories/capabilities.db").expanduser())
        self._initialized = False
        self._blacklist: set[str] = set()
        self._task_history: Dict[str, Dict[str, int]] = {}

    def _ensure_db(self) -> None:
        if self._initialized:
            return

        Path(self.persist_path).parent.mkdir(parents=True, exist_ok=True)
        self._load_caches()
        self._initialized = True

    def _load_caches(self) -> None:
        conn = sqlite3.connect(self.persist_path)
        conn.row_factory = sqlite3.Row

        cursor = conn.execute("SELECT capability_id FROM capability_blacklist")
        self._blacklist = {str(row[0]) for row in cursor.fetchall()}

        cursor = conn.execute("SELECT capability_id, task_category, usage_count, success_count FROM capability_task_stats")
        self._task_history = {
            f"{row['capability_id']}:{row['task_category']}": {
                "attempt": int(row["usage_count"]),
                "success": int(row["success_count"]),
            }
            for row in cursor.fetchall()
        }

        conn.close()

    def record_attempt(
        self,
        task_id: str,
        context: Dict[str, Any],
        action: Dict[str, Any],
        success: bool,
        duration: float = 0.0,
        error: Optional[str] = None,
    ) -> None:
        self._ensure_db()
        task_id = task_id or "unknown"

        attempts, successes = self._upsert_task_stats(task_id, success)
        success_rate = (successes / attempts) if attempts else 0.0

        if attempts >= 3 and success_rate >= 0.7:
            self._extract_or_update_capability(task_id, context, action, success_rate, attempts, duration)

        self._update_matching_capabilities(context, success, duration, error)

        if attempts >= 5 and success_rate < 0.3:
            capability_id = f"cap_{_safe_id(task_id)}"
            self._blacklist_capability(capability_id, "low success rate")

    def _upsert_task_stats(self, task_id: str, success: bool) -> Tuple[int, int]:
        now = time.time()
        conn = sqlite3.connect(self.persist_path)
        conn.row_factory = sqlite3.Row

        # task_id 作为 capability_id 使用，task_category 默认为 "default"
        capability_id = task_id
        task_category = "default"
        cache_key = f"{capability_id}:{task_category}"

        cursor = conn.execute(
            "SELECT usage_count, success_count FROM capability_task_stats WHERE capability_id = ? AND task_category = ?",
            (capability_id, task_category),
        )
        row = cursor.fetchone()
        if row:
            usage_count = int(row["usage_count"]) + 1
            success_count = int(row["success_count"]) + (1 if success else 0)
            avg_satisfaction = success_count / usage_count if usage_count > 0 else 0.0
            conn.execute(
                "UPDATE capability_task_stats SET usage_count = ?, success_count = ?, avg_satisfaction = ?, updated_at = ? WHERE capability_id = ? AND task_category = ?",
                (usage_count, success_count, avg_satisfaction, now, capability_id, task_category),
            )
        else:
            usage_count = 1
            success_count = 1 if success else 0
            avg_satisfaction = success_count / usage_count if usage_count > 0 else 0.0
            conn.execute(
                "INSERT INTO capability_task_stats(capability_id, task_category, usage_count, success_count, avg_satisfaction, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (capability_id, task_category, usage_count, success_count, avg_satisfaction, now),
            )

        conn.commit()
        conn.close()

        self._task_history[cache_key] = {"attempt": usage_count, "success": success_count}
        return usage_count, success_count

    def _extract_or_update_capability(
        self,
        task_id: str,
        context: Dict[str, Any],
        action: Dict[str, Any],
        success_rate: float,
        attempts: int,
        duration: float,
    ) -> None:
        capability_id = f"cap_{_safe_id(task_id)}"
        name = self._generate_capability_name(context, action)
        description = f"Capability extracted from task '{task_id}'"
        category = action.get("type") or action.get("tool") or context.get("event_type") or "general"
        now = time.time()

        conn = sqlite3.connect(self.persist_path)
        conn.execute(
            """
            INSERT INTO capabilities(
                capability_id, name, description, category, proficiency, usage_count, success_count, last_used, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(capability_id) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                category = excluded.category,
                proficiency = excluded.proficiency,
                usage_count = excluded.usage_count,
                success_count = excluded.success_count,
                last_used = excluded.last_used,
                updated_at = excluded.updated_at
            """,
            (
                capability_id,
                name,
                description,
                str(category),
                success_rate,
                attempts,
                int(success_rate * attempts),
                now,
                now,
                now,
            ),
        )
        conn.commit()
        conn.close()

    def _update_matching_capabilities(
        self,
        context: Dict[str, Any],
        success: bool,
        duration: float,
        error: Optional[str],
    ) -> None:
        capabilities = self.get_all_capabilities()
        if not capabilities:
            return

        conn = sqlite3.connect(self.persist_path)
        now = time.time()
        for capability in capabilities:
            if capability.capability_id in self._blacklist:
                continue
            if capability.matches(context) < 0.2:
                continue

            usage_count = capability.usage_count + 1
            success_count = capability.success_count + (1 if success else 0)
            proficiency = success_count / usage_count if usage_count > 0 else 0.0

            conn.execute(
                """
                UPDATE capabilities
                SET usage_count = ?, success_count = ?, proficiency = ?, last_used = ?, updated_at = ?
                WHERE capability_id = ?
                """,
                (
                    usage_count,
                    success_count,
                    proficiency,
                    now,
                    now,
                    capability.capability_id,
                ),
            )

        conn.commit()
        conn.close()

    def _blacklist_capability(self, capability_id: str, reason: str) -> None:
        conn = sqlite3.connect(self.persist_path)
        conn.execute(
            """
            INSERT INTO capability_blacklist(capability_id, reason, blacklisted_at)
            VALUES (?, ?, ?)
            ON CONFLICT(capability_id) DO UPDATE SET
                reason = excluded.reason,
                blacklisted_at = excluded.blacklisted_at
            """,
            (capability_id, reason, time.time()),
        )
        conn.commit()
        conn.close()
        self._blacklist.add(capability_id)

    def _generate_capability_name(self, context: Dict[str, Any], action: Dict[str, Any]) -> str:
        tool_name = action.get("tool") or action.get("type")
        event_type = context.get("event_type")
        if tool_name:
            return f"{tool_name} capability"
        if event_type:
            return f"{event_type} handling capability"
        return "general capability"

    def find_capability(self, context: Dict[str, Any], threshold: float = 0.5) -> Optional[Capability]:
        self._ensure_db()
        candidates = self.get_all_capabilities()
        if not candidates:
            return None

        best_capability: Optional[Capability] = None
        best_score = threshold

        for capability in candidates:
            if capability.capability_id in self._blacklist:
                continue

            score = capability.matches(context)
            if score > best_score:
                best_score = score
                best_capability = capability

        return best_capability

    def get_all_capabilities(self) -> List[Capability]:
        self._ensure_db()
        conn = sqlite3.connect(self.persist_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM capabilities")
        rows = cursor.fetchall()
        conn.close()
        return [Capability.from_row(row) for row in rows]

    def get_capability(self, capability_id: str) -> Optional[Capability]:
        self._ensure_db()
        conn = sqlite3.connect(self.persist_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM capabilities WHERE capability_id = ?", (capability_id,))
        row = cursor.fetchone()
        conn.close()
        return Capability.from_row(row) if row else None

    def delete_capability(self, capability_id: str) -> bool:
        self._ensure_db()
        conn = sqlite3.connect(self.persist_path)
        cur = conn.cursor()
        cur.execute("DELETE FROM capabilities WHERE capability_id = ?", (capability_id,))
        deleted = cur.rowcount > 0
        cur.execute("DELETE FROM capability_blacklist WHERE capability_id = ?", (capability_id,))
        conn.commit()
        conn.close()
        self._blacklist.discard(capability_id)
        return deleted

    def clear(self) -> int:
        self._ensure_db()
        conn = sqlite3.connect(self.persist_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM capabilities")
        count = int(cur.fetchone()[0])
        cur.execute("DELETE FROM capabilities")
        cur.execute("DELETE FROM capability_task_stats")
        cur.execute("DELETE FROM capability_blacklist")
        conn.commit()
        conn.close()

        self._blacklist.clear()
        self._task_history.clear()
        return count

    def get_statistics(self) -> Dict[str, Any]:
        self._ensure_db()
        capabilities = self.get_all_capabilities()
        ranked = sorted(
            ((cap.capability_id, cap.usage_count) for cap in capabilities),
            key=lambda item: item[1],
            reverse=True,
        )

        return {
            "total_capabilities": len(capabilities),
            "blacklist_count": len(self._blacklist),
            "most_used_capabilities": ranked[:5],
            "db_path": self.persist_path,
        }

    # compatibility methods
    def _save_to_disk(self) -> None:
        return None

    _save = _save_to_disk


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", value)
