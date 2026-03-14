"""L4 procedural memory store."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

from .event_contracts import MemoryEvent


class L4ProceduralMemoryStore:
    """Tracks procedural skills and breaker state from historical attempts."""

    def __init__(
        self,
        *,
        db_path: str = "~/.magi/data/memory_l4.db",
        breaker_failure_threshold: int = 3,
        breaker_recovery_successes: int = 2,
    ) -> None:
        self.db_path = str(Path(db_path).expanduser())
        self.breaker_failure_threshold = int(breaker_failure_threshold)
        self.breaker_recovery_successes = int(breaker_recovery_successes)
        self._initialized = False

    async def initialize(self) -> None:
        """Create the procedural memory schema."""
        if self._initialized:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS procedural_skills (
                    skill_id TEXT PRIMARY KEY,
                    skill_name TEXT NOT NULL,
                    skill_category TEXT NOT NULL,
                    skill_type TEXT NOT NULL,
                    proficiency REAL NOT NULL DEFAULT 0.0,
                    total_attempts INTEGER NOT NULL DEFAULT 0,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    success_rate REAL NOT NULL DEFAULT 0.0,
                    avg_execution_time_ms REAL,
                    min_execution_time_ms REAL,
                    max_execution_time_ms REAL,
                    p95_execution_time_ms REAL,
                    circuit_breaker_state TEXT NOT NULL DEFAULT 'closed',
                    circuit_breaker_opened_at REAL,
                    circuit_breaker_failure_count INTEGER NOT NULL DEFAULT 0,
                    circuit_breaker_success_count INTEGER NOT NULL DEFAULT 0,
                    optimized_prompt TEXT,
                    optimized_params TEXT,
                    optimization_score REAL,
                    context_affinity TEXT,
                    source_event_ids TEXT NOT NULL,
                    last_used_at REAL,
                    last_success_at REAL,
                    last_failure_at REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(skill_name, skill_category)
                );
                CREATE INDEX IF NOT EXISTS idx_procedural_skill_name ON procedural_skills(skill_name, skill_category);

                CREATE TABLE IF NOT EXISTS l4_skill_vectors (
                    vector_id TEXT PRIMARY KEY,
                    skill_id TEXT NOT NULL,
                    embedding_model TEXT NOT NULL,
                    embedding_dim INTEGER NOT NULL,
                    embedding_payload BLOB NOT NULL,
                    metadata TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(skill_id, embedding_model)
                );
                CREATE INDEX IF NOT EXISTS idx_l4_skill_vectors_skill ON l4_skill_vectors(skill_id);
                CREATE INDEX IF NOT EXISTS idx_l4_skill_vectors_model ON l4_skill_vectors(embedding_model);
                """
            )
            await db.commit()
        self._initialized = True

    async def record_memory_event(self, event: MemoryEvent) -> Optional[str]:
        """Update procedural memory based on a normalized event."""
        identity = self._extract_skill_identity(event)
        if identity is None:
            return None

        await self.initialize()
        skill_name, skill_category, skill_type, success, duration_ms, error, optimized_prompt = identity
        now = time.time()

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM procedural_skills WHERE skill_name = ? AND skill_category = ?",
                (skill_name, skill_category),
            ) as cursor:
                existing = await cursor.fetchone()

            if existing is None:
                skill_id = f"skill_{uuid.uuid4().hex}"
                total_attempts = 1
                success_count = 1 if success else 0
                failure_count = 0 if success else 1
                avg_duration = duration_ms
                min_duration = duration_ms
                max_duration = duration_ms
                breaker_state = "closed"
                breaker_opened_at = None
                failure_streak = 0 if success else 1
                recovery_count = 0
                if failure_streak >= self.breaker_failure_threshold:
                    breaker_state = "open"
                    breaker_opened_at = event.timestamp
                await db.execute(
                    """
                    INSERT INTO procedural_skills(
                        skill_id, skill_name, skill_category, skill_type, proficiency,
                        total_attempts, success_count, failure_count, success_rate,
                        avg_execution_time_ms, min_execution_time_ms, max_execution_time_ms, p95_execution_time_ms,
                        circuit_breaker_state, circuit_breaker_opened_at, circuit_breaker_failure_count,
                        circuit_breaker_success_count, optimized_prompt, optimized_params, optimization_score,
                        context_affinity, source_event_ids, last_used_at, last_success_at, last_failure_at,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        skill_id,
                        skill_name,
                        skill_category,
                        skill_type,
                        float(success_count / total_attempts),
                        total_attempts,
                        success_count,
                        failure_count,
                        float(success_count / total_attempts),
                        duration_ms,
                        duration_ms,
                        duration_ms,
                        duration_ms,
                        breaker_state,
                        breaker_opened_at,
                        failure_streak,
                        recovery_count,
                        optimized_prompt,
                        json.dumps({}, ensure_ascii=False),
                        None,
                        json.dumps({}, ensure_ascii=False),
                        json.dumps([event.event_id], ensure_ascii=False),
                        float(event.timestamp),
                        float(event.timestamp) if success else None,
                        float(event.timestamp) if not success else None,
                        now,
                        now,
                    ),
                )
                await db.commit()
                return skill_id

            total_attempts = int(existing["total_attempts"]) + 1
            success_count = int(existing["success_count"]) + (1 if success else 0)
            failure_count = int(existing["failure_count"]) + (0 if success else 1)
            avg_duration = self._rolling_average(existing["avg_execution_time_ms"], total_attempts - 1, duration_ms)
            min_duration = min(float(existing["min_execution_time_ms"] or duration_ms), duration_ms)
            max_duration = max(float(existing["max_execution_time_ms"] or duration_ms), duration_ms)
            source_event_ids = json.loads(existing["source_event_ids"] or "[]")
            source_event_ids.append(event.event_id)
            breaker_state = str(existing["circuit_breaker_state"])
            failure_streak = int(existing["circuit_breaker_failure_count"])
            recovery_count = int(existing["circuit_breaker_success_count"])
            breaker_opened_at = float(existing["circuit_breaker_opened_at"]) if existing["circuit_breaker_opened_at"] else None

            if success:
                failure_streak = 0
                if breaker_state == "open":
                    breaker_state = "half_open"
                    recovery_count = 1
                elif breaker_state == "half_open":
                    recovery_count += 1
                    if recovery_count >= self.breaker_recovery_successes:
                        breaker_state = "closed"
                        recovery_count = 0
                        breaker_opened_at = None
                else:
                    recovery_count = 0
            else:
                recovery_count = 0
                failure_streak += 1
                if failure_streak >= self.breaker_failure_threshold:
                    breaker_state = "open"
                    breaker_opened_at = event.timestamp

            await db.execute(
                """
                UPDATE procedural_skills
                SET proficiency = ?, total_attempts = ?, success_count = ?, failure_count = ?, success_rate = ?,
                    avg_execution_time_ms = ?, min_execution_time_ms = ?, max_execution_time_ms = ?, p95_execution_time_ms = ?,
                    circuit_breaker_state = ?, circuit_breaker_opened_at = ?, circuit_breaker_failure_count = ?,
                    circuit_breaker_success_count = ?, optimized_prompt = COALESCE(?, optimized_prompt),
                    source_event_ids = ?, last_used_at = ?, last_success_at = ?, last_failure_at = ?, updated_at = ?
                WHERE skill_id = ?
                """,
                (
                    float(success_count / total_attempts),
                    total_attempts,
                    success_count,
                    failure_count,
                    float(success_count / total_attempts),
                    avg_duration,
                    min_duration,
                    max_duration,
                    max_duration,
                    breaker_state,
                    breaker_opened_at,
                    failure_streak,
                    recovery_count,
                    optimized_prompt,
                    json.dumps(source_event_ids[-100:], ensure_ascii=False),
                    float(event.timestamp),
                    float(event.timestamp) if success else existing["last_success_at"],
                    float(event.timestamp) if not success else existing["last_failure_at"],
                    now,
                    str(existing["skill_id"]),
                ),
            )
            await db.commit()
            return str(existing["skill_id"])

    async def get_skill(self, *, skill_name: str, skill_category: str) -> Optional[Dict[str, Any]]:
        """Fetch a single procedural skill."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM procedural_skills WHERE skill_name = ? AND skill_category = ?",
                (skill_name, skill_category),
            ) as cursor:
                row = await cursor.fetchone()
        return self._row_to_dict(row) if row else None

    async def get_all_skills(self, *, limit: int = 100) -> List[Dict[str, Any]]:
        """List all stored skills."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM procedural_skills ORDER BY updated_at DESC LIMIT ?",
                (int(limit),),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    async def query_strategies(self, *, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search procedural skills by name or optimized prompt."""
        await self.initialize()
        like_query = f"%{query}%"
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM procedural_skills
                WHERE skill_name LIKE ? OR COALESCE(optimized_prompt, '') LIKE ?
                ORDER BY success_rate DESC, updated_at DESC
                LIMIT ?
                """,
                (like_query, like_query, int(limit)),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    async def clear(self) -> int:
        """Delete all procedural skills."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM procedural_skills") as cursor:
                row = await cursor.fetchone()
                count = int(row[0]) if row else 0
            await db.execute("DELETE FROM procedural_skills")
            await db.commit()
        return count

    def get_statistics(self) -> Dict[str, Any]:
        """Return lightweight metadata for higher-level reporting."""
        return {"db_path": self.db_path}

    def _extract_skill_identity(
        self,
        event: MemoryEvent,
    ) -> Optional[tuple[str, str, str, bool, float, Optional[str], Optional[str]]]:
        payload = event.structured_payload if isinstance(event.structured_payload, dict) else None
        if payload is None:
            try:
                payload = json.loads(event.structured_payload)
            except Exception:
                payload = {}

        if event.event_type == "ActionExecuted":
            skill_name = str(payload.get("action_type") or "").strip()
            if not skill_name:
                return None
            return (
                skill_name,
                "tool",
                "external_tool",
                bool(payload.get("success", True)),
                float(payload.get("execution_time", 0.0) or 0.0),
                payload.get("error"),
                payload.get("optimized_prompt"),
            )

        if event.event_type == "TaskCompleted":
            skill_name = str(payload.get("task_id") or "task").strip()
            return (
                skill_name,
                "workflow",
                "composite",
                bool(payload.get("success", True)),
                float(payload.get("duration", 0.0) or 0.0),
                payload.get("error"),
                payload.get("optimized_prompt"),
            )

        if event.event_type == "TaskFailed":
            skill_name = str(payload.get("task_id") or "task").strip()
            return (
                skill_name,
                "workflow",
                "composite",
                False,
                float(payload.get("duration", 0.0) or 0.0),
                payload.get("error"),
                payload.get("optimized_prompt"),
            )

        return None

    def _rolling_average(self, current_value: Any, current_count: int, next_value: float) -> float:
        current = float(current_value or 0.0)
        if current_count <= 0:
            return next_value
        return ((current * current_count) + next_value) / (current_count + 1)

    def _row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]:
        return {
            "skill_id": str(row["skill_id"]),
            "skill_name": str(row["skill_name"]),
            "skill_category": str(row["skill_category"]),
            "skill_type": str(row["skill_type"]),
            "proficiency": float(row["proficiency"]),
            "total_attempts": int(row["total_attempts"]),
            "success_count": int(row["success_count"]),
            "failure_count": int(row["failure_count"]),
            "success_rate": float(row["success_rate"]),
            "avg_execution_time_ms": float(row["avg_execution_time_ms"] or 0.0),
            "min_execution_time_ms": float(row["min_execution_time_ms"] or 0.0),
            "max_execution_time_ms": float(row["max_execution_time_ms"] or 0.0),
            "p95_execution_time_ms": float(row["p95_execution_time_ms"] or 0.0),
            "circuit_breaker_state": str(row["circuit_breaker_state"]),
            "circuit_breaker_opened_at": float(row["circuit_breaker_opened_at"]) if row["circuit_breaker_opened_at"] else None,
            "circuit_breaker_failure_count": int(row["circuit_breaker_failure_count"]),
            "circuit_breaker_success_count": int(row["circuit_breaker_success_count"]),
            "optimized_prompt": row["optimized_prompt"],
            "optimized_params": json.loads(row["optimized_params"] or "{}"),
            "optimization_score": float(row["optimization_score"]) if row["optimization_score"] is not None else None,
            "context_affinity": json.loads(row["context_affinity"] or "{}"),
            "source_event_ids": json.loads(row["source_event_ids"] or "[]"),
            "last_used_at": float(row["last_used_at"]) if row["last_used_at"] else None,
            "last_success_at": float(row["last_success_at"]) if row["last_success_at"] else None,
            "last_failure_at": float(row["last_failure_at"]) if row["last_failure_at"] else None,
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }


__all__ = ["L4ProceduralMemoryStore"]
