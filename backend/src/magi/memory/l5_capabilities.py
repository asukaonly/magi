"""L5 capability memory with SQLite persistence and sqlite-vec-compatible embeddings."""

from __future__ import annotations

import hashlib
import json
import logging
import math
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
    trigger_pattern: Dict[str, Any]
    action: Dict[str, Any]
    success_rate: float = 0.0
    usage_count: int = 0
    avg_duration: float = 0.0
    last_used: float = 0.0
    created_at: float = field(default_factory=time.time)
    examples: List[Dict[str, Any]] = field(default_factory=list)
    failures: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "name": self.name,
            "description": self.description,
            "trigger_pattern": self.trigger_pattern,
            "action": self.action,
            "success_rate": self.success_rate,
            "usage_count": self.usage_count,
            "avg_duration": self.avg_duration,
            "last_used": self.last_used,
            "created_at": self.created_at,
            "examples": self.examples,
            "failures": self.failures,
        }

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Capability":
        return cls(
            capability_id=str(row["capability_id"]),
            name=str(row["name"]),
            description=str(row["description"]),
            trigger_pattern=json.loads(row["trigger_pattern"] or "{}"),
            action=json.loads(row["action"] or "{}"),
            success_rate=float(row["success_rate"]),
            usage_count=int(row["usage_count"]),
            avg_duration=float(row["avg_duration"]),
            last_used=float(row["last_used"]),
            created_at=float(row["created_at"]),
            examples=json.loads(row["examples"] or "[]"),
            failures=json.loads(row["failures"] or "[]"),
        )

    def matches(self, context: Dict[str, Any]) -> float:
        score = 0.0
        pattern = self.trigger_pattern

        event_type = str(context.get("event_type", ""))
        if event_type and event_type in pattern.get("event_types", []):
            score += 0.35

        context_message = str(context.get("message", "")).lower()
        for keyword in pattern.get("keywords", []):
            if keyword.lower() in context_message:
                score += 0.1

        required_params = pattern.get("requires_params", [])
        context_params = context.get("parameters") if isinstance(context.get("parameters"), dict) else {}
        if required_params and all(key in context_params for key in required_params):
            score += 0.3

        return min(1.0, score)


