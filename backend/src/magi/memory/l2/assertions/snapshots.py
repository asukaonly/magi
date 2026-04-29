"""Snapshot persistence helpers for the L2 cognition store."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional, Protocol, cast

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from ..storage.utils import MOOD_TRAJECTORY_FAMILIES, MOOD_TRAJECTORY_LIMIT


class _SnapshotHostProtocol(Protocol):
    db_path: str

    def _snapshot_row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]:
        ...

    def _engagement_value(self, value: str) -> float:
        ...

    def _is_assertion_expired(self, assertion: Dict[str, Any], *, now: float | None = None) -> bool:
        ...

    def _build_snapshot_evolution_payload(
        self,
        *,
        existing_snapshot: Dict[str, Any] | None,
        core_traits: Dict[str, Any],
        preferences: Dict[str, Any],
        relationship_topology: Dict[str, Any],
        assertions: List[Dict[str, Any]],
        outgoing_relations: List[Dict[str, Any]],
        incoming_relations: List[Dict[str, Any]],
        superseded_outgoing_relations: List[Dict[str, Any]],
        superseded_incoming_relations: List[Dict[str, Any]],
        fallback_updated_at: float,
    ) -> Dict[str, Any]:
        ...

    async def get_tom_snapshot(self, *, entity_id: str, entity_type: str) -> Optional[Dict[str, Any]]:
        ...


class L2StoreSnapshotMixin:
    """Persist ToM snapshots derived from assertions and graph relations."""

    async def _materialize_snapshot(
        self,
        *,
        entity_id: str,
        entity_type: str,
        trait_name: str,
        trait_value: str,
        assertion_ids: List[str],
        last_interaction_at: float,
    ) -> None:
        host = cast(_SnapshotHostProtocol, self)
        now = time.time()
        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM tom_snapshots WHERE entity_id = ? AND entity_type = ?",
                (entity_id, entity_type),
            ) as cursor:
                existing = await cursor.fetchone()

            core_traits = {"stress_level": trait_value} if trait_name == "stress_level" else {}
            current_stress = 1.0 if trait_value == "high" else 0.2

            if existing:
                merged_traits = json.loads(existing["core_traits"] or "{}")
                merged_traits.update(core_traits)
                await db.execute(
                    """
                    UPDATE tom_snapshots
                    SET core_traits = ?, current_stress_level = ?, last_interaction_at = ?,
                        last_updated_at = ?, update_source_assertion_ids = ?,
                        snapshot_version = snapshot_version + 1
                    WHERE snapshot_id = ?
                    """,
                    (
                        json.dumps(merged_traits, ensure_ascii=False),
                        current_stress,
                        float(last_interaction_at),
                        now,
                        json.dumps(assertion_ids, ensure_ascii=False),
                        str(existing["snapshot_id"]),
                    ),
                )
            else:
                await db.execute(
                    """
                    INSERT INTO tom_snapshots(
                        snapshot_id, entity_id, entity_type, core_traits, sensitive_triggers,
                        preferences, public_sentiment_profile, relationship_topology,
                        current_stress_level, current_mood, current_engagement, current_context,
                        interaction_count, last_interaction_at, last_updated_at,
                        update_source_assertion_ids, snapshot_version, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"snapshot_{uuid.uuid4().hex}",
                        entity_id,
                        entity_type,
                        json.dumps(core_traits, ensure_ascii=False),
                        json.dumps([], ensure_ascii=False),
                        json.dumps({}, ensure_ascii=False),
                        json.dumps({}, ensure_ascii=False),
                        json.dumps({}, ensure_ascii=False),
                        current_stress,
                        None,
                        0.5,
                        json.dumps({}, ensure_ascii=False),
                        1,
                        float(last_interaction_at),
                        now,
                        json.dumps(assertion_ids, ensure_ascii=False),
                        1,
                        now,
                    ),
                )
            await db.commit()

    async def _upsert_snapshot(
        self,
        *,
        entity_id: str,
        entity_type: str,
        assertions: List[Dict[str, Any]],
        expired_assertions: List[Dict[str, Any]],
        stable_assertions: List[Dict[str, Any]],
        tentative_assertions: List[Dict[str, Any]] | None = None,
        all_raw_assertions: List[Dict[str, Any]] | None = None,
        outgoing_relations: List[Dict[str, Any]],
        incoming_relations: List[Dict[str, Any]],
        superseded_outgoing_relations: List[Dict[str, Any]],
        superseded_incoming_relations: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        host = cast(_SnapshotHostProtocol, self)
        now = time.time()
        stable_by_trait = {item["trait_name"]: item for item in stable_assertions}
        active_by_trait = {item["trait_name"]: item for item in assertions}

        core_traits: dict[str, Any] = {}
        preferences: dict[str, Any] = {}
        sensitive_triggers: list[str] = []
        public_sentiment_profile: dict[str, Any] = {}

        current_stress_level = 0.0
        stress_assertion = active_by_trait.get("stress_level") or stable_by_trait.get("stress_level")
        if stress_assertion:
            stress_value = str(stress_assertion["trait_value"])
            current_stress_level = 1.0 if stress_value == "high" else 0.2 if stress_value == "low" else 0.5
            if stress_assertion["validation_state"] == "stable":
                core_traits["stress_level"] = stress_value

        current_mood = None
        mood_assertion = active_by_trait.get("mood")
        if mood_assertion:
            current_mood = str(mood_assertion["trait_value"])

        current_engagement = 0.5
        engagement_assertion = active_by_trait.get("engagement")
        if engagement_assertion:
            current_engagement = host._engagement_value(str(engagement_assertion["trait_value"]))

        for trait_name, assertion in stable_by_trait.items():
            if trait_name.startswith("preference."):
                preference_key = trait_name.split(".", 1)[1]
                preferences[preference_key] = assertion["trait_value"]
            elif trait_name.startswith("trigger."):
                sensitive_triggers.append(str(assertion["trait_value"]))
            elif trait_name not in {"stress_level", "mood", "engagement"}:
                core_traits[trait_name] = assertion["trait_value"]

        pref_families = {"taste_profile", "preference_profile"}
        for assertion in assertions:
            family = assertion.get("trait_family", "")
            if family not in pref_families:
                continue
            trait_name = str(assertion.get("trait_name", ""))
            if trait_name.startswith("preference."):
                continue
            confidence = float(assertion.get("confidence_score", 0))
            evidence_count = len(assertion.get("evidence_events", []) or [])
            affinity = round(min(1.0, confidence * (1 + 0.1 * min(evidence_count, 5))), 2)
            preferences[trait_name] = {
                "value": assertion["trait_value"],
                "affinity": affinity,
                "family": family,
            }

        for relation in outgoing_relations:
            if relation["predicate"] == "LIKES":
                confidence = float(relation.get("confidence", 0.5))
                obs_count = int(relation.get("observation_count", 1))
                affinity = round(min(1.0, confidence * (1 + 0.1 * min(obs_count, 5))), 2)
                preferences[relation["object_id"]] = {
                    "value": "like",
                    "affinity": affinity,
                    "family": "graph",
                }
            elif relation["predicate"] == "DISLIKES":
                confidence = float(relation.get("confidence", 0.5))
                obs_count = int(relation.get("observation_count", 1))
                affinity = round(min(1.0, confidence * (1 + 0.1 * min(obs_count, 5))), 2)
                preferences[relation["object_id"]] = {
                    "value": "dislike",
                    "affinity": -affinity,
                    "family": "graph",
                }

        relationship_topology = {
            "outgoing_count": len(outgoing_relations),
            "incoming_count": len(incoming_relations),
            "outgoing": [
                {
                    "predicate": relation["predicate"],
                    "object_id": relation["object_id"],
                    "object_type": relation["object_type"],
                }
                for relation in outgoing_relations[:20]
            ],
            "incoming": [
                {
                    "predicate": relation["predicate"],
                    "subject_id": relation["subject_id"],
                    "subject_type": relation["subject_type"],
                }
                for relation in incoming_relations[:20]
            ],
        }
        current_context = {
            "active_assertion_count": len(assertions),
            "expired_assertion_count": len(expired_assertions),
            "stable_assertion_count": len(stable_assertions),
            "relation_count": len(outgoing_relations) + len(incoming_relations),
        }
        emerging_signals: list[dict[str, Any]] = []
        for item in (tentative_assertions or []):
            emerging_signals.append({
                "trait_family": item.get("trait_family", ""),
                "trait_name": item["trait_name"],
                "trait_value": item["trait_value"],
                "confidence": float(item.get("confidence_score", 0)),
                "evidence_count": len(item.get("evidence_events", []) or []),
                "first_inferred_at": float(item.get("first_inferred_at", 0)),
                "last_validated_at": float(item.get("last_validated_at", 0)),
            })

        update_source_assertion_ids = [item["assertion_id"] for item in assertions]
        last_interaction_at = max([float(item["last_validated_at"]) for item in assertions] + [now])
        interaction_count = max(1, len(assertions) + len(outgoing_relations) + len(incoming_relations))

        async with sqlite_connection_async(host.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM tom_snapshots WHERE entity_id = ? AND entity_type = ?",
                (entity_id, entity_type),
            ) as cursor:
                existing = await cursor.fetchone()
            existing_snapshot = host._snapshot_row_to_dict(existing) if existing else None

            prev_trajectory: list[dict[str, Any]] = (
                list(existing_snapshot.get("mood_trajectory", [])) if existing_snapshot else []
            )
            for item in (all_raw_assertions or assertions):
                family = item.get("trait_family")
                if family not in MOOD_TRAJECTORY_FAMILIES:
                    continue
                if host._is_assertion_expired(item):
                    continue
                value = str(item["trait_value"])
                same_family = [entry for entry in prev_trajectory if entry.get("family") == family]
                if same_family and str(same_family[-1].get("value")) == value:
                    continue
                prev_trajectory.append({
                    "family": family,
                    "value": value,
                    "confidence": float(item.get("confidence_score", 0)),
                    "at": float(item.get("last_validated_at", 0)),
                })
            prev_trajectory.sort(key=lambda entry: entry["at"])
            mood_trajectory = prev_trajectory[-MOOD_TRAJECTORY_LIMIT:]

            evolution_payload = host._build_snapshot_evolution_payload(
                existing_snapshot=existing_snapshot,
                core_traits=core_traits,
                preferences=preferences,
                relationship_topology=relationship_topology,
                assertions=assertions,
                outgoing_relations=outgoing_relations,
                incoming_relations=incoming_relations,
                superseded_outgoing_relations=superseded_outgoing_relations,
                superseded_incoming_relations=superseded_incoming_relations,
                fallback_updated_at=now,
            )

            payload = (
                json.dumps(core_traits, ensure_ascii=False),
                json.dumps(sorted(set(sensitive_triggers)), ensure_ascii=False),
                json.dumps(preferences, ensure_ascii=False),
                json.dumps(public_sentiment_profile, ensure_ascii=False),
                json.dumps(relationship_topology, ensure_ascii=False),
                float(current_stress_level),
                current_mood,
                float(current_engagement),
                json.dumps(current_context, ensure_ascii=False),
                interaction_count,
                last_interaction_at,
                now,
                json.dumps(update_source_assertion_ids, ensure_ascii=False),
                json.dumps(evolution_payload["core_traits_history"], ensure_ascii=False),
                json.dumps(evolution_payload["preferences_history"], ensure_ascii=False),
                json.dumps(evolution_payload["relationship_history"], ensure_ascii=False),
                evolution_payload["last_evolution_at"],
                json.dumps(evolution_payload["active_record_ids"], ensure_ascii=False),
                json.dumps(evolution_payload["superseded_record_ids"], ensure_ascii=False),
                json.dumps(emerging_signals, ensure_ascii=False),
                json.dumps(mood_trajectory, ensure_ascii=False),
            )

            if existing:
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
                        snapshot_version = snapshot_version + 1
                    WHERE snapshot_id = ?
                    """,
                    payload + (str(existing["snapshot_id"]),),
                )
            else:
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
                        snapshot_version, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"snapshot_{uuid.uuid4().hex}",
                        entity_id,
                        entity_type,
                    )
                    + payload
                    + (1, now),
                )
            await db.commit()

        snapshot = await host.get_tom_snapshot(entity_id=entity_id, entity_type=entity_type)
        assert snapshot is not None
        return snapshot
