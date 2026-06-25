"""Explicit task preference storage for behavior evolution."""

from __future__ import annotations

import time
import uuid
from typing import Any

import aiosqlite

from ..core.sqlite import sqlite_connection_async


class BehaviorEvolutionPreferenceMixin:
    """Persist explicit user preferences for future task handling."""

    _expanded_db_path: str
    persona_id: str
    _cache: dict[str, Any]

    async def record_task_preference(
        self,
        *,
        task_category: str,
        preference: str,
        polarity: str = "prefer",
        evidence_text: str = "",
        confidence: float = 0.0,
        user_id: str = "",
        session_id: str = "",
        turn_id: str = "",
    ) -> bool:
        category = str(task_category or "chat").strip() or "chat"
        text = " ".join(str(preference or "").split())
        normalized_polarity = str(polarity or "prefer").strip().casefold()
        if normalized_polarity not in {"prefer", "avoid"}:
            normalized_polarity = "prefer"
        if not text:
            return False
        try:
            score = float(confidence)
        except (TypeError, ValueError):
            score = 0.0
        score = max(0.0, min(1.0, score))
        if score < 0.65:
            return False

        now = time.time()
        async with sqlite_connection_async(self._expanded_db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS task_preferences (
                    preference_id TEXT PRIMARY KEY,
                    task_category TEXT NOT NULL,
                    polarity TEXT NOT NULL,
                    preference_text TEXT NOT NULL,
                    evidence_text TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    user_id TEXT NOT NULL DEFAULT '',
                    session_id TEXT NOT NULL DEFAULT '',
                    turn_id TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    persona_id TEXT NOT NULL DEFAULT ''
                )
                """
            )
            async with db.execute(
                """
                SELECT preference_id, confidence FROM task_preferences
                WHERE task_category = ? AND polarity = ? AND preference_text = ? AND persona_id = ?
                LIMIT 1
                """,
                (category, normalized_polarity, text, self.persona_id),
            ) as cursor:
                existing = await cursor.fetchone()
            if existing is None:
                await db.execute(
                    """
                    INSERT INTO task_preferences(
                        preference_id, task_category, polarity, preference_text,
                        evidence_text, confidence, user_id, session_id, turn_id,
                        created_at, updated_at, persona_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"task_pref_{uuid.uuid4().hex}",
                        category,
                        normalized_polarity,
                        text,
                        str(evidence_text or "").strip()[:500],
                        score,
                        str(user_id or "").strip(),
                        str(session_id or "").strip(),
                        str(turn_id or "").strip(),
                        now,
                        now,
                        self.persona_id,
                    ),
                )
            else:
                await db.execute(
                    """
                    UPDATE task_preferences
                    SET evidence_text = ?, confidence = ?, user_id = ?,
                        session_id = ?, turn_id = ?, updated_at = ?
                    WHERE preference_id = ?
                    """,
                    (
                        str(evidence_text or "").strip()[:500],
                        max(score, float(existing["confidence"])),
                        str(user_id or "").strip(),
                        str(session_id or "").strip(),
                        str(turn_id or "").strip(),
                        now,
                        str(existing["preference_id"]),
                    ),
                )
            await db.commit()

        self._cache.pop(category, None)
        return True

    async def get_task_preferences(self, task_category: str, *, limit: int = 8) -> dict[str, list[str]]:
        category = str(task_category or "chat").strip() or "chat"
        async with sqlite_connection_async(self._expanded_db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS task_preferences (
                    preference_id TEXT PRIMARY KEY,
                    task_category TEXT NOT NULL,
                    polarity TEXT NOT NULL,
                    preference_text TEXT NOT NULL,
                    evidence_text TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    user_id TEXT NOT NULL DEFAULT '',
                    session_id TEXT NOT NULL DEFAULT '',
                    turn_id TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    persona_id TEXT NOT NULL DEFAULT ''
                )
                """
            )
            async with db.execute(
                """
                SELECT polarity, preference_text FROM task_preferences
                WHERE task_category = ? AND persona_id = ?
                ORDER BY confidence DESC, updated_at DESC
                LIMIT ?
                """,
                (category, self.persona_id, int(limit)),
            ) as cursor:
                rows = await cursor.fetchall()
        prefers: list[str] = []
        avoids: list[str] = []
        for row in rows:
            text = str(row["preference_text"] or "").strip()
            if not text:
                continue
            if str(row["polarity"] or "").strip() == "avoid":
                avoids.append(text)
            else:
                prefers.append(text)
        return {
            "response_prefers": list(dict.fromkeys(prefers)),
            "response_avoids": list(dict.fromkeys(avoids)),
        }


__all__ = ["BehaviorEvolutionPreferenceMixin"]
