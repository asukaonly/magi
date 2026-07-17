"""Task preference operations backed by L4 procedural memory."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

import aiosqlite

from ...core.sqlite import sqlite_connection_async
from .source_event_governance import (
    active_skill_predicate,
    link_skill_source_event,
    skill_accepts_source_event,
)
from .storage.records import sync_skill_fts

TASK_PREFERENCE_CATEGORY = "task_preference"


@dataclass(frozen=True)
class _TaskPreferenceDraft:
    user_id: str
    persona_id: str
    task_category: str
    preference: str
    polarity: str
    evidence_text: str
    confidence: float
    turn_id: str
    session_id: str
    display_skill_name: str
    storage_skill_name: str
    content: str
    params: dict[str, Any]
    context_affinity: dict[str, float]


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
        draft = _build_task_preference_draft(
            user_id=user_id,
            persona_id=persona_id,
            task_category=task_category,
            preference=preference,
            polarity=polarity,
            evidence_text=evidence_text,
            confidence=confidence,
            turn_id=turn_id,
            session_id=session_id,
        )
        if draft is None:
            return None

        await self.initialize()
        await self.retire_governed_skill_identity(
            skill_name=draft.storage_skill_name,
            skill_category=TASK_PREFERENCE_CATEGORY,
        )
        skill_id = await self._upsert_task_preference(draft)
        if skill_id is None:
            return None

        await self._schedule_skill_embedding(
            skill_id=skill_id,
            skill_name=draft.display_skill_name,
            skill_category=TASK_PREFERENCE_CATEGORY,
            optimized_prompt=draft.content,
        )
        return skill_id

    async def _upsert_task_preference(self, draft: _TaskPreferenceDraft) -> str | None:
        now = time.time()
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            if draft.turn_id and not await skill_accepts_source_event(
                db,
                event_id=draft.turn_id,
            ):
                await db.rollback()
                return None
            existing = await _fetch_existing_task_preference(db, draft.storage_skill_name)

            if existing is None:
                skill_id = f"task_pref_{uuid.uuid4().hex}"
                await _insert_task_preference_row(
                    db,
                    draft=draft,
                    skill_id=skill_id,
                    source_event_ids=_source_event_ids(None, draft.turn_id),
                    now=now,
                )
                replace_existing = False
            else:
                skill_id = str(existing["skill_id"])
                await _update_task_preference_row(
                    db,
                    draft=draft,
                    existing=existing,
                    skill_id=skill_id,
                    source_event_ids=_source_event_ids(existing["source_event_ids"], draft.turn_id),
                    now=now,
                )
                replace_existing = True

            if draft.turn_id:
                await link_skill_source_event(
                    db,
                    skill_id=skill_id,
                    event_id=draft.turn_id,
                    created_at=now,
                )

            await sync_skill_fts(
                db,
                skill_id=skill_id,
                skill_name=draft.display_skill_name,
                skill_category=TASK_PREFERENCE_CATEGORY,
                optimized_prompt=draft.content,
                replace_existing=replace_existing,
            )
            await db.commit()
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
                f"""
                SELECT *
                FROM procedural_skills AS skills
                WHERE skills.skill_category = ?
                  AND {active_skill_predicate("skills")}
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


def _build_task_preference_draft(
    *,
    user_id: str,
    persona_id: str,
    task_category: str,
    preference: str,
    polarity: str,
    evidence_text: str,
    confidence: float,
    turn_id: str,
    session_id: str,
) -> _TaskPreferenceDraft | None:
    normalized_user_id = _clean(user_id)
    normalized_task_category = _clean(task_category) or "chat"
    normalized_preference = _clean(preference)
    normalized_polarity = _normalize_polarity(polarity)
    if not normalized_user_id or not normalized_preference:
        return None

    confidence_value = _clamp_confidence(confidence)
    normalized_persona_id = _clean(persona_id)
    normalized_evidence_text = _clean(evidence_text)
    display_skill_name = _display_skill_name(
        task_category=normalized_task_category,
        polarity=normalized_polarity,
        preference=normalized_preference,
    )
    content = _preference_content(
        polarity=normalized_polarity,
        preference=normalized_preference,
        evidence_text=normalized_evidence_text,
    )
    params = {
        "kind": TASK_PREFERENCE_CATEGORY,
        "user_id": normalized_user_id,
        "persona_id": normalized_persona_id,
        "task_category": normalized_task_category,
        "preference": normalized_preference,
        "polarity": normalized_polarity,
        "evidence_text": normalized_evidence_text,
        "confidence": confidence_value,
        "turn_id": _clean(turn_id),
        "session_id": _clean(session_id),
        "display_skill_name": display_skill_name,
    }
    return _TaskPreferenceDraft(
        user_id=normalized_user_id,
        persona_id=normalized_persona_id,
        task_category=normalized_task_category,
        preference=normalized_preference,
        polarity=normalized_polarity,
        evidence_text=normalized_evidence_text,
        confidence=confidence_value,
        turn_id=_clean(turn_id),
        session_id=_clean(session_id),
        display_skill_name=display_skill_name,
        storage_skill_name=_storage_skill_name(
            user_id=normalized_user_id,
            persona_id=normalized_persona_id,
            display_skill_name=display_skill_name,
        ),
        content=content,
        params=params,
        context_affinity={normalized_task_category: confidence_value},
    )


async def _fetch_existing_task_preference(
    db: aiosqlite.Connection,
    storage_skill_name: str,
) -> aiosqlite.Row | None:
    async with db.execute(
        f"""
        SELECT skills.skill_id, skills.source_event_ids,
               skills.total_attempts, skills.success_count
        FROM procedural_skills AS skills
        WHERE skills.skill_name = ? AND skills.skill_category = ?
          AND {active_skill_predicate("skills")}
        """,
        (storage_skill_name, TASK_PREFERENCE_CATEGORY),
    ) as cursor:
        return await cursor.fetchone()


async def _insert_task_preference_row(
    db: aiosqlite.Connection,
    *,
    draft: _TaskPreferenceDraft,
    skill_id: str,
    source_event_ids: list[str],
    now: float,
) -> None:
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
            draft.storage_skill_name,
            TASK_PREFERENCE_CATEGORY,
            TASK_PREFERENCE_CATEGORY,
            draft.confidence,
            1,
            1,
            0,
            draft.confidence,
            0.0,
            0.0,
            0.0,
            0.0,
            "closed",
            None,
            0,
            0,
            draft.content,
            json.dumps(draft.params, ensure_ascii=False),
            draft.confidence,
            json.dumps(draft.context_affinity, ensure_ascii=False),
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


async def _update_task_preference_row(
    db: aiosqlite.Connection,
    *,
    draft: _TaskPreferenceDraft,
    existing: aiosqlite.Row,
    skill_id: str,
    source_event_ids: list[str],
    now: float,
) -> None:
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
            draft.confidence,
            total_attempts,
            success_count,
            draft.confidence,
            draft.content,
            json.dumps(draft.params, ensure_ascii=False),
            draft.confidence,
            json.dumps(draft.context_affinity, ensure_ascii=False),
            json.dumps(source_event_ids, ensure_ascii=False),
            now,
            now,
            now,
            skill_id,
        ),
    )


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
