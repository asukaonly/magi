"""Snapshot evolution payload helpers for L2 assertions."""

from __future__ import annotations

from typing import Any, Dict, List

from ..storage.utils import SNAPSHOT_HISTORY_LIMIT as _SNAPSHOT_HISTORY_LIMIT


class L2SnapshotEvolutionMixin:
    """Build and merge snapshot evolution history entries."""

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


__all__ = ["L2SnapshotEvolutionMixin", "_SNAPSHOT_HISTORY_LIMIT"]
