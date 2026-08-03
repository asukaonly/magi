"""In-memory snapshot assembly helpers for L2 assertions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, cast


from ..assertion_family_policy import get_assertion_family_policy
from ..storage.utils import MOOD_TRAJECTORY_FAMILIES, mood_trajectory_limit
from .snapshot_protocols import _SnapshotHostProtocol
from .source_tier import source_tier


@dataclass(slots=True)
class _SnapshotProfileFields:
    core_traits: dict[str, Any] = field(default_factory=dict)
    preferences: dict[str, Any] = field(default_factory=dict)
    sensitive_triggers: list[str] = field(default_factory=list)
    public_sentiment_profile: dict[str, Any] = field(default_factory=dict)
    current_stress_level: float = 0.0
    current_mood: str | None = None
    current_engagement: float = 0.5


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
        stable_by_trait = {item["trait_name"]: item for item in stable_assertions}
        active_by_trait = {item["trait_name"]: item for item in assertions}
        profile = self._build_snapshot_profile_fields(
            active_by_trait=active_by_trait,
            stable_by_trait=stable_by_trait,
        )

        self._add_assertion_preferences(
            preferences=profile.preferences,
            assertions=assertions,
        )
        self._add_relation_preferences(
            preferences=profile.preferences,
            outgoing_relations=outgoing_relations,
        )

        relationship_topology = self._build_relationship_topology(
            outgoing_relations=outgoing_relations,
            incoming_relations=incoming_relations,
        )
        return self._snapshot_state_payload(
            profile=profile,
            relationship_topology=relationship_topology,
            current_context=self._build_snapshot_current_context(
                assertions=assertions,
                expired_assertions=expired_assertions,
                stable_assertions=stable_assertions,
                outgoing_relations=outgoing_relations,
                incoming_relations=incoming_relations,
            ),
            emerging_signals=self._build_emerging_signals(tentative_assertions or []),
            assertions=assertions,
            outgoing_relations=outgoing_relations,
            incoming_relations=incoming_relations,
            now=now,
        )

    def _build_snapshot_profile_fields(
        self,
        *,
        active_by_trait: dict[str, dict[str, Any]],
        stable_by_trait: dict[str, dict[str, Any]],
    ) -> _SnapshotProfileFields:
        host = cast(_SnapshotHostProtocol, self)
        profile = _SnapshotProfileFields()

        stress_assertion = active_by_trait.get("stress_level") or stable_by_trait.get(
            "stress_level"
        )
        if stress_assertion:
            stress_value = str(stress_assertion["trait_value"])
            profile.current_stress_level = self._stress_level_value(stress_value)
            if stress_assertion["validation_state"] == "stable":
                profile.core_traits["stress_level"] = stress_value

        mood_assertion = active_by_trait.get("mood")
        if mood_assertion:
            profile.current_mood = str(mood_assertion["trait_value"])

        engagement_assertion = active_by_trait.get("engagement")
        if engagement_assertion:
            profile.current_engagement = host._engagement_value(
                str(engagement_assertion["trait_value"])
            )

        for trait_name, assertion in stable_by_trait.items():
            if str(assertion.get("trait_family") or "").strip().casefold() == "goal_profile":
                continue
            if trait_name.startswith("preference."):
                preference_key = trait_name.split(".", 1)[1]
                profile.preferences[preference_key] = assertion["trait_value"]
            elif trait_name.startswith("trigger."):
                profile.sensitive_triggers.append(str(assertion["trait_value"]))
            elif trait_name not in {"stress_level", "mood", "engagement"}:
                profile.core_traits[trait_name] = assertion["trait_value"]
        return profile

    @staticmethod
    def _stress_level_value(stress_value: str) -> float:
        if stress_value == "high":
            return 1.0
        if stress_value == "low":
            return 0.2
        return 0.5

    @staticmethod
    def _build_snapshot_current_context(
        *,
        assertions: List[Dict[str, Any]],
        expired_assertions: List[Dict[str, Any]],
        stable_assertions: List[Dict[str, Any]],
        outgoing_relations: List[Dict[str, Any]],
        incoming_relations: List[Dict[str, Any]],
    ) -> dict[str, int]:
        return {
            "active_assertion_count": len(assertions),
            "expired_assertion_count": len(expired_assertions),
            "stable_assertion_count": len(stable_assertions),
            "relation_count": len(outgoing_relations) + len(incoming_relations),
        }

    def _snapshot_state_payload(
        self,
        *,
        profile: _SnapshotProfileFields,
        relationship_topology: dict[str, Any],
        current_context: dict[str, int],
        emerging_signals: list[dict[str, Any]],
        assertions: List[Dict[str, Any]],
        outgoing_relations: List[Dict[str, Any]],
        incoming_relations: List[Dict[str, Any]],
        now: float,
    ) -> dict[str, Any]:
        return {
            "core_traits": profile.core_traits,
            "preferences": profile.preferences,
            "sensitive_triggers": profile.sensitive_triggers,
            "public_sentiment_profile": profile.public_sentiment_profile,
            "current_stress_level": profile.current_stress_level,
            "current_mood": profile.current_mood,
            "current_engagement": profile.current_engagement,
            "relationship_topology": relationship_topology,
            "current_context": current_context,
            "emerging_signals": emerging_signals,
            "update_source_assertion_ids": [item["assertion_id"] for item in assertions],
            "last_interaction_at": max(
                [float(item["last_validated_at"]) for item in assertions] + [now]
            ),
            "interaction_count": max(
                1, len(assertions) + len(outgoing_relations) + len(incoming_relations)
            ),
        }

    def _add_assertion_preferences(
        self,
        *,
        preferences: dict[str, Any],
        assertions: List[Dict[str, Any]],
    ) -> None:
        for assertion in assertions:
            family = str(assertion.get("trait_family") or "").strip().casefold()
            policy = get_assertion_family_policy(family)
            if policy is None or policy.snapshot_bucket != "preferences":
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
            emerging_signals.append(
                {
                    "trait_family": item.get("trait_family", ""),
                    "trait_name": item["trait_name"],
                    "trait_value": item["trait_value"],
                    "confidence": float(item.get("confidence_score", 0)),
                    "evidence_count": len(item.get("evidence_events", []) or []),
                    "first_inferred_at": float(item.get("first_inferred_at", 0)),
                    "last_validated_at": float(item.get("last_validated_at", 0)),
                }
            )
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
        for item in all_raw_assertions or assertions:
            family = item.get("trait_family")
            if family not in MOOD_TRAJECTORY_FAMILIES:
                continue
            if host._is_assertion_expired(item):
                continue
            value = str(item["trait_value"])
            same_family = [entry for entry in prev_trajectory if entry.get("family") == family]
            if same_family and str(same_family[-1].get("value")) == value:
                continue
            prev_trajectory.append(
                {
                    "family": family,
                    "value": value,
                    "confidence": float(item.get("confidence_score", 0)),
                    "at": float(item.get("last_validated_at", 0)),
                }
            )
        prev_trajectory.sort(key=lambda entry: entry["at"])
        return prev_trajectory[-mood_trajectory_limit() :]


__all__ = ["L2SnapshotAssemblyMixin"]