class CapabilityMemory:
    """Stores extracted capabilities and provides retrieval by context matching."""

    def __init__(self, persist_path: Optional[str] = None, embedding_dimension: int = 256):
        self.persist_path = str(Path(persist_path or "~/.magi/data/memories/capabilities.db").expanduser())
        self.embedding_dimension = embedding_dimension
        self._initialized = False
        self._blacklist: set[str] = set()
        self._task_history: Dict[str, Dict[str, int]] = {}

    def _ensure_db(self) -> None:
        if self._initialized:
            return

        Path(self.persist_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.persist_path)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS capabilities (
                capability_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                trigger_pattern TEXT NOT NULL,
                action TEXT NOT NULL,
                embedding TEXT NOT NULL,
                success_rate REAL NOT NULL,
                usage_count INTEGER NOT NULL,
                avg_duration REAL NOT NULL,
                last_used REAL NOT NULL,
                created_at REAL NOT NULL,
                examples TEXT,
                failures TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS capability_task_stats (
                task_id TEXT PRIMARY KEY,
                attempts INTEGER NOT NULL,
                successes INTEGER NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS capability_blacklist (
                capability_id TEXT PRIMARY KEY,
                reason TEXT,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.commit()
        conn.close()

        self._load_caches()
        self._initialized = True

    def _load_caches(self) -> None:
        conn = sqlite3.connect(self.persist_path)
        conn.row_factory = sqlite3.Row

        cursor = conn.execute("SELECT capability_id FROM capability_blacklist")
        self._blacklist = {str(row[0]) for row in cursor.fetchall()}

        cursor = conn.execute("SELECT task_id, attempts, successes FROM capability_task_stats")
        self._task_history = {
            str(row["task_id"]): {
                "attempt": int(row["attempts"]),
                "success": int(row["successes"]),
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

        cursor = conn.execute(
            "SELECT attempts, successes FROM capability_task_stats WHERE task_id = ?",
            (task_id,),
        )
        row = cursor.fetchone()
        if row:
            attempts = int(row["attempts"]) + 1
            successes = int(row["successes"]) + (1 if success else 0)
            conn.execute(
                "UPDATE capability_task_stats SET attempts = ?, successes = ?, updated_at = ? WHERE task_id = ?",
                (attempts, successes, now, task_id),
            )
        else:
            attempts = 1
            successes = 1 if success else 0
            conn.execute(
                "INSERT INTO capability_task_stats(task_id, attempts, successes, updated_at) VALUES (?, ?, ?, ?)",
                (task_id, attempts, successes, now),
            )

        conn.commit()
        conn.close()

        self._task_history[task_id] = {"attempt": attempts, "success": successes}
        return attempts, successes

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
        trigger_pattern = self._analyze_trigger_pattern(context, action)
        name = self._generate_capability_name(context, action)
        description = f"Capability extracted from task '{task_id}'"
        created_at = time.time()

        capability = Capability(
            capability_id=capability_id,
            name=name,
            description=description,
            trigger_pattern=trigger_pattern,
            action=dict(action),
            success_rate=success_rate,
            usage_count=attempts,
            avg_duration=max(0.0, duration),
            last_used=created_at,
            created_at=created_at,
            examples=[{"timestamp": created_at, "context": context}] if context else [],
            failures=[],
        )

        embedding = _hash_embedding(self._capability_text(capability), self.embedding_dimension)

        conn = sqlite3.connect(self.persist_path)
        conn.execute(
            """
            INSERT INTO capabilities(
                capability_id, name, description, trigger_pattern, action, embedding,
                success_rate, usage_count, avg_duration, last_used, created_at, examples, failures
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(capability_id) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                trigger_pattern = excluded.trigger_pattern,
                action = excluded.action,
                embedding = excluded.embedding,
                success_rate = excluded.success_rate,
                usage_count = excluded.usage_count,
                avg_duration = CASE
                    WHEN capabilities.avg_duration > 0 AND excluded.avg_duration > 0
                    THEN (capabilities.avg_duration * 0.7 + excluded.avg_duration * 0.3)
                    ELSE excluded.avg_duration
                END,
                last_used = excluded.last_used,
                examples = excluded.examples,
                failures = capabilities.failures
            """,
            (
                capability.capability_id,
                capability.name,
                capability.description,
                json.dumps(capability.trigger_pattern, ensure_ascii=False),
                json.dumps(capability.action, ensure_ascii=False),
                json.dumps(embedding),
                capability.success_rate,
                capability.usage_count,
                capability.avg_duration,
                capability.last_used,
                capability.created_at,
                json.dumps(capability.examples, ensure_ascii=False),
                json.dumps(capability.failures, ensure_ascii=False),
            ),
        )
        conn.commit()
        conn.close()

    def _capability_text(self, capability: Capability) -> str:
        return json.dumps(
            {
                "name": capability.name,
                "description": capability.description,
                "trigger_pattern": capability.trigger_pattern,
                "action": capability.action,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

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
        for capability in capabilities:
            if capability.capability_id in self._blacklist:
                continue
            if capability.matches(context) < 0.2:
                continue

            usage_count = capability.usage_count + 1
            alpha = 0.3
            new_success = (1.0 if success else 0.0)
            success_rate = (1 - alpha) * capability.success_rate + alpha * new_success
            if duration > 0:
                avg_duration = (
                    (0.7 * capability.avg_duration + 0.3 * duration)
                    if capability.avg_duration > 0
                    else duration
                )
            else:
                avg_duration = capability.avg_duration

            examples = list(capability.examples)
            failures = list(capability.failures)
            if success:
                if len(examples) < 10:
                    examples.append({"timestamp": time.time(), "context": context})
            elif error and len(failures) < 10:
                failures.append(error)

            conn.execute(
                """
                UPDATE capabilities
                SET usage_count = ?, success_rate = ?, avg_duration = ?, last_used = ?, examples = ?, failures = ?
                WHERE capability_id = ?
                """,
                (
                    usage_count,
                    success_rate,
                    avg_duration,
                    time.time(),
                    json.dumps(examples, ensure_ascii=False),
                    json.dumps(failures, ensure_ascii=False),
                    capability.capability_id,
                ),
            )

        conn.commit()
        conn.close()

    def _blacklist_capability(self, capability_id: str, reason: str) -> None:
        conn = sqlite3.connect(self.persist_path)
        conn.execute(
            """
            INSERT INTO capability_blacklist(capability_id, reason, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(capability_id) DO UPDATE SET
                reason = excluded.reason,
                updated_at = excluded.updated_at
            """,
            (capability_id, reason, time.time()),
        )
        conn.commit()
        conn.close()
        self._blacklist.add(capability_id)

    def _analyze_trigger_pattern(self, context: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
        pattern = {
            "event_types": [],
            "keywords": [],
            "requires_params": [],
        }

        event_type = context.get("event_type")
        if event_type:
            pattern["event_types"].append(str(event_type))

        message = str(context.get("message", ""))
        keywords = [word for word in re.split(r"\W+", message) if len(word) >= 4]
        pattern["keywords"] = keywords[:8]

        parameters = action.get("params") if isinstance(action.get("params"), dict) else {}
        pattern["requires_params"] = list(parameters.keys())[:8]

        tool_name = action.get("tool") or action.get("type")
        if tool_name:
            pattern["keywords"].append(str(tool_name))

        return pattern

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

        context_vector = _hash_embedding(json.dumps(context, sort_keys=True, ensure_ascii=False), self.embedding_dimension)

        best_capability: Optional[Capability] = None
        best_score = threshold

        for capability in candidates:
            if capability.capability_id in self._blacklist:
                continue

            pattern_score = capability.matches(context)
            semantic_score = self._semantic_similarity(capability.capability_id, context_vector)
            score = 0.6 * semantic_score + 0.4 * pattern_score

            if score > best_score:
                best_score = score
                best_capability = capability

        return best_capability

    def _semantic_similarity(self, capability_id: str, context_vector: List[float]) -> float:
        conn = sqlite3.connect(self.persist_path)
        cur = conn.cursor()
        cur.execute("SELECT embedding FROM capabilities WHERE capability_id = ?", (capability_id,))
        row = cur.fetchone()
        conn.close()

        if not row:
            return 0.0

        try:
            capability_vector = json.loads(row[0])
        except Exception:
            return 0.0

        return _cosine_similarity(context_vector, capability_vector)

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


def _hash_embedding(text: str, dimension: int) -> List[float]:
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    buf = bytearray(seed)
    while len(buf) < dimension:
        buf.extend(hashlib.sha256(bytes(buf[-32:])).digest())
    return [float(byte) / 255.0 for byte in buf[:dimension]]


def _cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    limit = min(len(vec1), len(vec2))
    if limit == 0:
        return 0.0

    dot = 0.0
    norm1 = 0.0
    norm2 = 0.0
    for index in range(limit):
        left = float(vec1[index])
        right = float(vec2[index])
        dot += left * right
        norm1 += left * left
        norm2 += right * right

    denom = math.sqrt(norm1) * math.sqrt(norm2)
    if denom <= 0.0:
        return 0.0

    return dot / denom
