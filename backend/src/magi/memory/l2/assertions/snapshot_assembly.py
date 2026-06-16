"""In-memory snapshot assembly helpers for L2 assertions."""

from __future__ import annotations

from typing import Any, Dict, List, cast


from ..storage.utils import MOOD_TRAJECTORY_FAMILIES, MOOD_TRAJECTORY_LIMIT
from .snapshot_protocols import _SnapshotHostProtocol
from .source_tier import source_tier


class L2SnapshotAssemblyMixin:
    """Build snapshot JSON payload fields before persistence."""

    def _build_snapshot_state(
        self,
        *,
        assertions: List[Dict[str, Any]],
        expired_assertions: List[Dict[str, Any]],
        stable_assertions: List[Dict[str, Any]],
        tentative_assertions: List[Dict[str, Any]] | None,
        outgoing_relations: List[Dict[str, Any]],
        incoming_relations: List[Dict[str, Any]],
        now: float,
    ) -> dict[str, Any]:
        host = cast(_SnapshotHostProtocol, self)
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

        self._add_assertion_preferences(preferences=preferences, assertions=assertions)
        self._add_relation_preferences(preferences=preferences, outgoing_relations=outgoing_relations)

        relationship_topology = self._build_relationship_topology(
            outgoing_relations=outgoing_relations,
            incoming_relations=incoming_relations,
        )
        current_context = {
            "active_assertion_count": len(assertions),
            "expired_assertion_count": len(expired_assertions),
            "stable_assertion_count": len(stable_assertions),
            "relation_count": len(outgoing_relations) + len(incoming_relations),
        }
        emerging_signals = self._build_emerging_signals(tentative_assertions or [])

        return {
            "core_traits": core_traits,
            "preferences": preferences,
            "sensitive_triggers": sensitive_triggers,
            "public_sentiment_profile": public_sentiment_profile,
            "current_stress_level": current_stress_level,
            "current_mood": current_mood,
            "current_engagement": current_engagement,
            "relationship_topology": relationship_topology,
            "current_context": current_context,
            "emerging_signals": emerging_signals,
            "update_source_assertion_ids": [item["assertion_id"] for item in assertions],
            "last_interaction_at": max([float(item["last_validated_at"]) for item in assertions] + [now]),
            "interaction_count": max(1, len(assertions) + len(outgoing_relations) + len(incoming_relations)),
        }

    def _add_assertion_preferences(
        self,
        *,
        preferences: dict[str, Any],
        assertions: List[Dict[str, Any]],
    ) -> None:
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
                "source_tier": source_tier(
                    source_domain=assertion.get("source_domain"),
                    user_feedback=assertion.get("user_feedback"),
                ),
            }

    def _add_relation_preferences(
        self,
        *,
        preferences: dict[str, Any],
        outgoing_relations: List[Dict[str, Any]],
    ) -> None:
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

    def _build_relationship_topology(
        self,
        *,
        outgoing_relations: List[Dict[str, Any]],
        incoming_relations: List[Dict[str, Any]],
    ) -> dict[str, Any]:
        return {
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

    def _build_emerging_signals(
        self,
        tentative_assertions: List[Dict[str, Any]],
    ) -> list[dict[str, Any]]:
        emerging_signals: list[dict[str, Any]] = []
        for item in tentative_assertions:
            emerging_signals.append({
                "trait_family": item.get("trait_family", ""),
                "trait_name": item["trait_name"],
                "trait_value": item["trait_value"],
                "confidence": float(item.get("confidence_score", 0)),
                "evidence_count": len(item.get("evidence_events", []) or []),
                "first_inferred_at": float(item.get("first_inferred_at", 0)),
                "last_validated_at": float(item.get("last_validated_at", 0)),
            })
        return emerging_signals

    def _build_mood_trajectory(
        self,
        *,
        existing_snapshot: Dict[str, Any] | None,
        assertions: List[Dict[str, Any]],
        all_raw_assertions: List[Dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        host = cast(_SnapshotHostProtocol, self)
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
        return prev_trajectory[-MOOD_TRAJECTORY_LIMIT:]


__all__ = ["L2SnapshotAssemblyMixin"]
