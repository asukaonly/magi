"""Snapshot evolution payload helpers for L2 assertions."""

from __future__ import annotations

from typing import Any, Dict, List

from ..storage.utils import (
    SNAPSHOT_HISTORY_LIMIT as _SNAPSHOT_HISTORY_LIMIT,
    snapshot_history_limit,
)


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
        previous_core_traits = self._snapshot_mapping(existing_snapshot, "core_traits")
        previous_preferences = self._snapshot_mapping(existing_snapshot, "preferences")
        previous_relationship = self._snapshot_mapping(existing_snapshot, "relationship_topology")

        next_core_entries = self._build_core_trait_transition_entries(
            previous_core_traits=previous_core_traits,
            core_traits=core_traits,
            assertions=assertions,
            previous_assertion_ids=self._previous_snapshot_assertion_ids(existing_snapshot),
        )
        next_preference_entries = self._build_preference_transition_entries(
            previous_preferences=previous_preferences,
            preferences=preferences,
            outgoing_relations=outgoing_relations,
            superseded_outgoing_relations=superseded_outgoing_relations,
            fallback_updated_at=fallback_updated_at,
        )
        next_relationship_entries = self._build_relationship_snapshot_entries(
            previous_relationship=previous_relationship,
            current_relationship=relationship_topology,
            outgoing_relations=outgoing_relations,
            incoming_relations=incoming_relations,
            superseded_outgoing_relations=superseded_outgoing_relations,
            superseded_incoming_relations=superseded_incoming_relations,
            fallback_updated_at=fallback_updated_at,
        )

        histories = self._merge_snapshot_evolution_histories(
            existing_snapshot=existing_snapshot,
            next_core_entries=next_core_entries,
            next_preference_entries=next_preference_entries,
            next_relationship_entries=next_relationship_entries,
        )
        history_entries = self._snapshot_history_entries(histories)

        return {
            **histories,
            "last_evolution_at": self._last_snapshot_evolution_at(
                history_entries=history_entries,
                existing_snapshot=existing_snapshot,
            ),
            "active_record_ids": self._active_snapshot_record_ids(
                assertions=assertions,
                outgoing_relations=outgoing_relations,
                incoming_relations=incoming_relations,
            ),
            "superseded_record_ids": self._superseded_snapshot_record_ids(history_entries),
        }

    @staticmethod
    def _snapshot_mapping(
        existing_snapshot: Dict[str, Any] | None,
        key: str,
    ) -> Dict[str, Any]:
        return dict(existing_snapshot.get(key, {})) if existing_snapshot else {}

    @staticmethod
    def _previous_snapshot_assertion_ids(existing_snapshot: Dict[str, Any] | None) -> List[str]:
        if not existing_snapshot:
            return []
        return [str(item) for item in existing_snapshot.get("update_source_assertion_ids", [])]

    def _active_snapshot_record_ids(
        self,
        *,
        assertions: List[Dict[str, Any]],
        outgoing_relations: List[Dict[str, Any]],
        incoming_relations: List[Dict[str, Any]],
    ) -> List[str]:
        active_assertion_ids = [str(item["assertion_id"]) for item in assertions]
        active_relation_ids = [
            str(item["triple_id"]) for item in [*outgoing_relations, *incoming_relations]
        ]
        return self._dedupe_preserve_order([*active_assertion_ids, *active_relation_ids])

    def _build_core_trait_transition_entries(
        self,
        *,
        previous_core_traits: Dict[str, Any],
        core_traits: Dict[str, Any],
        assertions: List[Dict[str, Any]],
        previous_assertion_ids: List[str],
    ) -> List[Dict[str, Any]]:
        return self._build_mapping_transition_entries(
            previous_values=previous_core_traits,
            current_values=core_traits,
            support_ids_by_field={
                str(item["trait_name"]): [str(item["assertion_id"])] for item in assertions
            },
            superseded_ids_by_field={
                field_name: previous_assertion_ids
                for field_name in set(previous_core_traits).intersection(core_traits)
            },
            evolved_at_by_field={
                str(item["trait_name"]): float(item["last_validated_at"]) for item in assertions
            },
        )

    def _build_preference_transition_entries(
        self,
        *,
        previous_preferences: Dict[str, Any],
        preferences: Dict[str, Any],
        outgoing_relations: List[Dict[str, Any]],
        superseded_outgoing_relations: List[Dict[str, Any]],
        fallback_updated_at: float,
    ) -> List[Dict[str, Any]]:
        return self._build_mapping_transition_entries(
            previous_values=previous_preferences,
            current_values=preferences,
            support_ids_by_field={
                str(item["object_id"]): [str(item["triple_id"])]
                for item in outgoing_relations
                if item["predicate"] in {"LIKES", "DISLIKES"}
            },
            superseded_ids_by_field=self._group_relation_ids_by_object(
                superseded_outgoing_relations
            ),
            evolved_at_by_field=self._relation_evolved_at_by_object(
                outgoing_relations=outgoing_relations,
                superseded_outgoing_relations=superseded_outgoing_relations,
                fallback_updated_at=fallback_updated_at,
            ),
        )

    def _build_relationship_snapshot_entries(
        self,
        *,
        previous_relationship: Dict[str, Any],
        current_relationship: Dict[str, Any],
        outgoing_relations: List[Dict[str, Any]],
        incoming_relations: List[Dict[str, Any]],
        superseded_outgoing_relations: List[Dict[str, Any]],
        superseded_incoming_relations: List[Dict[str, Any]],
        fallback_updated_at: float,
    ) -> List[Dict[str, Any]]:
        return self._build_relationship_transition_entries(
            previous_relationship=previous_relationship,
            current_relationship=current_relationship,
            support_ids=[
                str(item["triple_id"]) for item in [*outgoing_relations, *incoming_relations]
            ],
            superseded_ids=[
                str(item["triple_id"])
                for item in [*superseded_outgoing_relations, *superseded_incoming_relations]
            ],
            fallback_updated_at=fallback_updated_at,
        )

    def _merge_snapshot_evolution_histories(
        self,
        *,
        existing_snapshot: Dict[str, Any] | None,
        next_core_entries: List[Dict[str, Any]],
        next_preference_entries: List[Dict[str, Any]],
        next_relationship_entries: List[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        return {
            "core_traits_history": self._merge_snapshot_history(
                existing_history=self._snapshot_history(existing_snapshot, "core_traits_history"),
                new_entries=next_core_entries,
            ),
            "preferences_history": self._merge_snapshot_history(
                existing_history=self._snapshot_history(existing_snapshot, "preferences_history"),
                new_entries=next_preference_entries,
            ),
            "relationship_history": self._merge_snapshot_history(
                existing_history=self._snapshot_history(existing_snapshot, "relationship_history"),
                new_entries=next_relationship_entries,
            ),
        }

    @staticmethod
    def _snapshot_history(
        existing_snapshot: Dict[str, Any] | None,
        key: str,
    ) -> List[Dict[str, Any]]:
        return existing_snapshot.get(key, []) if existing_snapshot else []

    @staticmethod
    def _snapshot_history_entries(
        histories: Dict[str, List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        return [
            *histories["core_traits_history"],
            *histories["preferences_history"],
            *histories["relationship_history"],
        ]

    @staticmethod
    def _last_snapshot_evolution_at(
        *,
        history_entries: List[Dict[str, Any]],
        existing_snapshot: Dict[str, Any] | None,
    ) -> Any:
        evolution_timestamps = [
            float(entry["evolved_at"])
            for entry in history_entries
            if entry.get("evolved_at") is not None
        ]
        if evolution_timestamps:
            return max(evolution_timestamps)
        return existing_snapshot.get("last_evolution_at") if existing_snapshot else None

    def _superseded_snapshot_record_ids(
        self,
        history_entries: List[Dict[str, Any]],
    ) -> List[str]:
        return self._dedupe_preserve_order(
            [
                str(record_id)
                for entry in history_entries
                for record_id in entry.get("superseded_record_ids", [])
                if str(record_id).strip()
            ]
        )

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
                    "supporting_record_ids": self._dedupe_preserve_order(
                        support_ids_by_field.get(field_name, [])
                    ),
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
        return merged[: snapshot_history_limit()]

    def _same_history_entry(self, left: Dict[str, Any], right: Dict[str, Any]) -> bool:
        return (
            left.get("field") == right.get("field")
            and left.get("from") == right.get("from")
            and left.get("to") == right.get("to")
        )

    def _group_relation_ids_by_object(
        self, relations: List[Dict[str, Any]]
    ) -> Dict[str, List[str]]:
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
