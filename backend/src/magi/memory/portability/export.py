"""Human-readable, non-restorable memory export packages."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum
import errno
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import uuid
import zipfile

from ..event_contracts import AuthorType, ContentType, MemoryDomain, RetentionClass
from ..evidence import EvidenceClass, EvidenceStatus, L1RetrievalScope
from ..source_event_governance import source_occurrence_visible_predicate
from .backup import (
    _fsync_directory,
    _fsync_file,
    _magi_version,
    _open_private_exclusive,
    _require_free_space,
    _require_output_directory,
)
from .errors import MemoryPortabilityError
from .models import EXPORT_FORMAT, EXPORT_FORMAT_VERSION, SnapshotBundle, utc_now_iso

_RECORD_SCHEMA_VERSION = 1
# Covers sixfold JSON control-character escaping, repeated DTO field names, and ZIP metadata.
_STRUCTURED_EXPORT_EXPANSION_FACTOR = 16
_EXPORT_FIXED_OVERHEAD_BYTES = 8 * 1024 * 1024
_COMMON_FIELDS = (
    {"name": "record_type", "type": "string"},
    {"name": "schema_version", "type": "integer"},
    {"name": "layer", "type": "string"},
)

_Decoder = Callable[[object], object]


@dataclass(frozen=True, slots=True)
class _ExportField:
    """One deliberately public field in a readable-export DTO."""

    name: str
    value_type: str
    source: str
    decoder: _Decoder | None = None
    json_path: tuple[str, ...] = ()

    def read(self, row: sqlite3.Row) -> object:
        value: object = row[self.source]
        if self.json_path:
            value = _json_path_value(value, self.json_path)
        if self.decoder is not None:
            value = self.decoder(value)
        return value


@dataclass(frozen=True, slots=True)
class _ExportSpec:
    """A versioned JSONL record contract backed by explicit SQLite columns."""

    database: str
    archive_path: str
    table: str
    record_type: str
    layer: str
    description: str
    fields: tuple[_ExportField, ...]
    order_by: tuple[str, ...]
    table_optional: bool = False
    visibility_sql: str = "1"


def _field(
    name: str,
    value_type: str,
    source: str | None = None,
    *,
    decoder: _Decoder | None = None,
    json_path: tuple[str, ...] = (),
) -> _ExportField:
    return _ExportField(
        name=name,
        value_type=value_type,
        source=source or name,
        decoder=decoder,
        json_path=json_path,
    )


def _json_field(
    name: str,
    value_type: str,
    source: str | None = None,
) -> _ExportField:
    return _field(name, value_type, source, decoder=_json_decoder(value_type))


def _optional_enum_label(enum_type: type[IntEnum]) -> _Decoder:
    def decode(value: object) -> object:
        if value is None:
            return None
        return enum_type.from_value(value).label  # type: ignore[attr-defined]

    return decode


def _as_bool(value: object) -> object:
    return None if value is None else bool(value)


def _status_from_deleted_at(value: object) -> str:
    return "active" if value is None else "deleted"


def _status_from_success(value: object) -> str:
    return "succeeded" if value else "failed"


def _status_from_active(value: object) -> str:
    return "active" if value else "inactive"


def _status_from_invalidated_at(value: object) -> str:
    return "active" if value is None else "invalidated"


def _archived_status(_value: object) -> str:
    return "archived"


def _decode_json(value: object) -> object:
    if value is None or value == "":
        return None
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    return json.loads(str(value))


def _json_decoder(value_type: str) -> _Decoder:
    allowed_types = frozenset(value_type.split("|"))

    def decode(value: object) -> object:
        parsed = _decode_json(value)
        if parsed is None:
            actual_type = "null"
        elif isinstance(parsed, bool):
            actual_type = "boolean"
        elif isinstance(parsed, dict):
            actual_type = "object"
        elif isinstance(parsed, list):
            actual_type = "array"
        elif isinstance(parsed, str):
            actual_type = "string"
        elif isinstance(parsed, (int, float)):
            actual_type = "number"
        else:
            raise ValueError("Unsupported JSON value in readable export")
        if actual_type not in allowed_types:
            raise ValueError(f"Expected readable export JSON type {value_type}, got {actual_type}")
        return parsed

    return decode


def _json_path_value(value: object, path: tuple[str, ...]) -> object:
    current = _decode_json(value)
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


_CURRENT_EXPORT_SPECS: tuple[_ExportSpec, ...] = (
    _ExportSpec(
        database="l1",
        archive_path="l1/events.jsonl",
        table="fact_events",
        visibility_sql="deleted_at IS NULL",
        record_type="l1_event",
        layer="L1",
        description="Durable source events and their evidence classification.",
        fields=(
            _field("event_id", "string"),
            _field("occurred_at", "number", "timestamp"),
            _field("created_at", "number"),
            _field("category", "string", "event_type"),
            _field("source", "string"),
            _field("source_item_id", "string|null"),
            _field(
                "memory_domain",
                "string",
                decoder=_optional_enum_label(MemoryDomain),
            ),
            _field("cognition_eligible", "boolean", decoder=_as_bool),
            _field(
                "retention_class",
                "string",
                decoder=_optional_enum_label(RetentionClass),
            ),
            _field("session_id", "string|null"),
            _field("turn_id", "string|null"),
            _field("session_sequence", "integer|null", "session_seq"),
            _field("user_id", "string|null"),
            _field("content", "string"),
            _field("author_type", "string", decoder=_optional_enum_label(AuthorType)),
            _field("content_type", "string", decoder=_optional_enum_label(ContentType)),
            _field("importance_score", "number"),
            _field("media_reference", "string|null", "media_path"),
            _field("status", "string", "deleted_at", decoder=_status_from_deleted_at),
            _field("deleted_at", "number|null"),
            _field(
                "evidence_status",
                "string",
                decoder=_optional_enum_label(EvidenceStatus),
            ),
            _field(
                "evidence_class",
                "string",
                decoder=_optional_enum_label(EvidenceClass),
            ),
            _field("evidence_rule_version", "integer"),
            _field(
                "retrieval_scope",
                "string",
                "l1_retrieval_scope",
                decoder=_optional_enum_label(L1RetrievalScope),
            ),
        ),
        order_by=("timestamp", "event_id"),
    ),
    _ExportSpec(
        database="l1",
        archive_path="l1/source_payloads.jsonl",
        table="l1_event_payload",
        visibility_sql="event_id IN (SELECT event_id FROM fact_events WHERE deleted_at IS NULL)",
        record_type="l1_source_payload",
        layer="L1",
        description="Pinned source text retained for an L1 event.",
        fields=(
            _field("event_id", "string"),
            _field("content", "string"),
            _field("created_at", "number"),
        ),
        order_by=("created_at", "event_id"),
    ),
    _ExportSpec(
        database="l1",
        archive_path="l1/event_entities.jsonl",
        table="l1_event_entities",
        visibility_sql="event_id IN (SELECT event_id FROM fact_events WHERE deleted_at IS NULL)",
        record_type="l1_event_entity",
        layer="L1",
        description="Entity links attached directly to an L1 event.",
        fields=(
            _field("event_id", "string"),
            _field("entity_id", "string"),
            _field("entity_type", "string|null"),
            _field("confidence", "number|null"),
            _field("created_at", "number"),
        ),
        order_by=("event_id", "entity_id"),
    ),
    _ExportSpec(
        database="l1",
        archive_path="l1/source_facets.jsonl",
        table="l1_source_facets",
        visibility_sql="event_id IN (SELECT event_id FROM fact_events WHERE deleted_at IS NULL)",
        record_type="l1_source_facet",
        layer="L1",
        description="Typed source attributes associated with an L1 event.",
        fields=(
            _field("event_id", "string"),
            _field("source", "string"),
            _field("category", "string", "facet_name"),
            _field("text_value", "string|null"),
            _field("normalized_text_value", "string|null"),
            _field("numeric_value", "number|null"),
            _field("timestamp_value", "number|null"),
            _json_field(
                "structured_value",
                "object|array|string|number|boolean|null",
                "json_value",
            ),
            _field("created_at", "number"),
        ),
        order_by=("event_id", "facet_name"),
    ),
)

_CURRENT_EXPORT_SPECS += (
    _ExportSpec(
        database="memory",
        archive_path="l2/entities.jsonl",
        table="entity_catalog",
        record_type="l2_entity",
        layer="L2",
        description="Canonical entities used by structured memory.",
        fields=(
            _field("entity_id", "string"),
            _field("display_name", "string", "canonical_name"),
            _field("category", "string", "entity_type"),
            _field(
                "name_is_independent",
                "boolean",
                "canonical_name_is_independent",
                decoder=_as_bool,
            ),
            _field("created_at", "number"),
            _field("updated_at", "number"),
        ),
        order_by=("created_at", "entity_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="l2/entity_name_evidence.jsonl",
        table="entity_name_evidence",
        record_type="l2_entity_name_evidence",
        layer="L2",
        description="Source-event evidence supporting entity names.",
        fields=(
            _field("entity_id", "string"),
            _field("category", "string", "name_kind"),
            _field("normalized_name", "string"),
            _field("display_name", "string"),
            _field("source_event_id", "string", "event_id"),
            _field("confidence", "number"),
            _field("created_at", "number"),
            _field("updated_at", "number"),
        ),
        order_by=("entity_id", "name_kind", "normalized_name", "event_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="l2/entity_aliases.jsonl",
        table="entity_aliases",
        record_type="l2_entity_alias",
        layer="L2",
        description="Alternate entity names and their canonical entity link.",
        fields=(
            _field("alias_id", "integer"),
            _field("entity_id", "string"),
            _field("alias", "string", "alias_text"),
            _field("normalized_alias", "string"),
            _field("confidence", "number"),
            _field("is_independent", "boolean", decoder=_as_bool),
            _field("created_at", "number"),
            _field("updated_at", "number"),
        ),
        order_by=("created_at", "alias_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="l2/entity_mentions.jsonl",
        table="entity_mentions",
        record_type="l2_entity_mention",
        layer="L2",
        description="Observed entity mentions with source-event evidence and resolution.",
        fields=(
            _field("mention_id", "integer"),
            _field("mention_text", "string"),
            _field("normalized_surface", "string"),
            _field("category", "string|null", "entity_type"),
            _json_field("source_event_ids", "array", "evidence_event_ids"),
            _field("evidence_text", "string|null"),
            _field("resolved_entity_id", "string|null"),
            _field("confidence", "number|null"),
            _field("created_at", "number"),
        ),
        order_by=("created_at", "mention_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="l2/entity_facets.jsonl",
        table="entity_facets",
        record_type="l2_entity_facet",
        layer="L2",
        description="Observed entity attributes with source-event lineage.",
        fields=(
            _field("facet_id", "string"),
            _field("entity_id", "string"),
            _field("entity_type", "string"),
            _field("category", "string", "facet_name"),
            _field("value", "string", "facet_value"),
            _field("confidence", "number"),
            _json_field("source_event_ids", "array", "evidence_event_ids"),
            _field("first_observed_at", "number|null"),
            _field("last_observed_at", "number|null"),
            _field("source", "string|null", "source_type"),
            _field("extraction_method", "string|null"),
            _field("status", "string"),
            _field("created_at", "number"),
            _field("updated_at", "number"),
        ),
        order_by=("created_at", "facet_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="l2/claims.jsonl",
        table="l2_grounded_claims",
        record_type="l2_claim",
        layer="L2",
        description="Grounded claims, validity windows, and forgetting state.",
        fields=(
            _field("claim_id", "string"),
            _field("identity_key", "string"),
            _field("user_id", "string|null"),
            _field("subject_ref", "string|null"),
            _field("subject_type", "string|null"),
            _field("category", "string|null", "canonical_predicate"),
            _field("fact_kind", "string|null"),
            _field("object_type", "string|null"),
            _field("polarity", "string|null"),
            _field("specificity", "string|null"),
            _field("confidence", "number|null"),
            _json_field(
                "object_value",
                "object|array|string|number|boolean|null",
                "object_value_json",
            ),
            _field("object_surface", "string|null"),
            _field("temporal_cue", "string|null"),
            _field("valid_from", "number|null", "fact_valid_from"),
            _field("valid_to", "number|null", "fact_valid_to"),
            _field("target_from", "number|null"),
            _field("target_to", "number|null"),
            _field("availability", "string"),
            _field("evidence_rule_version", "integer"),
            _field("created_at", "number"),
            _field("updated_at", "number"),
            _field("forgotten_at", "number|null"),
            _field("forget_tombstone_key", "string|null"),
        ),
        order_by=("created_at", "claim_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="l2/claim_evidence.jsonl",
        table="l2_claim_evidence",
        record_type="l2_claim_evidence",
        layer="L2",
        description="L1 evidence and timestamp quality supporting grounded claims.",
        fields=(
            _field("claim_id", "string"),
            _field("source_event_id", "string", "event_id"),
            _field("category", "string", "link_role"),
            _field("required_for_grounding", "boolean", decoder=_as_bool),
            _field("event_time", "number|null"),
            _field("timestamp_confidence", "string"),
            _field("timestamp_quality", "string|null"),
            _field("timestamp_anchor_source", "string|null"),
            _field("evidence_rule_version", "integer"),
            _field("evidence_mode", "string"),
            _field("source", "string|null", "source_type"),
            _field("source_domain", "string|null"),
            _field("author_type", "string|null"),
            _field("evidence_class", "string|null"),
            _json_field("evidence_locator", "object|array|null", "evidence_locator_json"),
            _field("created_at", "number"),
        ),
        order_by=("claim_id", "event_id", "link_role"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="l2/claim_entity_refs.jsonl",
        table="l2_claim_entity_refs",
        record_type="l2_claim_entity_ref",
        layer="L2",
        description="Resolved entity references for grounded claims and invalidation state.",
        fields=(
            _field("claim_id", "string"),
            _field("category", "string", "ref_role"),
            _field("entity_id", "string"),
            _field("resolution_version", "integer"),
            _field(
                "status",
                "string",
                "invalidated_at",
                decoder=_status_from_invalidated_at,
            ),
            _field("created_at", "number"),
            _field("invalidated_at", "number|null"),
            _field("invalidated_reason", "string|null"),
        ),
        order_by=("claim_id", "ref_role", "resolution_version"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="l2/relationships.jsonl",
        table="knowledge_graph",
        record_type="l2_relationship",
        layer="L2",
        description="Current governed relationships and their evidence lineage.",
        fields=(
            _field("relationship_id", "string", "triple_id"),
            _field("subject_id", "string"),
            _field("subject_type", "string"),
            _field("category", "string", "predicate"),
            _field("object_id", "string"),
            _field("object_type", "string"),
            _field("fact_kind", "string"),
            _field("confidence", "number"),
            _json_field("source_event_ids", "array", "evidence_event_ids"),
            _field("evidence_text", "string|null"),
            _field("natural_summary", "string|null"),
            _field("first_observed_at", "number|null"),
            _field("last_observed_at", "number|null"),
            _field("last_confirmed_at", "number|null"),
            _field("source", "string|null", "source_type"),
            _field("extraction_method", "string|null"),
            _field("status", "string"),
            _field("status_reason", "string|null"),
            _field("deprecated_by", "string|null"),
            _field("deprecated_at", "number|null"),
            _field("valid_from", "number|null"),
            _field("valid_to", "number|null"),
            _field("expires_at", "number|null"),
            _field("evidence_class", "string|null"),
            _field("slot_key", "string|null"),
            _field("claim_fingerprint", "string|null"),
            _field("authority_ref", "string|null"),
            _field("scope_key", "string|null"),
            _json_field("scope", "object|array|null", "scope_json"),
            _field("created_at", "number"),
            _field("updated_at", "number"),
        ),
        order_by=("created_at", "triple_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="l2/relationship_versions.jsonl",
        table="knowledge_graph_versions",
        record_type="l2_relationship_version",
        layer="L2",
        description="Immutable relationship history, including correction lineage.",
        fields=(
            _field("version_id", "string"),
            _field("relationship_id", "string", "triple_id"),
            _field("previous_version_id", "string|null"),
            _field("subject_id", "string"),
            _field("subject_type", "string"),
            _field("category", "string", "predicate"),
            _field("object_id", "string"),
            _field("object_type", "string"),
            _field("fact_kind", "string"),
            _field("confidence", "number"),
            _json_field("source_event_ids", "array", "evidence_event_ids"),
            _field("evidence_text", "string|null"),
            _field("natural_summary", "string|null"),
            _field("status", "string"),
            _field("valid_from", "number|null"),
            _field("valid_to", "number|null"),
            _field("correction_id", "string|null"),
            _field("slot_key", "string|null"),
            _field("claim_fingerprint", "string|null"),
            _field("authority_ref", "string|null"),
            _field("scope_key", "string|null"),
            _json_field("scope", "object|array|null", "scope_json"),
            _field("governance_complete", "boolean", decoder=_as_bool),
            _field("created_at", "number"),
        ),
        order_by=("created_at", "version_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="l2/assertions.jsonl",
        table="tom_trait_assertions",
        record_type="l2_assertion",
        layer="L2",
        description="Governed trait assertions and their semantic/version lineage.",
        fields=(
            _field("assertion_id", "string"),
            _field("entity_id", "string"),
            _field("entity_type", "string"),
            _field("category", "string", "trait_family"),
            _field("trait_name", "string"),
            _field("trait_value", "string"),
            _field("confidence", "number", "confidence_score"),
            _json_field("source_event_ids", "array", "evidence_events"),
            _field("source", "string", "source_domain"),
            _field("inference_depth", "string"),
            _field("validation_state", "string"),
            _field("status", "string"),
            _field("natural_summary", "string|null"),
            _field("first_inferred_at", "number"),
            _field("last_validated_at", "number|null"),
            _field("valid_from", "number|null"),
            _field("valid_to", "number|null"),
            _field("expires_at", "number|null"),
            _field("superseded_by", "string|null"),
            _field("superseded_at", "number|null"),
            _field("slot_key", "string|null"),
            _field("claim_fingerprint", "string|null"),
            _field("authority_ref", "string|null"),
            _field("version_root_id", "string|null"),
            _field("previous_version_id", "string|null"),
            _field("scope_key", "string|null"),
            _json_field("scope", "object|array|null", "scope_json"),
            _field("semantic_lineage_key", "string|null"),
            _json_field("target_window", "object|array|null", "target_window_json"),
            _field("created_at", "number"),
            _field("updated_at", "number"),
        ),
        order_by=("created_at", "assertion_id"),
    ),
)

_CURRENT_EXPORT_SPECS += (
    _ExportSpec(
        database="memory",
        archive_path="l2/episodes.jsonl",
        table="episodes",
        record_type="l2_episode",
        layer="L2",
        description="Bounded episodes assembled from source events.",
        fields=(
            _field("episode_id", "string"),
            _field("category", "string", "episode_type"),
            _field("status", "string"),
            _field("time_start", "number"),
            _field("time_end", "number"),
            _field("parent_episode_id", "string|null"),
            _field("label", "string|null"),
            _field("summary", "string|null"),
            _field("dominant_mode", "string|null"),
            _json_field("primary_entity_ids", "array"),
            _json_field("primary_place_ids", "array"),
            _json_field("primary_topic_keys", "array"),
            _field("formation_method", "string"),
            _field("confidence", "number"),
            _field("source_event_count", "integer"),
            _field("user_label", "string|null"),
            _field("user_note", "string|null"),
            _field("user_pinned", "boolean", decoder=_as_bool),
            _field("representative_asset_ref", "string|null"),
            _field("created_at", "number"),
            _field("updated_at", "number"),
        ),
        order_by=("time_start", "episode_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="l2/episode_evidence.jsonl",
        table="episode_events",
        record_type="l2_episode_evidence",
        layer="L2",
        description="Source-event membership for episodes.",
        fields=(
            _field("episode_id", "string"),
            _field("source_event_id", "string", "event_id"),
            _field("category", "string", "membership_role"),
            _field("confidence", "number", "membership_confidence"),
            _field("created_at", "number", "added_at"),
        ),
        order_by=("episode_id", "event_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="l2/location_samples.jsonl",
        table="location_samples",
        record_type="l2_location_sample",
        layer="L2",
        description="Timestamped location observations and their source metadata.",
        fields=(
            _field("sample_id", "string"),
            _field("source", "string"),
            _field("sampled_at", "number"),
            _field("latitude", "number|null", "lat"),
            _field("longitude", "number|null", "lng"),
            _field("accuracy_m", "number|null"),
            _field("city", "string|null"),
            _field("region", "string|null"),
            _field("country", "string|null"),
            _json_field("metadata", "object", "metadata_json"),
            _field("created_at", "number"),
        ),
        order_by=("sampled_at", "sample_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="l2/place_labels.jsonl",
        table="place_labels",
        record_type="l2_place_label",
        layer="L2",
        description="User-defined labels for bounded geographic places.",
        fields=(
            _field("place_label_id", "string", "label_id"),
            _field("center_latitude", "number", "center_lat"),
            _field("center_longitude", "number", "center_lng"),
            _field("radius_m", "number"),
            _field("label", "string", "user_label"),
            _field("created_at", "number"),
        ),
        order_by=("created_at", "label_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="l2/experiences.jsonl",
        table="experiences",
        record_type="l2_experience",
        layer="L2",
        description="User-facing experiences assembled from episodes and events.",
        fields=(
            _field("experience_id", "string"),
            _field("category", "string|null", "experience_type"),
            _field("status", "string"),
            _field("title", "string|null"),
            _field("time_start", "number"),
            _field("time_end", "number"),
            _field("intent", "string|null"),
            _field("outcome", "string|null"),
            _field("interpretation", "string|null", "magi_interpretation"),
            _field("narrative_score", "number"),
            _json_field("primary_entity_ids", "array"),
            _json_field("primary_place_ids", "array"),
            _json_field("primary_topic_keys", "array"),
            _field("source_episode_count", "integer"),
            _field("source_event_count", "integer"),
            _field("source_seed_id", "string|null"),
            _field("parent_experience_id", "string|null"),
            _field("merged_into_experience_id", "string|null"),
            _field("user_label", "string|null"),
            _field("user_note", "string|null"),
            _field("user_pinned", "boolean", decoder=_as_bool),
            _field("user_cover_asset_ref", "string|null"),
            _field("created_at", "number"),
            _field("updated_at", "number"),
        ),
        order_by=("time_start", "experience_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="l2/experience_members.jsonl",
        table="experience_members",
        record_type="l2_experience_member",
        layer="L2",
        description="Episode, event, and other member links within an experience.",
        fields=(
            _field("experience_id", "string"),
            _field("category", "string", "member_type"),
            _field("member_id", "string"),
            _field("role", "string"),
            _field("confidence", "number"),
            _field("created_at", "number", "added_at"),
        ),
        order_by=("experience_id", "member_type", "member_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="l2/experience_evidence.jsonl",
        table="experience_key_events",
        record_type="l2_experience_evidence",
        layer="L2",
        description="Selected source events supporting an experience.",
        fields=(
            _field("experience_id", "string"),
            _field("source_event_id", "string", "event_id"),
            _field("category", "string", "role"),
            _field("reason", "string|null"),
            _field("confidence", "number"),
            _field("created_at", "number", "added_at"),
        ),
        order_by=("experience_id", "event_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="l2/experience_seeds.jsonl",
        table="experience_seeds",
        record_type="l2_experience_seed",
        layer="L2",
        description="Candidate experience seeds, anchors, source, and promotion status.",
        fields=(
            _field("seed_id", "string"),
            _field("category", "string", "seed_type"),
            _field("status", "string"),
            _field("title", "string|null"),
            _field("description", "string|null"),
            _json_field("anchor_entity_ids", "array"),
            _json_field("anchor_place_ids", "array"),
            _json_field("anchor_topic_keys", "array"),
            _field("time_start", "number|null"),
            _field("time_end", "number|null"),
            _field("confidence", "number"),
            _field("source", "string", "created_by"),
            _field("source_reference_type", "string|null", "source_ref_type"),
            _field("source_reference_id", "string|null", "source_ref_id"),
            _field("promoted_experience_id", "string|null"),
            _field("created_at", "number"),
            _field("updated_at", "number"),
            _field("last_evaluated_at", "number|null"),
        ),
        order_by=("created_at", "seed_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="l2/experience_seed_evidence.jsonl",
        table="experience_seed_evidence",
        record_type="l2_experience_seed_evidence",
        layer="L2",
        description="Evidence references supporting an experience seed.",
        fields=(
            _field("seed_id", "string"),
            _field("category", "string", "ref_type"),
            _field("reference_id", "string", "ref_id"),
            _field("role", "string"),
            _field("confidence", "number"),
            _field("reason", "string|null"),
            _field("created_at", "number"),
        ),
        order_by=("seed_id", "ref_type", "ref_id", "role"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="l2/experience_chapters.jsonl",
        table="experience_chapters",
        record_type="l2_experience_chapter",
        layer="L2",
        description="Ordered experience chapters and their episode/event references.",
        fields=(
            _field("experience_id", "string"),
            _field("chapter_id", "string"),
            _field("position", "integer"),
            _field("title", "string"),
            _field("summary", "string"),
            _field("time_start", "number|null"),
            _field("time_end", "number|null"),
            _json_field("episode_ids", "array", "episode_ids_json"),
            _json_field("source_event_ids", "array", "event_ids_json"),
            _field("created_at", "number"),
            _field("updated_at", "number"),
        ),
        order_by=("experience_id", "position", "chapter_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="l2/manual_entries.jsonl",
        table="manual_entries",
        visibility_sql=(
            "deleted_at IS NULL AND delete_requested_at IS NULL "
            "AND (pending_l1_event_id IS NULL OR pending_l1_predecessor_event_id IS NULL) "
            f"AND {source_occurrence_visible_predicate('manual_entries.event_at')}"
        ),
        record_type="l2_manual_entry",
        layer="L2",
        description="User-authored manual memories and managed asset references.",
        fields=(
            _field("entry_id", "string"),
            _field("category", "string", "kind"),
            _field("event_at", "number"),
            _field("body", "string"),
            _field("mood", "string|null"),
            _field("location_label", "string|null"),
            _field("location_latitude", "number|null", "location_lat"),
            _field("location_longitude", "number|null", "location_lng"),
            _json_field("asset_references", "array", "attachments_json"),
            _field("exclude_from_llm", "boolean", decoder=_as_bool),
            _field("user_pinned", "boolean", decoder=_as_bool),
            _field("status", "string", "deleted_at", decoder=_status_from_deleted_at),
            _field("deleted_at", "number|null"),
            _field("source_event_id", "string|null", "l1_event_id"),
            _json_field("weather", "object|null", "weather_json"),
            _field("created_at", "number"),
        ),
        order_by=("event_at", "entry_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="l2/pending_reviews.jsonl",
        table="l2_pending_reviews",
        record_type="l2_pending_review",
        layer="L2",
        description="Governed memory proposals and user resolution lineage.",
        fields=(
            _field("review_id", "string"),
            _field("subject_id", "string"),
            _field("category", "string", "kind"),
            _field("slot_key", "string"),
            _field("semantic_lineage_key", "string"),
            _json_field("claim_ids", "array", "claim_ids_json"),
            _field("reason_code", "string"),
            _json_field(
                "proposed_value",
                "object|array|string|number|boolean|null",
                "proposed_json",
            ),
            _field("evidence_rule_version", "integer"),
            _field("status", "string"),
            _field("resolution_action", "string|null"),
            _json_field("resolution", "object|array|null", "resolution_payload_json"),
            _field("resolution_event_id", "string|null"),
            _field("resolved_by", "string|null"),
            _field("close_reason", "string|null"),
            _field("created_at", "number"),
            _field("updated_at", "number"),
            _field("resolved_at", "number|null"),
        ),
        order_by=("created_at", "review_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="l3/summaries.jsonl",
        table="summaries",
        record_type="l3_summary",
        layer="L3",
        description="Longer-horizon summaries and their source-event references.",
        fields=(
            _field("summary_id", "string"),
            _field("category", "string", "summary_category"),
            _field("summary_type", "string"),
            _field("period_start", "number"),
            _field("period_end", "number"),
            _field("content", "string"),
            _json_field("key_topics", "array|null"),
            _json_field("key_entities", "array|null"),
            _field("sentiment_summary", "string|null"),
            _field("change_and_pattern", "string|null"),
            _json_field("source_event_ids", "array"),
            _field("source_event_count", "integer"),
            _field("importance", "number|null", "importance_aggregate"),
            _field("generation_source", "string|null", "generated_by_model"),
            _field("generation_reason", "string|null"),
            _field("insight_key", "string|null"),
            _field("review_state", "string|null"),
            _field("narrative_style", "string|null"),
            _field("essence_prose", "string|null"),
            _field("status", "string", "derivation_state"),
            _field("created_at", "number"),
            _field("updated_at", "number"),
        ),
        order_by=("period_start", "summary_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="l3/summary_evidence.jsonl",
        table="summary_event_links",
        record_type="l3_summary_evidence",
        layer="L3",
        description="Source-event evidence linked to an L3 summary.",
        fields=(
            _field("link_id", "string"),
            _field("summary_id", "string"),
            _field("source_event_id", "string", "event_id"),
            _field("category", "string", "link_role"),
            _field("evidence_weight", "number"),
            _field("created_at", "number"),
        ),
        order_by=("summary_id", "event_id", "link_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="l3/daily_moods.jsonl",
        table="daily_mood_aggregate",
        record_type="l3_daily_mood",
        layer="L3",
        description="Daily mood aggregates with contributing source events.",
        fields=(
            _field("date", "string", "day_local_date"),
            _field("category", "string", "dominant_valence"),
            _field("volatility_score", "number"),
            _json_field("state_curve", "array", "state_curve_compact"),
            _field("source_event_count", "integer", "event_count"),
            _json_field("source_event_ids", "array"),
            _field("computed_at", "number"),
        ),
        order_by=("day_local_date",),
    ),
    _ExportSpec(
        database="memory",
        archive_path="l3/user_profiles.jsonl",
        table="user_profile_projection",
        record_type="l3_user_profile",
        layer="L3",
        description="Current user profile with field-level sources and conflicts.",
        fields=(
            _field("user_id", "string"),
            _field("entity_id", "string"),
            _field("display_name", "string"),
            _field("preferred_form_of_address", "string"),
            _field("real_name", "string"),
            _field("birth_date", "string"),
            _field("birth_year", "integer|null"),
            _field("age_years", "integer|null"),
            _field("age_as_of", "string"),
            _field("home_location", "string"),
            _json_field("communication", "object", "communication_json"),
            _json_field("identity", "object", "identity_json"),
            _json_field("preferences", "object", "preferences_json"),
            _json_field("state", "object", "state_json"),
            _json_field("field_sources", "object", "field_sources_json"),
            _json_field("field_conflicts", "object", "field_conflicts_json"),
            _field("completeness_score", "number"),
            _field("refreshed_at", "number"),
            _field("created_at", "number"),
            _field("updated_at", "number"),
        ),
        order_by=("created_at", "user_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="l3/user_portraits.jsonl",
        table="user_portrait_projection",
        record_type="l3_user_portrait",
        layer="L3",
        description="Product-facing self portrait with evidence references.",
        fields=(
            _field("user_id", "string"),
            _field("entity_id", "string"),
            _field("category", "string", "entity_type"),
            _json_field("world", "object", "world_json"),
            _json_field("review", "object", "review_json"),
            _json_field("recent", "object", "recent_json"),
            _json_field("prompt_summary", "array", "prompt_summary_json"),
            _json_field("evidence_references", "array", "evidence_refs_json"),
            _json_field("source_counts", "object", "source_counts_json"),
            _field("source", "string", "generated_by"),
            _field("generated_at", "number"),
            _field("created_at", "number"),
            _field("updated_at", "number"),
        ),
        order_by=("created_at", "user_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="l4/procedures.jsonl",
        table="procedural_skills",
        visibility_sql="deleted_at IS NULL",
        record_type="l4_procedure",
        layer="L4",
        description="Learned procedures and their source-event lineage.",
        fields=(
            _field("procedure_id", "string", "skill_id"),
            _field("name", "string", "skill_name"),
            _field("category", "string", "skill_category"),
            _field("procedure_type", "string", "skill_type"),
            _field("proficiency", "number"),
            _field("total_attempts", "integer"),
            _field("success_count", "integer"),
            _field("failure_count", "integer"),
            _field("success_rate", "number"),
            _field("optimized_prompt", "string|null"),
            _json_field("optimized_parameters", "object|array|null", "optimized_params"),
            _json_field("context_affinity", "object|array|null"),
            _json_field("source_event_ids", "array"),
            _field("last_used_at", "number|null"),
            _field("last_success_at", "number|null"),
            _field("last_failure_at", "number|null"),
            _field("status", "string", "deleted_at", decoder=_status_from_deleted_at),
            _field("deleted_at", "number|null"),
            _field("created_at", "number"),
            _field("updated_at", "number"),
        ),
        order_by=("created_at", "skill_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="l4/execution_traces.jsonl",
        table="l4_execution_traces",
        visibility_sql="skill_id IN (SELECT skill_id FROM procedural_skills WHERE deleted_at IS NULL)",
        record_type="l4_execution_trace",
        layer="L4",
        description="Outcomes used to learn and evaluate a procedure.",
        fields=(
            _field("trace_id", "string"),
            _field("procedure_id", "string", "skill_id"),
            _field("source_event_id", "string|null", "event_id"),
            _field("source_turn_id", "string|null", "turn_id"),
            _field("status", "string", "success", decoder=_status_from_success),
            _field("duration_ms", "number|null"),
            _field("error_summary", "string|null"),
            _field("input_summary", "string|null"),
            _field("output_summary", "string|null"),
            _field("task_context", "string|null"),
            _field("created_at", "number"),
        ),
        order_by=("created_at", "trace_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="l4/procedure_evidence.jsonl",
        table="l4_skill_event_links",
        visibility_sql="skill_id IN (SELECT skill_id FROM procedural_skills WHERE deleted_at IS NULL)",
        record_type="l4_procedure_evidence",
        layer="L4",
        description="Source-event evidence linked to a learned procedure.",
        fields=(
            _field("procedure_id", "string", "skill_id"),
            _field("source_event_id", "string", "event_id"),
            _field("created_at", "number"),
        ),
        order_by=("skill_id", "event_id"),
    ),
)

_CURRENT_EXPORT_SPECS += (
    _ExportSpec(
        database="memory",
        archive_path="governance/corrections.jsonl",
        table="memory_corrections",
        record_type="memory_correction",
        layer="governance",
        description="User correction requests and replacement lineage.",
        fields=(
            _field("correction_id", "string"),
            _field("request_id", "string"),
            _field("actor_id", "string|null"),
            _field("target_kind", "string"),
            _field("target_id", "string"),
            _field("slot_key", "string|null"),
            _field("claim_fingerprint", "string|null"),
            _field("category", "string", "correction_kind"),
            _field("reason", "string|null"),
            _json_field(
                "before",
                "object|array|string|number|boolean|null",
                "before_json",
            ),
            _json_field(
                "replacement",
                "object|array|string|number|boolean|null",
                "replacement_json",
            ),
            _field("effective_at", "number|null"),
            _json_field("scope", "object|array|null", "scope_json"),
            _field("source_event_id", "string|null"),
            _field("audit_event_id", "string|null"),
            _field("replacement_target_id", "string|null"),
            _field("status", "string", "state"),
            _field("created_at", "number"),
            _field("reverted_at", "number|null"),
            _field("reverted_by", "string|null"),
        ),
        order_by=("created_at", "correction_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="governance/correction_rules.jsonl",
        table="memory_correction_rules",
        record_type="memory_correction_rule",
        layer="governance",
        description="Active-time rules created by a correction.",
        fields=(
            _field("rule_id", "string"),
            _field("correction_id", "string"),
            _field("target_kind", "string"),
            _field("category", "string", "rule_kind"),
            _field("slot_key", "string|null"),
            _field("claim_fingerprint", "string|null"),
            _field("scope_key", "string|null"),
            _field("effective_from", "number|null"),
            _field("effective_to", "number|null"),
            _field("status", "string", "active", decoder=_status_from_active),
            _field("created_at", "number"),
        ),
        order_by=("created_at", "rule_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="governance/correction_evidence.jsonl",
        table="memory_correction_evidence_events",
        record_type="memory_correction_evidence",
        layer="governance",
        description="Source events governed by a correction.",
        fields=(
            _field("correction_id", "string"),
            _field("source_event_id", "string", "event_id"),
            _field("target_kind", "string"),
            _field("created_at", "number"),
        ),
        order_by=("correction_id", "event_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="governance/correction_evidence_barriers.jsonl",
        table="memory_correction_evidence_fail_closed",
        record_type="memory_correction_evidence_barrier",
        layer="governance",
        description="Corrections whose evidence lineage must fail closed.",
        fields=(
            _field("correction_id", "string"),
            _field("created_at", "number"),
        ),
        order_by=("created_at", "correction_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="governance/correction_forget_links.jsonl",
        table="memory_correction_forget_barriers",
        record_type="memory_correction_forget_link",
        layer="governance",
        description="Forget rules that govern a prior correction.",
        fields=(
            _field("correction_id", "string"),
            _field("forget_rule_id", "string", "rule_id"),
            _field("created_at", "number"),
        ),
        order_by=("created_at", "correction_id", "rule_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="governance/correction_revert_blocks.jsonl",
        table="memory_correction_revert_blocks",
        record_type="memory_correction_revert_block",
        layer="governance",
        description="Safety reasons preventing a correction from being reverted.",
        fields=(
            _field("correction_id", "string"),
            _field("reason", "string", "block_reason"),
            _field("created_at", "number"),
        ),
        order_by=("created_at", "correction_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="governance/forget_rules.jsonl",
        table="memory_forget_claim_rules",
        record_type="memory_forget_rule",
        layer="governance",
        description="Durable claim barriers created by forgetting.",
        fields=(
            _field("rule_id", "string"),
            _field("target_kind", "string"),
            _field("claim_fingerprint", "string"),
            _field("semantic_fingerprint", "string|null"),
            _field("category", "string", "forget_kind"),
            _field("effective_from", "number|null"),
            _field("effective_to", "number|null"),
            _field("evidence_fail_closed", "boolean", decoder=_as_bool),
            _field("created_at", "number"),
        ),
        order_by=("created_at", "rule_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="governance/forget_rule_evidence.jsonl",
        table="memory_forget_evidence_events",
        record_type="memory_forget_rule_evidence",
        layer="governance",
        description="Source events attached to a durable forget rule.",
        fields=(
            _field("rule_id", "string"),
            _field("source_event_id", "string", "event_id"),
            _field("created_at", "number"),
        ),
        order_by=("rule_id", "event_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="governance/forget_operations.jsonl",
        table="memory_forget_operations",
        record_type="memory_forget_operation",
        layer="governance",
        description="User forget requests and their final cross-layer outcome.",
        fields=(
            _field("operation_id", "string"),
            _field("category", "string", "selector_kind"),
            _json_field("selector", "object|array", "selector_json"),
            _field("reason", "string|null"),
            _field("status", "string"),
            _field("total_event_count", "integer"),
            _field("active_event_count", "integer"),
            _field("cleaned_event_count", "integer"),
            _json_field("result", "object|array|null", "result_json"),
            _field("created_at", "number"),
            _field("updated_at", "number"),
            _field("completed_at", "number|null"),
        ),
        order_by=("created_at", "operation_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="governance/forget_operation_events.jsonl",
        table="memory_forget_operation_events",
        record_type="memory_forget_operation_event",
        layer="governance",
        description="Source-event membership and cleanup status for a forget request.",
        fields=(
            _field("operation_id", "string"),
            _field("source_event_id", "string", "event_id"),
            _field("was_active", "boolean", decoder=_as_bool),
            _field("status", "string", "cleanup_status"),
            _field("created_at", "number"),
            _field("updated_at", "number"),
        ),
        order_by=("operation_id", "event_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="governance/forget_operation_refs.jsonl",
        table="memory_forget_operation_refs",
        record_type="memory_forget_operation_ref",
        layer="governance",
        description="Source-owner references selected by a forget request.",
        fields=(
            _field("operation_id", "string"),
            _field("item_event_id", "string"),
            _field("category", "string", "ref_role"),
            _field("reference_type", "string", "ref_type"),
            _field("source_reference", "string", "source_ref"),
            _field("created_at", "number"),
        ),
        order_by=("operation_id", "item_event_id", "ref_role", "source_ref"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="governance/forgotten_source_events.jsonl",
        table="memory_source_event_tombstones",
        record_type="memory_forgotten_source_event",
        layer="governance",
        description="Source-event tombstones retained after forgetting.",
        fields=(
            _field("source_event_id", "string", "event_id"),
            _field("reason", "string|null"),
            _field("created_at", "number"),
        ),
        order_by=("created_at", "event_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="governance/forgotten_turn_cutoffs.jsonl",
        table="memory_source_turn_cutoffs",
        record_type="memory_forgotten_turn_cutoff",
        layer="governance",
        description="Per-turn cutoffs preventing forgotten evidence from returning.",
        fields=(
            _field("source_turn_id", "string", "turn_id"),
            _field("cutoff_at", "number"),
            _field("reason", "string|null"),
            _field("updated_at", "number"),
        ),
        order_by=("updated_at", "turn_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="governance/forgotten_time_ranges.jsonl",
        table="memory_time_range_forget_barriers",
        record_type="memory_forgotten_time_range",
        layer="governance",
        description="Time-range barriers created by a forget operation.",
        fields=(
            _field("operation_id", "string"),
            _field("target_id", "string"),
            _field("range_start", "number"),
            _field("range_end", "number"),
            _field(
                "delete_source_events",
                "boolean",
                "delete_l1_events",
                decoder=_as_bool,
            ),
            _field("reason", "string|null"),
            _field("created_at", "number"),
        ),
        order_by=("created_at", "operation_id", "target_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="governance/l0_forgotten_source_refs.jsonl",
        table="l0_forgotten_attention_source_refs",
        record_type="l0_forgotten_source_ref",
        layer="governance",
        description="Durable barriers for source references removed from L0.",
        fields=(
            _field("source_reference", "string", "source_ref"),
            _field("created_at", "number"),
        ),
        order_by=("created_at", "source_ref"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="governance/l0_forgotten_entities.jsonl",
        table="l0_forgotten_attention_entities",
        record_type="l0_forgotten_entity",
        layer="governance",
        description="Durable per-entity L0 forgetting cutoffs.",
        fields=(
            _field("entity_id", "string"),
            _field("cutoff_at", "number"),
            _field("operation_id", "string|null"),
            _field("updated_at", "number"),
        ),
        order_by=("updated_at", "entity_id"),
    ),
)

_L0_EXPORT_SPECS: tuple[_ExportSpec, ...] = (
    _ExportSpec(
        database="memory",
        archive_path="l0/sessions.jsonl",
        table="l0_sessions",
        record_type="l0_session",
        layer="L0",
        description="Optional runtime attention sessions.",
        fields=(
            _field("session_id", "string"),
            _field("user_id", "string|null"),
            _field("runtime_agent_id", "string|null"),
            _field("status", "string"),
            _field("started_at", "number"),
            _field("last_active_at", "number"),
            _field("last_checkpoint_at", "number|null"),
        ),
        order_by=("started_at", "session_id"),
    ),
    _ExportSpec(
        database="memory",
        archive_path="l0/attention_items.jsonl",
        table="l0_attention_items",
        record_type="l0_attention_item",
        layer="L0",
        description="Optional short-term attention and source lineage.",
        fields=(
            _field("item_id", "string"),
            _field("session_id", "string"),
            _field("category", "string", "kind"),
            _field("summary", "string"),
            _field("status", "string"),
            _field("salience", "number"),
            _field("confidence", "number"),
            _field("evidence_mode", "string"),
            _json_field("source_turn_ids", "array"),
            _json_field("source_event_ids", "array"),
            _field("entity_id", "string|null"),
            _field("task_id", "string|null"),
            _field("first_seen_at", "number"),
            _field("last_reinforced_at", "number"),
            _field("expires_at", "number|null"),
            _field("supersedes_item_id", "string|null"),
        ),
        order_by=("first_seen_at", "item_id"),
    ),
)
_ARCHIVE_EXPORT_SPECS: tuple[_ExportSpec, ...] = (
    _ExportSpec(
        database="archive",
        archive_path="archives/{date}/l1_events.jsonl",
        table="archived_l1_events",
        visibility_sql="json_extract(payload_json, '$.deleted_at') IS NULL",
        record_type="archived_l1_event",
        layer="L1",
        description="Archived L1 events using a fixed subset of the archived payload.",
        fields=(
            _field("event_id", "string"),
            _field("occurred_at", "number", "event_timestamp"),
            _field("archived_at", "number"),
            _field("archive_date", "string", "archived_date"),
            _field("category", "string", "event_type"),
            _field("source", "string"),
            _field("session_id", "string|null"),
            _field("user_id", "string|null"),
            _field("content", "string|null", "payload_json", json_path=("content",)),
            _field("status", "string", "archived_at", decoder=_archived_status),
            _field(
                "evidence_class",
                "string|null",
                "payload_json",
                json_path=("evidence_class",),
            ),
        ),
        order_by=("event_timestamp", "event_id"),
        table_optional=True,
    ),
    _ExportSpec(
        database="archive",
        archive_path="archives/{date}/l3_summaries.jsonl",
        table="archived_l3_summaries",
        record_type="archived_l3_summary",
        layer="L3",
        description="Archived L3 summaries using a fixed subset of the archived payload.",
        fields=(
            _field("summary_id", "string"),
            _field("period_start", "number"),
            _field("period_end", "number"),
            _field("archived_at", "number"),
            _field("archive_date", "string", "archived_date"),
            _field("summary_type", "string"),
            _field("category", "string", "summary_category"),
            _field(
                "content",
                "string|null",
                "payload_json",
                json_path=("summary", "content"),
            ),
            _field(
                "source_event_ids",
                "array|null",
                "payload_json",
                json_path=("summary", "source_event_ids"),
            ),
            _field("status", "string", "archived_at", decoder=_archived_status),
        ),
        order_by=("period_start", "summary_id"),
        table_optional=True,
    ),
)


def build_readable_export(
    *,
    snapshot: SnapshotBundle,
    output_directory: Path,
    include_l0: bool,
) -> tuple[Path, dict[str, object]]:
    """Write stable JSONL DTOs, their exact field contract, and managed assets."""

    output_directory = _require_output_directory(output_directory)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = output_directory / (f"magi-memory-export-{timestamp}-{uuid.uuid4().hex[:8]}.zip")
    partial_path = output_directory / f".{output_path.name}.partial"
    _require_free_space(output_directory, _required_export_free_bytes(snapshot))
    manifest: dict[str, object] = {
        "format": EXPORT_FORMAT,
        "format_version": EXPORT_FORMAT_VERSION,
        "created_at": utc_now_iso(),
        "magi_version": _magi_version(),
        "restorable": False,
        "includes_l0": bool(include_l0),
        "source_counts": dict(snapshot.counts),
        "files": {},
        "record_contract": {
            "contract_version": _RECORD_SCHEMA_VERSION,
            "encoding": "UTF-8 JSON Lines",
            "record_type_field": "record_type",
            "schema_version_field": "schema_version",
            "layer_field": "layer",
            "timestamps": (
                "Numeric timestamp fields use Unix seconds; calendar date fields use "
                "ISO 8601 strings"
            ),
            "additional_fields": False,
        },
    }
    try:
        with (
            _open_private_exclusive(partial_path) as output_handle,
            zipfile.ZipFile(
                output_handle,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=6,
                allowZip64=True,
            ) as archive,
        ):
            export_files: dict[str, dict[str, object]] = {}
            referenced_assets: set[str] = set()
            database_paths = {
                "l1": _snapshot_file(snapshot, "databases/l1_events.db"),
                "memory": _snapshot_file(snapshot, "databases/memory.db"),
            }
            specs = (*_CURRENT_EXPORT_SPECS, *(_L0_EXPORT_SPECS if include_l0 else ()))
            for spec in specs:
                export_files[spec.archive_path] = _write_spec_jsonl(
                    archive,
                    database_paths[spec.database],
                    spec,
                    spec.archive_path,
                    referenced_assets,
                )
            for item in snapshot.files:
                if item.purpose == "archive":
                    date = Path(item.archive_path).stem
                    for spec in _ARCHIVE_EXPORT_SPECS:
                        archive_path = spec.archive_path.format(date=date)
                        export_files[archive_path] = _write_spec_jsonl(
                            archive,
                            Path(item.source_path),
                            spec,
                            archive_path,
                            referenced_assets,
                        )
            for item in snapshot.files:
                if item.purpose == "manual_entry_asset" and item.archive_path in referenced_assets:
                    _write_asset(archive, item.archive_path, Path(item.source_path))
            manifest["files"] = export_files
            _write_text(
                archive,
                "schema.json",
                json.dumps(export_files, ensure_ascii=False, indent=2, sort_keys=True),
            )
            _write_text(archive, "README.txt", _export_readme(include_l0, export_files))
            _write_text(
                archive,
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            )
        partial_path.chmod(0o600)
        _fsync_file(partial_path)
        os.replace(partial_path, output_path)
        _fsync_directory(output_directory)
        return output_path, manifest
    except MemoryPortabilityError:
        partial_path.unlink(missing_ok=True)
        raise
    except (OSError, sqlite3.DatabaseError, zipfile.BadZipFile) as exc:
        partial_path.unlink(missing_ok=True)
        if _is_no_space_error(exc):
            raise MemoryPortabilityError(
                "insufficient_space",
                "The selected directory does not have enough free space.",
            ) from exc
        raise MemoryPortabilityError(
            "export_write_failed",
            "The readable memory export could not be created.",
            status_code=500,
        ) from exc


def _required_export_free_bytes(snapshot: SnapshotBundle) -> int:
    structured_bytes = 0
    asset_bytes = 0
    try:
        for item in snapshot.files:
            size_bytes = Path(item.source_path).stat().st_size
            if item.purpose == "manual_entry_asset":
                asset_bytes += size_bytes
            else:
                structured_bytes += size_bytes
    except OSError as exc:
        raise MemoryPortabilityError(
            "export_write_failed",
            "Readable export space requirements could not be determined.",
            status_code=500,
        ) from exc
    return (
        structured_bytes * _STRUCTURED_EXPORT_EXPANSION_FACTOR
        + asset_bytes
        + _EXPORT_FIXED_OVERHEAD_BYTES
    )


def _is_no_space_error(exc: BaseException) -> bool:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, OSError) and current.errno == errno.ENOSPC:
            return True
        if isinstance(current, sqlite3.Error) and getattr(
            current, "sqlite_errorcode", None
        ) == getattr(sqlite3, "SQLITE_FULL", 13):
            return True
        current = current.__cause__ or current.__context__
    return False


def _write_spec_jsonl(
    archive: zipfile.ZipFile,
    database_path: Path,
    spec: _ExportSpec,
    archive_path: str,
    referenced_assets: set[str],
) -> dict[str, object]:
    identifiers = {spec.table, *spec.order_by, *(field.source for field in spec.fields)}
    if any(re.fullmatch(r"[a-z0-9_]+", identifier) is None for identifier in identifiers):
        raise ValueError("Unsafe SQLite identifier in readable export contract")
    with sqlite3.connect(f"file:{database_path}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        table_row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (spec.table,),
        ).fetchone()
        if table_row is None:
            if spec.table_optional:
                _write_text(archive, archive_path, "")
                return _file_contract(spec, record_count=0)
            raise _schema_mismatch(spec, [spec.table])
        available_columns = {
            str(row[1]) for row in connection.execute(f'PRAGMA table_info("{spec.table}")')
        }
        source_columns = tuple(dict.fromkeys(field.source for field in spec.fields))
        required_columns = {*source_columns, *spec.order_by}
        missing_columns = sorted(required_columns - available_columns)
        if missing_columns:
            raise _schema_mismatch(spec, missing_columns)
        select_list = ", ".join(f'"{column}"' for column in source_columns)
        order_by = ", ".join(f'"{column}"' for column in spec.order_by)
        cursor = connection.execute(
            f'SELECT {select_list} FROM "{spec.table}" '
            f'WHERE {spec.visibility_sql} ORDER BY {order_by}'
        )
        info = zipfile.ZipInfo(archive_path)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100600 << 16
        count = 0
        with archive.open(info, "w", force_zip64=True) as handle:
            for row in cursor:
                try:
                    payload = {
                        "record_type": spec.record_type,
                        "schema_version": _RECORD_SCHEMA_VERSION,
                        "layer": spec.layer,
                        **{field.name: field.read(row) for field in spec.fields},
                    }
                except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
                    raise MemoryPortabilityError(
                        "export_data_invalid",
                        f"Stored memory data does not match readable export {spec.record_type} v1.",
                        status_code=500,
                    ) from exc
                handle.write(
                    (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
                )
                for name in ("asset_references", "user_cover_asset_ref", "representative_asset_ref"):
                    value = payload.get(name)
                    for reference in value if isinstance(value, list) else [value]:
                        if not isinstance(reference, str):
                            continue
                        match = re.fullmatch(
                            r"manual-entry-asset://([0-9a-f]{64}\.(?:gif|jpg|png|webp))",
                            reference,
                        )
                        if match is not None:
                            filename = match.group(1)
                            referenced_assets.add(f"assets/manual_entries/{filename[:2]}/{filename}")
                count += 1
    return _file_contract(spec, record_count=count)


def _file_contract(spec: _ExportSpec, *, record_count: int) -> dict[str, object]:
    return {
        "record_count": record_count,
        "record_type": spec.record_type,
        "schema_version": _RECORD_SCHEMA_VERSION,
        "layer": spec.layer,
        "description": spec.description,
        "fields": [
            *_COMMON_FIELDS,
            *({"name": field.name, "type": field.value_type} for field in spec.fields),
        ],
    }


def _schema_mismatch(spec: _ExportSpec, missing: list[str]) -> MemoryPortabilityError:
    return MemoryPortabilityError(
        "export_schema_mismatch",
        f"Readable export {spec.record_type} v1 is missing required storage fields: "
        f"{', '.join(missing)}.",
        status_code=500,
    )


def _snapshot_file(snapshot: SnapshotBundle, archive_path: str) -> Path:
    for item in snapshot.files:
        if item.archive_path == archive_path:
            return Path(item.source_path)
    raise MemoryPortabilityError(
        "snapshot_incomplete",
        "The consistent snapshot is missing a required database.",
        status_code=500,
    )


def _write_asset(archive: zipfile.ZipFile, archive_path: str, source: Path) -> None:
    info = zipfile.ZipInfo(archive_path)
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = 0o100600 << 16
    with source.open("rb") as input_handle, archive.open(info, "w", force_zip64=True) as handle:
        shutil.copyfileobj(input_handle, handle, length=1024 * 1024)


def _write_text(archive: zipfile.ZipFile, archive_path: str, content: str) -> None:
    info = zipfile.ZipInfo(archive_path)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100600 << 16
    archive.writestr(info, content.encode("utf-8"))


def _export_readme(
    include_l0: bool,
    export_files: dict[str, dict[str, object]],
) -> str:
    l0_note = (
        "L0 short-term attention is included because it was explicitly requested."
        if include_l0
        else "L0 short-term attention is omitted by default because it is disposable chat context."
    )
    field_guide = []
    for path, contract in sorted(export_files.items()):
        fields = contract.get("fields")
        if not isinstance(fields, list):
            raise ValueError("Readable export field contract must be a list")
        field_names = ", ".join(
            str(field["name"]) for field in fields if isinstance(field, dict) and "name" in field
        )
        field_guide.append(f"- {path} ({contract['record_type']} v1): {field_names}")
    return (
        "Magi readable memory export\n\n"
        "This is a stable, version-1 DTO export for reading and data portability. "
        "Each JSONL file contains one JSON object per line, and schema.json is the "
        "machine-readable source of truth for the exact fields. Fields not listed there "
        "are not part of the contract; internal SQLite columns are intentionally omitted.\n\n"
        "This export cannot be restored into Magi. Use a .magibackup file for restore. "
        "Vector and full-text indexes, worker leases, background jobs, chat transcripts, "
        "chat attachments, runtime logs, product tasks, models, plugins, credentials, "
        "configuration, and persona state are not included. Original chat evidence "
        "referenced by an L1 event may not exist on another device.\n\n"
        "Deleted memories and their owned source payloads or procedure traces are omitted. "
        "Content-free forgetting markers remain in the governance files.\n\n"
        f"{l0_note}\n\n"
        "JSONL field guide\n" + "\n".join(field_guide) + "\n"
    )


__all__ = ["build_readable_export"]
