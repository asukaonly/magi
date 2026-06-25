"""Task preference operations backed by L4 procedural memory."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from .storage.records import sync_skill_fts

TASK_PREFERENCE_CATEGORY = "task_preference"


class L4TaskPreferenceMixin:
    """Store explicit user task-handling preferences as procedural memory."""

    db_path: str

    async def initialize(self) -> None:
        raise NotImplementedError

    async def _schedule_skill_embedding(
        self,
        *,
        skill_id: str,
        skill_name: str,
        skill_category: str,
        optimized_prompt: str | None,
    ) -> None:
        raise NotImplementedError

    async def record_task_preference(
        self,
        *,
        user_id: str,
        persona_id: str = "",
        task_category: str,
        preference: str,
        polarity: str = "prefer",
        evidence_text: str = "",
        confidence: float = 0.0,
        turn_id: str = "",
        session_id: str = "",
    ) -> str | None:
        """Persist an explicit future task-handling preference."""
        normalized_user_id = _clean(user_id)
        normalized_task_category = _clean(task_category) or "chat"
        normalized_preference = _clean(preference)
        normalized_polarity = _normalize_polarity(polarity)
        if not normalized_user_id or not normalized_preference:
            return None

        await self.initialize()
        confidence_value = _clamp_confidence(confidence)
        now = time.time()
        display_skill_name = _display_skill_name(
            task_category=normalized_task_category,
            polarity=normalized_polarity,
            preference=normalized_preference,
        )
        storage_skill_name = _storage_skill_name(
            user_id=normalized_user_id,
            persona_id=_clean(persona_id),
            display_skill_name=display_skill_name,
        )
        content = _preference_content(
            polarity=normalized_polarity,
            preference=normalized_preference,
            evidence_text=_clean(evidence_text),
        )
        params = {
            "kind": TASK_PREFERENCE_CATEGORY,
            "user_id": normalized_user_id,
            "persona_id": _clean(persona_id),
            "task_category": normalized_task_category,
            "preference": normalized_preference,
            "polarity": normalized_polarity,
            "evidence_text": _clean(evidence_text),
            "confidence": confidence_value,
            "turn_id": _clean(turn_id),
            "session_id": _clean(session_id),
            "display_skill_name": display_skill_name,
        }
        context_affinity = {normalized_task_category: confidence_value}

        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT skill_id, source_event_ids, total_attempts, success_count
                FROM procedural_skills
                WHERE skill_name = ? AND skill_category = ? AND deleted_at IS NULL
                """,
                (storage_skill_name, TASK_PREFERENCE_CATEGORY),
            ) as cursor:
                existing = await cursor.fetchone()

            if existing is None:
                skill_id = f"task_pref_{uuid.uuid4().hex}"
                source_event_ids = _source_event_ids(None, turn_id)
                await db.execute(
                    """
                    INSERT INTO procedural_skills(
                        skill_id, skill_name, skill_category, skill_type, proficiency,
                        total_attempts, success_count, failure_count, success_rate,
                        avg_execution_time_ms, min_execution_time_ms, max_execution_time_ms, p95_execution_time_ms,
                        circuit_breaker_state, circuit_breaker_opened_at, circuit_breaker_failure_count,
                        circuit_breaker_success_count, optimized_prompt, optimized_params, optimization_score,
                        context_affinity, source_event_ids, last_used_at, last_success_at, last_failure_at,
                        embedding_chunk_count, last_embedded_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        skill_id,
                        storage_skill_name,
                        TASK_PREFERENCE_CATEGORY,
                        TASK_PREFERENCE_CATEGORY,
                        confidence_value,
                        1,
                        1,
                        0,
                        confidence_value,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        "closed",
                        None,
                        0,
                        0,
                        content,
                        json.dumps(params, ensure_ascii=False),
                        confidence_value,
                        json.dumps(context_affinity, ensure_ascii=False),
                        json.dumps(source_event_ids, ensure_ascii=False),
                        now,
                        now,
                        None,
                        0,
                        None,
                        now,
                        now,
                    ),
                )
                replace_existing = False
            else:
                skill_id = str(existing["skill_id"])
                source_event_ids = _source_event_ids(existing["source_event_ids"], turn_id)
                total_attempts = int(existing["total_attempts"] or 0) + 1
                success_count = int(existing["success_count"] or 0) + 1
                await db.execute(
                    """
                    UPDATE procedural_skills
                    SET proficiency = ?, total_attempts = ?, success_count = ?, failure_count = 0,
                        success_rate = ?, optimized_prompt = ?, optimized_params = ?,
                        optimization_score = ?, context_affinity = ?, source_event_ids = ?,
                        last_used_at = ?, last_success_at = ?, updated_at = ?
                    WHERE skill_id = ?
                    """,
                    (
                        confidence_value,
                        total_attempts,
                        success_count,
                        confidence_value,
                        content,
                        json.dumps(params, ensure_ascii=False),
                        confidence_value,
                        json.dumps(context_affinity, ensure_ascii=False),
                        json.dumps(source_event_ids, ensure_ascii=False),
                        now,
                        now,
                        now,
                        skill_id,
                    ),
                )
                replace_existing = True

            await sync_skill_fts(
                db,
                skill_id=skill_id,
                skill_name=display_skill_name,
                skill_category=TASK_PREFERENCE_CATEGORY,
                optimized_prompt=content,
                replace_existing=replace_existing,
            )
            await db.commit()

        await self._schedule_skill_embedding(
            skill_id=skill_id,
            skill_name=display_skill_name,
            skill_category=TASK_PREFERENCE_CATEGORY,
            optimized_prompt=content,
        )
        return skill_id

    async def get_task_preferences(
        self,
        *,
        user_id: str,
        task_category: str,
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        """Return task-handling preferences as prompt-ready L4 items."""
        normalized_user_id = _clean(user_id)
        normalized_task_category = _clean(task_category) or "chat"
        if not normalized_user_id:
            return []

        await self.initialize()
        resolved_limit = max(1, int(limit))
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT *
                FROM procedural_skills
                WHERE skill_category = ? AND deleted_at IS NULL
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (TASK_PREFERENCE_CATEGORY, resolved_limit * 4),
            ) as cursor:
                rows = await cursor.fetchall()

        preferences: list[dict[str, Any]] = []
        for row in rows:
            item = _task_preference_row_to_item(row)
            if item is None:
                continue
            if item["user_id"] != normalized_user_id:
                continue
            if item["task_category"] != normalized_task_category:
                continue
            item.pop("user_id", None)
            preferences.append(item)
            if len(preferences) >= resolved_limit:
                break
        return preferences


def _task_preference_row_to_item(row: aiosqlite.Row) -> dict[str, Any] | None:
    try:
        params = json.loads(row["optimized_params"] or "{}")
    except (TypeError, json.JSONDecodeError):
        return None
    if params.get("kind") != TASK_PREFERENCE_CATEGORY:
        return None

    task_category = _clean(params.get("task_category")) or "chat"
    preference = _clean(params.get("preference"))
    polarity = _normalize_polarity(params.get("polarity"))
    if not preference:
        return None
    evidence_text = _clean(params.get("evidence_text"))
    content = _preference_content(
        polarity=polarity,
        preference=preference,
        evidence_text=evidence_text,
    )
    return {
        "skill_id": str(row["skill_id"]),
        "skill_name": _display_skill_name(
            task_category=task_category,
            polarity=polarity,
            preference=preference,
        ),
        "skill_category": TASK_PREFERENCE_CATEGORY,
        "skill_type": TASK_PREFERENCE_CATEGORY,
        "summary": _preference_summary(polarity=polarity, preference=preference),
        "content": content,
        "polarity": polarity,
        "task_category": task_category,
        "preference": preference,
        "confidence": _clamp_confidence(params.get("confidence")),
        "source_event_ids": _source_event_ids(row["source_event_ids"], None),
        "user_id": _clean(params.get("user_id")),
    }


def _display_skill_name(*, task_category: str, polarity: str, preference: str) -> str:
    return f"{task_category}:{polarity}:{preference}"


def _storage_skill_name(*, user_id: str, persona_id: str, display_skill_name: str) -> str:
    persona_part = persona_id or "default"
    return f"task_preference:{user_id}:{persona_part}:{display_skill_name}"


def _preference_summary(*, polarity: str, preference: str) -> str:
    label = "Avoid" if polarity == "avoid" else "Prefer"
    return f"{label}: {preference}"


def _preference_content(*, polarity: str, preference: str, evidence_text: str) -> str:
    summary = _preference_summary(polarity=polarity, preference=preference)
    if not evidence_text:
        return summary
    return f"{summary}\nEvidence: {evidence_text}"


def _source_event_ids(raw: Any, turn_id: str | None) -> list[str]:
    result: list[str] = []
    if raw:
        try:
            loaded = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(loaded, list):
                result = [_clean(item) for item in loaded if _clean(item)]
        except (TypeError, json.JSONDecodeError):
            result = []
    normalized_turn_id = _clean(turn_id)
    if normalized_turn_id and normalized_turn_id not in result:
        result.append(normalized_turn_id)
    return result[-100:]


def _normalize_polarity(value: Any) -> str:
    normalized = _clean(value).casefold()
    return "avoid" if normalized == "avoid" else "prefer"


def _clamp_confidence(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = 0.0
    return max(0.0, min(1.0, parsed))


def _clean(value: Any) -> str:
    return str(value or "").strip()


__all__ = ["L4TaskPreferenceMixin", "TASK_PREFERENCE_CATEGORY"]
