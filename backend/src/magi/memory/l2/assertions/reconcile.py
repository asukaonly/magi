"""Snapshot evolution and reconciliation helpers for the L2 cognition store."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from ..storage.utils import (
    MOMENTARY_TRAITS as _MOMENTARY_TRAITS,
    SNAPSHOT_HISTORY_LIMIT as _SNAPSHOT_HISTORY_LIMIT,
)


class L2StoreReconcileMixin:
    """Pure helper methods for ToM reconciliation and snapshot evolution."""

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
        previous_core_traits = dict(existing_snapshot.get("core_traits", {})) if existing_snapshot else {}
        previous_preferences = dict(existing_snapshot.get("preferences", {})) if existing_snapshot else {}
        previous_relationship = (
            dict(existing_snapshot.get("relationship_topology", {})) if existing_snapshot else {}
        )

        active_assertion_ids = [str(item["assertion_id"]) for item in assertions]
        active_relation_ids = [
            str(item["triple_id"]) for item in [*outgoing_relations, *incoming_relations]
        ]
        active_record_ids = self._dedupe_preserve_order([*active_assertion_ids, *active_relation_ids])

        previous_assertion_ids = (
            [str(item) for item in existing_snapshot.get("update_source_assertion_ids", [])]
            if existing_snapshot
            else []
        )

        preference_support_ids = {
            str(item["object_id"]): [str(item["triple_id"])]
            for item in outgoing_relations
            if item["predicate"] in {"LIKES", "DISLIKES"}
        }
        preference_superseded_ids = self._group_relation_ids_by_object(superseded_outgoing_relations)
        core_support_ids = {
            str(item["trait_name"]): [str(item["assertion_id"])]
            for item in assertions
        }

        next_preference_entries = self._build_mapping_transition_entries(
            previous_values=previous_preferences,
            current_values=preferences,
            support_ids_by_field=preference_support_ids,
            superseded_ids_by_field=preference_superseded_ids,
            evolved_at_by_field=self._relation_evolved_at_by_object(
                outgoing_relations=outgoing_relations,
                superseded_outgoing_relations=superseded_outgoing_relations,
                fallback_updated_at=fallback_updated_at,
            ),
        )
        next_core_entries = self._build_mapping_transition_entries(
            previous_values=previous_core_traits,
            current_values=core_traits,
            support_ids_by_field=core_support_ids,
            superseded_ids_by_field={
                field_name: previous_assertion_ids
                for field_name in set(previous_core_traits).intersection(core_traits)
            },
            evolved_at_by_field={
                str(item["trait_name"]): float(item["last_validated_at"])
                for item in assertions
            },
        )

        relationship_support_ids = [str(item["triple_id"]) for item in [*outgoing_relations, *incoming_relations]]
        relationship_superseded_ids = [
            str(item["triple_id"]) for item in [*superseded_outgoing_relations, *superseded_incoming_relations]
        ]
        next_relationship_entries = self._build_relationship_transition_entries(
            previous_relationship=previous_relationship,
            current_relationship=relationship_topology,
            support_ids=relationship_support_ids,
            superseded_ids=relationship_superseded_ids,
            fallback_updated_at=fallback_updated_at,
        )

        core_traits_history = self._merge_snapshot_history(
            existing_history=existing_snapshot.get("core_traits_history", []) if existing_snapshot else [],
            new_entries=next_core_entries,
        )
        preferences_history = self._merge_snapshot_history(
            existing_history=existing_snapshot.get("preferences_history", []) if existing_snapshot else [],
            new_entries=next_preference_entries,
        )
        relationship_history = self._merge_snapshot_history(
            existing_history=existing_snapshot.get("relationship_history", []) if existing_snapshot else [],
            new_entries=next_relationship_entries,
        )

        history_entries = [*core_traits_history, *preferences_history, *relationship_history]
        evolution_timestamps = [
            float(entry["evolved_at"])
            for entry in history_entries
            if entry.get("evolved_at") is not None
        ]
        last_evolution_at = max(evolution_timestamps) if evolution_timestamps else (
            existing_snapshot.get("last_evolution_at") if existing_snapshot else None
        )
        superseded_record_ids = self._dedupe_preserve_order(
            [
                str(record_id)
                for entry in history_entries
                for record_id in entry.get("superseded_record_ids", [])
                if str(record_id).strip()
            ]
        )

        return {
            "core_traits_history": core_traits_history,
            "preferences_history": preferences_history,
            "relationship_history": relationship_history,
            "last_evolution_at": last_evolution_at,
            "active_record_ids": active_record_ids,
            "superseded_record_ids": superseded_record_ids,
        }

    def _build_mapping_transition_entries(
        self,
        *,
        previous_values: Dict[str, Any],
        current_values: Dict[str, Any],
        support_ids_by_field: Dict[str, List[str]],
        superseded_ids_by_field: Dict[str, List[str]],
        evolved_at_by_field: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for field_name in sorted(set(previous_values).intersection(current_values)):
            previous_value = previous_values.get(field_name)
            current_value = current_values.get(field_name)
            if previous_value == current_value:
                continue
            entries.append(
                {
                    "field": field_name,
                    "from": previous_value,
                    "to": current_value,
                    "evolved_at": evolved_at_by_field.get(field_name),
                    "supporting_record_ids": self._dedupe_preserve_order(support_ids_by_field.get(field_name, [])),
                    "superseded_record_ids": self._dedupe_preserve_order(
                        superseded_ids_by_field.get(field_name, [])
                    ),
                }
            )
        return entries

    def _build_relationship_transition_entries(
        self,
        *,
        previous_relationship: Dict[str, Any],
        current_relationship: Dict[str, Any],
        support_ids: List[str],
        superseded_ids: List[str],
        fallback_updated_at: float,
    ) -> List[Dict[str, Any]]:
        if not previous_relationship or previous_relationship == current_relationship:
            return []
        return [
            {
                "field": "relationship_topology",
                "from": previous_relationship,
                "to": current_relationship,
                "evolved_at": fallback_updated_at,
                "supporting_record_ids": self._dedupe_preserve_order(support_ids),
                "superseded_record_ids": self._dedupe_preserve_order(superseded_ids),
            }
        ]

    def _merge_snapshot_history(
        self,
        *,
        existing_history: List[Dict[str, Any]],
        new_entries: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        merged = [dict(entry) for entry in new_entries]
        for entry in existing_history:
            if any(self._same_history_entry(entry, candidate) for candidate in merged):
                continue
            merged.append(dict(entry))
        return merged[:_SNAPSHOT_HISTORY_LIMIT]

    def _same_history_entry(self, left: Dict[str, Any], right: Dict[str, Any]) -> bool:
        return (
            left.get("field") == right.get("field")
            and left.get("from") == right.get("from")
            and left.get("to") == right.get("to")
        )

    def _group_relation_ids_by_object(self, relations: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        grouped: dict[str, list[str]] = {}
        for relation in relations:
            if relation["predicate"] not in {"LIKES", "DISLIKES"}:
                continue
            object_id = str(relation["object_id"])
            grouped.setdefault(object_id, []).append(str(relation["triple_id"]))
        return {key: self._dedupe_preserve_order(value) for key, value in grouped.items()}

    def _relation_evolved_at_by_object(
        self,
        *,
        outgoing_relations: List[Dict[str, Any]],
        superseded_outgoing_relations: List[Dict[str, Any]],
        fallback_updated_at: float,
    ) -> Dict[str, float]:
        timestamps: dict[str, float] = {}
        for relation in [*outgoing_relations, *superseded_outgoing_relations]:
            if relation["predicate"] not in {"LIKES", "DISLIKES"}:
                continue
            object_id = str(relation["object_id"])
            candidate_timestamp = max(
                float(relation.get("last_observed_at") or 0.0),
                float(relation.get("deprecated_at") or 0.0),
                float(relation.get("updated_at") or 0.0),
                fallback_updated_at,
            )
            timestamps[object_id] = max(timestamps.get(object_id, 0.0), candidate_timestamp)
        return timestamps

    def _dedupe_preserve_order(self, values: List[str]) -> List[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = str(value).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
        return ordered

    def _derive_trait_family(self, trait_name: str) -> str:
        normalized = trait_name.strip().lower()
        if normalized == "stress_level":
            return "stress"
        if normalized in {"mood", "annoyance", "irritation", "frustration"}:
            return "mood"
        if normalized == "engagement":
            return "engagement"
        if normalized.startswith("trigger."):
            return "trigger"
        if normalized in {"taste_profile", "taste_preference"}:
            return "taste_profile"
        if normalized.startswith("preference."):
            return "preference_profile"
        return "preference_profile"

    def _optional_text(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _coerce_expires_at(
        self,
        value: Any,
        *,
        trait_family: str,
        trait_name: str,
        target_entity_id: str,
        anchor_at: float,
    ) -> float | None:
        if value is not None:
            return float(value)
        normalized_trait_name = trait_name.strip().lower()
        if target_entity_id and normalized_trait_name in _MOMENTARY_TRAITS:
            return anchor_at + 2 * 60 * 60
        if trait_family == "mood":
            return anchor_at + 12 * 60 * 60
        if trait_family == "stress":
            return anchor_at + 24 * 60 * 60
        if trait_family == "engagement":
            return anchor_at + 12 * 60 * 60
        if trait_family in {"group_atmosphere", "public_sentiment", "relationship_shift"}:
            return anchor_at + 6 * 60 * 60
        return None

    def _is_assertion_expired(self, assertion: Dict[str, Any], *, now: float | None = None) -> bool:
        expires_at = assertion.get("expires_at")
        if expires_at is None:
            return False
        current_time = float(now if now is not None else time.time())
        return float(expires_at) <= current_time

    _TEMPORARY_STATE_TRAITS = frozenset({"stress_level", "mood", "engagement"})

    def _derive_reconcile_state(
        self,
        *,
        current_state: str,
        current_confidence: float,
        evidence_count: int,
        time_span_hours: float,
        trait_name: str,
        user_feedback: Optional[str] = None,
    ) -> tuple[str, float, str]:
        is_temporary = trait_name in self._TEMPORARY_STATE_TRAITS

        if user_feedback == "rejected":
            return ("user_rejected", 0.10, "volatile_pattern")

        if user_feedback == "confirmed":
            stability_kind = "temporary_state" if is_temporary else "stable_trait"
            return ("stable", max(current_confidence, 0.85), stability_kind)

        if current_state == "contradicted":
            return ("contradicted", min(current_confidence, 0.35), "volatile_pattern")

        if is_temporary:
            if evidence_count >= 3 and time_span_hours >= 24.0:
                return ("stable", max(current_confidence, 0.82), "temporary_state")
            if evidence_count >= 1:
                return ("corroborated", max(current_confidence, 0.50), "temporary_state")

        if evidence_count >= 3 and time_span_hours >= 24.0:
            stability_kind = "stable_trait"
            return ("stable", max(current_confidence, 0.82), stability_kind)

        if evidence_count >= 2:
            return ("corroborated", max(current_confidence, 0.58), "volatile_pattern")

        return ("tentative", min(current_confidence, 0.3), "volatile_pattern")

    def _recommend_snapshot_field(self, *, trait_name: str, status: str) -> str:
        if status not in {"stable", "corroborated"}:
            return "none"
        if trait_name.startswith("preference."):
            return "preferences"
        if trait_name.startswith("trigger."):
            return "sensitive_triggers"
        if trait_name == "stress_level":
            return "core_traits" if status == "stable" else "current_stress_level"
        if trait_name == "mood":
            return "current_mood"
        if trait_name == "engagement":
            return "current_engagement"
        return "core_traits"

    def _engagement_value(self, value: str) -> float:
        normalized = value.strip().lower()
        if normalized in {"high", "engaged", "focused"}:
            return 0.9
        if normalized in {"low", "disengaged", "distant"}:
            return 0.2
        try:
            return float(normalized)
        except ValueError:
            return 0.5

    def _contradicted_confidence(self, *, current_confidence: float, hint_confidence: float, action: str) -> float:
        base = current_confidence * 0.35
        if action == "mark_conflicted":
            return round(max(0.1, min(base, 0.35)), 4)
        if action == "revalidate_only":
            return round(max(0.15, current_confidence * 0.75), 4)
        confidence_weight = 1.0 - min(max(hint_confidence, 0.0), 1.0) * 0.45
        return round(max(0.1, min(current_confidence * confidence_weight, 0.35)), 4)
