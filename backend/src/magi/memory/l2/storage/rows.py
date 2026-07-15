"""Row mapping helpers for the L2 cognition store."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import aiosqlite

from ...event_contracts import MemoryEvent
from ..assertion_family_policy import decorate_assertion_family_metadata


class L2StoreRowMappingMixin:
    """Convert SQLite rows into public L2 store dictionaries."""

    def _entity_identity(self, event: MemoryEvent) -> tuple[Optional[str], Optional[str]]:
        if event.user_id:
            return (f"user:{event.user_id}", "user")
        return (None, None)

    def _assertion_row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]:
        columns = set(row.keys())
        return decorate_assertion_family_metadata({
            "assertion_id": str(row["assertion_id"]),
            "entity_id": str(row["entity_id"]),
            "entity_type": str(row["entity_type"]),
            "trait_family": str(row["trait_family"]),
            "trait_name": str(row["trait_name"]),
            "trait_value": str(row["trait_value"]),
            "confidence_score": float(row["confidence_score"]),
            "evidence_events": json.loads(row["evidence_events"] or "[]"),
            "volatility_index": float(row["volatility_index"]),
            "source_domain": str(row["source_domain"]),
            "inference_depth": str(row["inference_depth"]),
            "validation_state": str(row["validation_state"]),
            "first_inferred_at": float(row["first_inferred_at"]),
            "last_validated_at": float(row["last_validated_at"]),
            "target_entity_id": str(row["target_entity_id"] or ""),
            "target_entity_type": str(row["target_entity_type"] or ""),
            "target_scope": str(row["target_scope"] or "global"),
            "temporal_scope": str(row["temporal_scope"] or "session"),
            "decay_policy": row["decay_policy"],
            "decay_anchor_at": float(row["decay_anchor_at"]) if row["decay_anchor_at"] else None,
            "context_ref_id": str(row["context_ref_id"] or ""),
            "expires_at": float(row["expires_at"]) if row["expires_at"] else None,
            "memory_subdomain": (
                str(row["memory_subdomain"] or "") if "memory_subdomain" in columns else ""
            ),
            "natural_summary": (
                str(row["natural_summary"] or "") if "natural_summary" in columns else ""
            ),
            "user_feedback": str(row["user_feedback"]) if "user_feedback" in columns and row["user_feedback"] else None,
            "user_feedback_at": float(row["user_feedback_at"]) if "user_feedback_at" in columns and row["user_feedback_at"] else None,
            "status": str(row["status"]) if "status" in columns and row["status"] else "active",
            "superseded_by": str(row["superseded_by"]) if "superseded_by" in columns and row["superseded_by"] else None,
            "superseded_at": float(row["superseded_at"]) if "superseded_at" in columns and row["superseded_at"] else None,
            "slot_key": str(row["slot_key"] or "") if "slot_key" in columns else "",
            "claim_fingerprint": (
                str(row["claim_fingerprint"] or "")
                if "claim_fingerprint" in columns
                else ""
            ),
            "authority_ref": (
                str(row["authority_ref"])
                if "authority_ref" in columns and row["authority_ref"]
                else None
            ),
            "version_root_id": (
                str(row["version_root_id"])
                if "version_root_id" in columns and row["version_root_id"]
                else None
            ),
            "previous_version_id": (
                str(row["previous_version_id"])
                if "previous_version_id" in columns and row["previous_version_id"]
                else None
            ),
            "valid_from": (
                float(row["valid_from"])
                if "valid_from" in columns and row["valid_from"] is not None
                else None
            ),
            "valid_to": (
                float(row["valid_to"])
                if "valid_to" in columns and row["valid_to"] is not None
                else None
            ),
            "scope_key": (
                str(row["scope_key"] or "global")
                if "scope_key" in columns
                else "global"
            ),
            "scope": (
                json.loads(row["scope_json"] or "{}")
                if "scope_json" in columns
                else {}
            ),
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        })

    def _snapshot_row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]:
        columns = set(row.keys())
        return {
            "snapshot_id": str(row["snapshot_id"]),
            "entity_id": str(row["entity_id"]),
            "entity_type": str(row["entity_type"]),
            "core_traits": json.loads(row["core_traits"] or "{}"),
            "sensitive_triggers": json.loads(row["sensitive_triggers"] or "[]"),
            "preferences": json.loads(row["preferences"] or "{}"),
            "public_sentiment_profile": json.loads(row["public_sentiment_profile"] or "{}"),
            "relationship_topology": json.loads(row["relationship_topology"] or "{}"),
            "current_stress_level": float(row["current_stress_level"] or 0.0),
            "current_mood": row["current_mood"],
            "current_engagement": float(row["current_engagement"] or 0.5),
            "current_context": json.loads(row["current_context"] or "{}"),
            "interaction_count": int(row["interaction_count"] or 0),
            "last_interaction_at": float(row["last_interaction_at"]) if row["last_interaction_at"] else None,
            "last_updated_at": float(row["last_updated_at"]),
            "update_source_assertion_ids": json.loads(row["update_source_assertion_ids"] or "[]"),
            "core_traits_history": json.loads(row["core_traits_history"] or "[]") if "core_traits_history" in columns else [],
            "preferences_history": json.loads(row["preferences_history"] or "[]") if "preferences_history" in columns else [],
            "relationship_history": json.loads(row["relationship_history"] or "[]") if "relationship_history" in columns else [],
            "last_evolution_at": (
                float(row["last_evolution_at"])
                if "last_evolution_at" in columns and row["last_evolution_at"] is not None
                else None
            ),
            "active_record_ids": json.loads(row["active_record_ids"] or "[]") if "active_record_ids" in columns else [],
            "superseded_record_ids": (
                json.loads(row["superseded_record_ids"] or "[]") if "superseded_record_ids" in columns else []
            ),
            "emerging_signals": json.loads(row["emerging_signals"] or "[]") if "emerging_signals" in columns else [],
            "mood_trajectory": json.loads(row["mood_trajectory"] or "[]") if "mood_trajectory" in columns else [],
            "snapshot_version": int(row["snapshot_version"] or 1),
            "created_at": float(row["created_at"]),
        }

    def _relation_row_to_dict(self, row: aiosqlite.Row) -> Dict[str, Any]:
        columns = set(row.keys()) if hasattr(row, "keys") else set()
        return {
            "triple_id": str(row["triple_id"]),
            "subject_id": str(row["subject_id"]),
            "subject_type": str(row["subject_type"]),
            "predicate": str(row["predicate"]),
            "object_id": str(row["object_id"]),
            "object_type": str(row["object_type"]),
            "fact_kind": str(row["fact_kind"]),
            "confidence": float(row["confidence"]),
            "evidence_event_ids": json.loads(row["evidence_event_ids"] or "[]"),
            "observation_count": int(row["observation_count"]),
            "first_observed_at": float(row["first_observed_at"]),
            "last_observed_at": float(row["last_observed_at"]),
            "last_confirmed_at": float(row["last_confirmed_at"]) if row["last_confirmed_at"] else None,
            "source_type": row["source_type"],
            "extraction_method": row["extraction_method"],
            "evidence_text": str(row["evidence_text"] or "") if "evidence_text" in columns else "",
            "natural_summary": str(row["natural_summary"] or "") if "natural_summary" in columns else "",
            "embedding_status": str(row["embedding_status"] or "pending") if "embedding_status" in columns else "pending",
            "expires_at": float(row["expires_at"]) if "expires_at" in columns and row["expires_at"] else None,
            "valid_from": (
                float(row["valid_from"])
                if "valid_from" in columns and row["valid_from"] is not None
                else None
            ),
            "valid_to": (
                float(row["valid_to"])
                if "valid_to" in columns and row["valid_to"] is not None
                else None
            ),
            "status": str(row["status"]),
            "status_reason": (
                str(row["status_reason"])
                if "status_reason" in columns and row["status_reason"]
                else None
            ),
            "deprecated_by": row["deprecated_by"],
            "deprecated_at": float(row["deprecated_at"]) if row["deprecated_at"] else None,
            # NULL evidence_class is load-bearing: downstream filter treats it
            # as "unknown — apply default weight, do NOT exclude", so surface
            # it as None rather than coercing to a string.
            "evidence_class": (
                str(row["evidence_class"])
                if "evidence_class" in columns and row["evidence_class"] is not None
                else None
            ),
            "slot_key": str(row["slot_key"] or "") if "slot_key" in columns else "",
            "claim_fingerprint": (
                str(row["claim_fingerprint"] or "")
                if "claim_fingerprint" in columns
                else ""
            ),
            "authority_ref": (
                str(row["authority_ref"])
                if "authority_ref" in columns and row["authority_ref"]
                else None
            ),
            "scope_key": (
                str(row["scope_key"] or "global")
                if "scope_key" in columns
                else "global"
            ),
            "scope": (
                json.loads(row["scope_json"] or "{}")
                if "scope_json" in columns
                else {}
            ),
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }
