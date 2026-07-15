"""SQLite persistence helpers for L2 ToM snapshots."""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict

import aiosqlite


def _snapshot_payload(
    *,
    state: dict[str, Any],
    evolution_payload: Dict[str, Any],
    mood_trajectory: list[dict[str, Any]],
    source_revision: int,
    now: float,
) -> tuple[Any, ...]:
    return (
        json.dumps(state["core_traits"], ensure_ascii=False),
        json.dumps(sorted(set(state["sensitive_triggers"])), ensure_ascii=False),
        json.dumps(state["preferences"], ensure_ascii=False),
        json.dumps(state["public_sentiment_profile"], ensure_ascii=False),
        json.dumps(state["relationship_topology"], ensure_ascii=False),
        float(state["current_stress_level"]),
        state["current_mood"],
        float(state["current_engagement"]),
        json.dumps(state["current_context"], ensure_ascii=False),
        state["interaction_count"],
        state["last_interaction_at"],
        now,
        json.dumps(state["update_source_assertion_ids"], ensure_ascii=False),
        json.dumps(evolution_payload["core_traits_history"], ensure_ascii=False),
        json.dumps(evolution_payload["preferences_history"], ensure_ascii=False),
        json.dumps(evolution_payload["relationship_history"], ensure_ascii=False),
        evolution_payload["last_evolution_at"],
        json.dumps(evolution_payload["active_record_ids"], ensure_ascii=False),
        json.dumps(evolution_payload["superseded_record_ids"], ensure_ascii=False),
        json.dumps(state["emerging_signals"], ensure_ascii=False),
        json.dumps(mood_trajectory, ensure_ascii=False),
        int(source_revision),
    )


async def _update_snapshot_payload(
    db: aiosqlite.Connection,
    *,
    snapshot_id: str,
    payload: tuple[Any, ...],
) -> None:
    await db.execute(
        """
        UPDATE tom_snapshots
        SET core_traits = ?, sensitive_triggers = ?, preferences = ?,
            public_sentiment_profile = ?, relationship_topology = ?,
            current_stress_level = ?, current_mood = ?, current_engagement = ?,
            current_context = ?, interaction_count = ?, last_interaction_at = ?,
            last_updated_at = ?, update_source_assertion_ids = ?,
            core_traits_history = ?, preferences_history = ?, relationship_history = ?,
            last_evolution_at = ?, active_record_ids = ?, superseded_record_ids = ?,
            emerging_signals = ?, mood_trajectory = ?,
            source_revision = ?,
            snapshot_version = snapshot_version + 1
        WHERE snapshot_id = ?
        """,
        payload + (snapshot_id,),
    )


async def _insert_snapshot_payload(
    db: aiosqlite.Connection,
    *,
    entity_id: str,
    entity_type: str,
    payload: tuple[Any, ...],
    now: float,
) -> None:
    await db.execute(
        """
        INSERT INTO tom_snapshots(
            snapshot_id, entity_id, entity_type, core_traits, sensitive_triggers,
            preferences, public_sentiment_profile, relationship_topology,
            current_stress_level, current_mood, current_engagement, current_context,
            interaction_count, last_interaction_at, last_updated_at,
            update_source_assertion_ids, core_traits_history, preferences_history,
            relationship_history, last_evolution_at, active_record_ids,
            superseded_record_ids, emerging_signals, mood_trajectory,
            source_revision, snapshot_version, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (f"snapshot_{uuid.uuid4().hex}", entity_id, entity_type) + payload + (1, now),
    )


class L2SnapshotPersistenceMixin:
    """Write assembled snapshot payloads to the ToM snapshot table."""

    async def _persist_snapshot_payload(
        self,
        *,
        db: aiosqlite.Connection,
        existing: aiosqlite.Row | None,
        entity_id: str,
        entity_type: str,
        state: dict[str, Any],
        evolution_payload: Dict[str, Any],
        mood_trajectory: list[dict[str, Any]],
        source_revision: int,
        now: float,
    ) -> None:
        payload = _snapshot_payload(
            state=state,
            evolution_payload=evolution_payload,
            mood_trajectory=mood_trajectory,
            source_revision=source_revision,
            now=now,
        )
        if existing:
            await _update_snapshot_payload(
                db,
                snapshot_id=str(existing["snapshot_id"]),
                payload=payload,
            )
            return
        await _insert_snapshot_payload(
            db,
            entity_id=entity_id,
            entity_type=entity_type,
            payload=payload,
            now=now,
        )


__all__ = ["L2SnapshotPersistenceMixin"]
