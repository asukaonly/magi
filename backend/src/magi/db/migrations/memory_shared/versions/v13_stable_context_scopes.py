"""Replace free-text correction scopes with stable local context identities.

Revision ID: v13_stable_context_scopes
Revises: v12_scheduled_correction_transitions
"""

import hashlib
import json
import re
import time
import unicodedata
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from alembic import op

revision = "v13_stable_context_scopes"
down_revision = "v12_scheduled_correction_transitions"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memory_context_catalog (
    context_id TEXT PRIMARY KEY,
    dimension TEXT NOT NULL CHECK(
        dimension IN ('project', 'activity', 'place', 'person', 'time')
    ),
    label TEXT NOT NULL,
    display_label TEXT,
    source_kind TEXT NOT NULL CHECK(
        source_kind IN ('workspace', 'built_in', 'legacy_custom')
    ),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_context_aliases (
    context_id TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    alias TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY(context_id, normalized_alias),
    FOREIGN KEY(context_id) REFERENCES memory_context_catalog(context_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS memory_context_bindings (
    context_id TEXT NOT NULL,
    binding_kind TEXT NOT NULL CHECK(binding_kind = 'workspace'),
    binding_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY(binding_kind, binding_id),
    UNIQUE(context_id, binding_kind),
    FOREIGN KEY(context_id) REFERENCES memory_context_catalog(context_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_memory_context_catalog_product_options
    ON memory_context_catalog(dimension, source_kind, is_active, label);
CREATE INDEX IF NOT EXISTS idx_memory_context_alias_lookup
    ON memory_context_aliases(normalized_alias, context_id);
"""

_WHITESPACE_RE = re.compile(r"\s+")
_LEGACY_DIMENSIONS = {"project", "activity", "place", "person"}
_CODING_ALIASES = (
    "coding",
    "code",
    "programming",
    "写代码",
    "编码",
    "编程",
    "开发",
)
_AUTHORITATIVE_SOURCE_DOMAINS = {"user_authored", "settings_profile"}
_RETRIEVABLE_VALIDATION_RANK = {
    "tentative": 1,
    "corroborated": 2,
    "stable": 3,
}
_INVALID_ASSERTION_STATES = {
    "archived",
    "contradicted",
    "expired",
    "invalidated",
    "shadow",
    "superseded",
    "user_rejected",
}


def _normalized_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return _WHITESPACE_RE.sub(" ", text).casefold()


def _identity_digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _fingerprint_digest(*parts: Any) -> str:
    payload = "\x1f".join(_normalized_text(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _context_id(dimension: str, source_kind: str, canonical_value: str) -> str:
    return f"ctx_{dimension}_" f"{_identity_digest(dimension, source_kind, canonical_value)}"


def _coding_context_id() -> str:
    return _context_id("activity", "built_in", "coding")


def _canonical_claim_value(value: Any) -> str:
    if isinstance(value, (Mapping, Sequence)) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    if value is None:
        return ""
    text = str(value).strip()
    if text and text[0] in '[{"':
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
        else:
            if isinstance(parsed, (dict, list)):
                return json.dumps(
                    parsed,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
    return _normalized_text(text)


def _scope_json(scope: Mapping[str, Any] | None) -> str:
    payload = dict(scope or {})
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _scope_key(scope: Mapping[str, Any] | None) -> str:
    canonical = _scope_json(scope)
    if canonical == "{}":
        return "global"
    return f"scope_{_fingerprint_digest(canonical)}"


def _assertion_fingerprint(
    *,
    slot_key: str,
    trait_value: Any,
    scope_key: str,
) -> str:
    return "assertion_claim_" + _fingerprint_digest(
        slot_key,
        scope_key,
        _canonical_claim_value(trait_value),
    )


def _edge_fingerprint(payload: Mapping[str, Any], scope_key: str) -> str:
    return "edge_claim_" + _fingerprint_digest(
        payload.get("slot_key") or "",
        payload.get("subject_id") or "",
        payload.get("predicate") or "",
        payload.get("object_id") or "",
        scope_key,
    )


def _relationship_triple_id(
    *,
    subject_id: str,
    predicate: str,
    object_id: str,
    scope_key: str,
) -> str:
    triple_key = f"{subject_id}:{predicate}:{object_id}"
    if scope_key != "global":
        triple_key = f"{triple_key}:{scope_key}"
    return f"triple_{uuid.uuid5(uuid.NAMESPACE_DNS, triple_key)}"


def _row_dicts(connection: Any, query: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cursor = connection.execute(query, args)
    columns = [str(item[0]) for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _seed_builtin_contexts(connection: Any) -> None:
    context_id = _coding_context_id()
    connection.execute(
        """
        INSERT OR IGNORE INTO memory_context_catalog(
            context_id, dimension, label, source_kind, is_active,
            created_at, updated_at
        ) VALUES (?, 'activity', 'Coding', 'built_in', 1, 0, 0)
        """,
        (context_id,),
    )
    for alias in _CODING_ALIASES:
        connection.execute(
            """
            INSERT OR IGNORE INTO memory_context_aliases(
                context_id, normalized_alias, alias, created_at
            ) VALUES (?, ?, ?, 0)
            """,
            (context_id, _normalized_text(alias), alias),
        )


def _display_value(value: Any) -> tuple[str, str]:
    if isinstance(value, str):
        display = value.strip()
    else:
        display = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    normalized = _normalized_text(display)
    if normalized:
        return display, normalized
    return "(empty legacy context)", "__empty_legacy_context__"


def _ensure_custom_context(
    connection: Any,
    *,
    dimension: str,
    value: Any,
) -> str:
    display, normalized = _display_value(value)
    context_id = _context_id(dimension, "legacy_custom", normalized)
    connection.execute(
        """
        INSERT OR IGNORE INTO memory_context_catalog(
            context_id, dimension, label, source_kind, is_active,
            created_at, updated_at
        ) VALUES (?, ?, ?, 'legacy_custom', 1, 0, 0)
        """,
        (context_id, dimension, display),
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO memory_context_aliases(
            context_id, normalized_alias, alias, created_at
        ) VALUES (?, ?, ?, 0)
        """,
        (context_id, normalized, display),
    )
    return context_id


def _ensure_existing_identity(
    connection: Any,
    *,
    dimension: str,
    context_id: str,
) -> None:
    connection.execute(
        """
        INSERT OR IGNORE INTO memory_context_catalog(
            context_id, dimension, label, source_kind, is_active,
            created_at, updated_at
        ) VALUES (?, ?, ?, 'legacy_custom', 1, 0, 0)
        """,
        (context_id, dimension, ""),
    )


def _legacy_condition(
    connection: Any,
    *,
    dimension: str,
    value: Any,
) -> dict[str, str]:
    if dimension == "activity" and _normalized_text(value) in {
        _normalized_text(alias) for alias in _CODING_ALIASES
    }:
        context_id = _coding_context_id()
    else:
        context_id = _ensure_custom_context(
            connection,
            dimension=dimension,
            value=value,
        )
    return {"dimension": dimension, "context_id": context_id}


def _quarantined_scope(
    connection: Any,
    raw_scope: Any,
    *,
    reason: str,
    quarantine_salt: str = "",
) -> dict[str, Any]:
    """Keep malformed scopes isolated in one runtime-readable identity."""
    _, normalized = _display_value(
        {
            "legacy_scope_key": quarantine_salt,
            "reason": reason,
            "value": raw_scope,
        }
    )
    context_id = _context_id("time", "quarantined_scope", normalized)
    connection.execute(
        """
        INSERT OR IGNORE INTO memory_context_catalog(
            context_id, dimension, label, source_kind, is_active,
            created_at, updated_at
        ) VALUES (?, 'time', '', 'legacy_custom', 1, 0, 0)
        """,
        (context_id,),
    )
    return {"all_of": [{"dimension": "time", "context_id": context_id}]}


def _convert_scope(
    connection: Any,
    raw_scope: Any,
    *,
    quarantine_salt: str = "",
) -> dict[str, Any]:
    if raw_scope in (None, {}):
        return {}
    if not isinstance(raw_scope, Mapping):
        return _quarantined_scope(
            connection,
            raw_scope,
            reason="invalid_scope_type",
            quarantine_salt=quarantine_salt,
        )

    if "all_of" in raw_scope:
        raw_conditions = raw_scope.get("all_of")
        if (
            set(raw_scope) != {"all_of"}
            or not isinstance(raw_conditions, list)
            or not raw_conditions
            or len(raw_conditions) > 5
        ):
            return _quarantined_scope(
                connection,
                dict(raw_scope),
                reason="invalid_all_of",
                quarantine_salt=quarantine_salt,
            )
        conditions: list[dict[str, str]] = []
        seen_dimensions: set[str] = set()
        for item in raw_conditions:
            if not isinstance(item, Mapping) or set(item) != {
                "dimension",
                "context_id",
            }:
                return _quarantined_scope(
                    connection,
                    dict(raw_scope),
                    reason="invalid_all_of_condition",
                    quarantine_salt=quarantine_salt,
                )
            dimension = str(item.get("dimension") or "").strip()
            context_id = str(item.get("context_id") or "").strip()
            if (
                dimension not in {"project", "activity", "place", "person", "time"}
                or dimension in seen_dimensions
                or not re.fullmatch(rf"ctx_{dimension}_[0-9a-f]{{64}}", context_id)
            ):
                return _quarantined_scope(
                    connection,
                    dict(raw_scope),
                    reason="invalid_all_of_identity",
                    quarantine_salt=quarantine_salt,
                )
            seen_dimensions.add(dimension)
            _ensure_existing_identity(
                connection,
                dimension=dimension,
                context_id=context_id,
            )
            conditions.append({"dimension": dimension, "context_id": context_id})
        return {
            "all_of": sorted(
                conditions,
                key=lambda item: (item["dimension"], item["context_id"]),
            )
        }

    for dimension in _LEGACY_DIMENSIONS:
        if dimension not in raw_scope:
            continue
        value = raw_scope[dimension]
        if not isinstance(value, str) or not _normalized_text(value):
            return _quarantined_scope(
                connection,
                dict(raw_scope),
                reason="invalid_legacy_dimension",
                quarantine_salt=quarantine_salt,
            )

    conditions = [
        _legacy_condition(connection, dimension=key, value=raw_scope[key])
        for key in sorted(_LEGACY_DIMENSIONS)
        if key in raw_scope
    ]
    residual = {
        str(key): value for key, value in raw_scope.items() if str(key) not in _LEGACY_DIMENSIONS
    }
    if residual:
        time_range = residual.get("time_range")
        if (
            set(residual) != {"time_range"}
            or not isinstance(time_range, Mapping)
            or not time_range
            or not set(str(key) for key in time_range).issubset({"start", "end"})
        ):
            return _quarantined_scope(
                connection,
                dict(raw_scope),
                reason="invalid_legacy_time_range",
                quarantine_salt=quarantine_salt,
            )
        conditions.append(
            _legacy_condition(
                connection,
                dimension="time",
                value=residual,
            )
        )
    if not conditions:
        return {}
    return {
        "all_of": sorted(
            conditions,
            key=lambda item: (item["dimension"], item["context_id"]),
        )
    }


def _convert_scope_json(
    connection: Any,
    raw_json: Any,
    *,
    quarantine_salt: str = "",
) -> dict[str, Any]:
    if raw_json is None:
        return {}
    try:
        decoded = json.loads(str(raw_json))
    except (TypeError, ValueError, json.JSONDecodeError):
        return _quarantined_scope(
            connection,
            str(raw_json),
            reason="invalid_json",
            quarantine_salt=quarantine_salt,
        )
    if decoded is None:
        return _quarantined_scope(
            connection,
            None,
            reason="json_null",
            quarantine_salt=quarantine_salt,
        )
    return _convert_scope(
        connection,
        decoded,
        quarantine_salt=quarantine_salt,
    )


def _migrate_assertions(connection: Any) -> dict[str, str]:
    prepared: list[tuple[dict[str, Any], dict[str, Any], str, str]] = []
    for row in _row_dicts(connection, "SELECT * FROM tom_trait_assertions"):
        scope = _convert_scope_json(
            connection,
            row.get("scope_json"),
            quarantine_salt=str(row.get("scope_key") or ""),
        )
        key = _scope_key(scope)
        fingerprint = _assertion_fingerprint(
            slot_key=str(row.get("slot_key") or ""),
            trait_value=row.get("trait_value"),
            scope_key=key,
        )
        prepared.append((row, scope, key, fingerprint))

    current_groups: dict[
        tuple[str, str],
        list[tuple[dict[str, Any], dict[str, Any], str, str]],
    ] = {}
    excluded_statuses = {
        "superseded",
        "archived",
        "expired",
        "user_rejected",
        "shadow",
    }
    for item in prepared:
        row, _, key, _ = item
        if str(row.get("status") or "active") in excluded_statuses:
            continue
        current_groups.setdefault((str(row.get("slot_key") or ""), key), []).append(item)

    collision_losers: dict[str, str] = {}
    for group in current_groups.values():
        if len(group) <= 1:
            continue
        winner = max(
            group,
            key=lambda item: (
                _assertion_is_retrievable(item[0]),
                _assertion_is_authoritative(item[0]),
                _assertion_validation_rank(item[0]),
                float(item[0].get("updated_at") or 0.0),
                float(item[0].get("created_at") or 0.0),
                str(item[0].get("assertion_id") or ""),
            ),
        )
        winner_row = winner[0]
        winner_cutoff = float(
            winner_row.get("updated_at")
            or winner_row.get("valid_from")
            or winner_row.get("created_at")
            or 0.0
        )
        for loser in group:
            loser_row = loser[0]
            if loser_row["assertion_id"] == winner_row["assertion_id"]:
                continue
            cutoff = max(
                winner_cutoff,
                float(loser_row.get("valid_from") or 0.0),
                float(loser_row.get("created_at") or 0.0),
            )
            connection.execute(
                """
                UPDATE tom_trait_assertions
                SET status = 'superseded', superseded_by = ?,
                    superseded_at = COALESCE(superseded_at, ?),
                    valid_to = COALESCE(valid_to, ?)
                WHERE assertion_id = ?
                """,
                (
                    winner_row["assertion_id"],
                    cutoff,
                    cutoff,
                    loser_row["assertion_id"],
                ),
            )
            collision_losers[str(loser_row["assertion_id"])] = str(winner_row["assertion_id"])

    for row, scope, key, fingerprint in prepared:
        connection.execute(
            """
            UPDATE tom_trait_assertions
            SET scope_json = ?, scope_key = ?, claim_fingerprint = ?
            WHERE assertion_id = ?
            """,
            (_scope_json(scope), key, fingerprint, row["assertion_id"]),
        )
    return collision_losers


def _assertion_is_authoritative(row: Mapping[str, Any]) -> bool:
    if _normalized_text(row.get("user_feedback")) == "confirmed":
        return True
    return _normalized_text(row.get("source_domain")) in _AUTHORITATIVE_SOURCE_DOMAINS


def _assertion_validation_rank(row: Mapping[str, Any]) -> int:
    return _RETRIEVABLE_VALIDATION_RANK.get(
        _normalized_text(row.get("validation_state")),
        0,
    )


def _assertion_is_retrievable(row: Mapping[str, Any]) -> bool:
    status = _normalized_text(row.get("status") or "active")
    validation_state = _normalized_text(row.get("validation_state"))
    if status in _INVALID_ASSERTION_STATES:
        return False
    if validation_state in _INVALID_ASSERTION_STATES:
        return False
    return _assertion_validation_rank(row) > 0


_KNOWLEDGE_GRAPH_COLUMNS = (
    "triple_id",
    "subject_id",
    "subject_type",
    "predicate",
    "object_id",
    "object_type",
    "fact_kind",
    "confidence",
    "evidence_event_ids",
    "evidence_text",
    "natural_summary",
    "observation_count",
    "first_observed_at",
    "last_observed_at",
    "last_confirmed_at",
    "source_type",
    "extraction_method",
    "embedding_status",
    "embedding_profile_id",
    "last_embedded_at",
    "expires_at",
    "valid_from",
    "valid_to",
    "status",
    "status_reason",
    "deprecated_by",
    "deprecated_at",
    "created_at",
    "updated_at",
    "evidence_class",
    "slot_key",
    "claim_fingerprint",
    "authority_ref",
    "scope_key",
    "scope_json",
)

_KNOWLEDGE_GRAPH_V13_SQL = """
CREATE TABLE knowledge_graph_v13 (
    triple_id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object_id TEXT NOT NULL,
    object_type TEXT NOT NULL,
    fact_kind TEXT NOT NULL DEFAULT 'explicit_fact',
    confidence REAL NOT NULL DEFAULT 0.5,
    evidence_event_ids TEXT NOT NULL,
    evidence_text TEXT DEFAULT '',
    natural_summary TEXT DEFAULT '',
    observation_count INTEGER NOT NULL DEFAULT 1,
    first_observed_at REAL NOT NULL,
    last_observed_at REAL NOT NULL,
    last_confirmed_at REAL,
    source_type TEXT,
    extraction_method TEXT,
    embedding_status TEXT DEFAULT 'pending',
    embedding_profile_id TEXT,
    last_embedded_at REAL,
    expires_at REAL,
    valid_from REAL,
    valid_to REAL,
    status TEXT NOT NULL DEFAULT 'active',
    status_reason TEXT,
    deprecated_by TEXT,
    deprecated_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    evidence_class TEXT DEFAULT NULL,
    slot_key TEXT NOT NULL DEFAULT '',
    claim_fingerprint TEXT NOT NULL DEFAULT '',
    authority_ref TEXT,
    scope_key TEXT NOT NULL DEFAULT 'global',
    scope_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(subject_id, predicate, object_id, scope_key)
)
"""

_KNOWLEDGE_GRAPH_INDEX_SQL = (
    """
    CREATE INDEX idx_knowledge_graph_status_subject
    ON knowledge_graph(status, subject_id, updated_at DESC)
    """,
    """
    CREATE INDEX idx_knowledge_graph_status_object
    ON knowledge_graph(status, object_id, updated_at DESC)
    """,
    """
    CREATE INDEX idx_knowledge_graph_status_predicate
    ON knowledge_graph(status, predicate)
    """,
    """
    CREATE INDEX idx_knowledge_graph_embedding_profile
    ON knowledge_graph(embedding_profile_id)
    """,
    """
    CREATE INDEX idx_knowledge_graph_evidence_class
    ON knowledge_graph(evidence_class)
    WHERE evidence_class IS NOT NULL
    """,
    """
    CREATE INDEX idx_knowledge_graph_slot_scope_status
    ON knowledge_graph(slot_key, scope_key, status, updated_at DESC)
    """,
)


def _rebuild_knowledge_graph_for_scoped_identity(connection: Any) -> None:
    """Replace the legacy unscoped uniqueness constraint without losing columns."""
    columns = ", ".join(_KNOWLEDGE_GRAPH_COLUMNS)
    connection.execute("DROP TABLE IF EXISTS knowledge_graph_v13")
    connection.execute(_KNOWLEDGE_GRAPH_V13_SQL)
    connection.execute(
        f"INSERT INTO knowledge_graph_v13({columns}) " f"SELECT {columns} FROM knowledge_graph"
    )
    connection.execute("DROP TABLE knowledge_graph")
    connection.execute("ALTER TABLE knowledge_graph_v13 RENAME TO knowledge_graph")
    for statement in _KNOWLEDGE_GRAPH_INDEX_SQL:
        connection.execute(statement)


def schema_sql_for_fresh_database() -> str:
    """Return the complete v13 DDL for an empty release-baseline database."""
    columns = ", ".join(_KNOWLEDGE_GRAPH_COLUMNS)
    coding_context_id = _coding_context_id()
    alias_rows = ",\n".join(
        "(" + ", ".join(_sql_literal(value) for value in row) + ", 0)"
        for row in (
            (coding_context_id, _normalized_text(alias), alias) for alias in _CODING_ALIASES
        )
    )
    statements = [
        SCHEMA_SQL,
        f"""
        INSERT OR IGNORE INTO memory_context_catalog(
            context_id, dimension, label, source_kind, is_active,
            created_at, updated_at
        ) VALUES (
            {_sql_literal(coding_context_id)}, 'activity', 'Coding',
            'built_in', 1, 0, 0
        )
        """,
        f"""
        INSERT OR IGNORE INTO memory_context_aliases(
            context_id, normalized_alias, alias, created_at
        ) VALUES {alias_rows}
        """,
        "DROP TABLE IF EXISTS knowledge_graph_v13",
        _KNOWLEDGE_GRAPH_V13_SQL,
        (f"INSERT INTO knowledge_graph_v13({columns}) " f"SELECT {columns} FROM knowledge_graph"),
        "DROP TABLE knowledge_graph",
        "ALTER TABLE knowledge_graph_v13 RENAME TO knowledge_graph",
        *_KNOWLEDGE_GRAPH_INDEX_SQL,
    ]
    return ";\n".join(statement.strip().rstrip(";") for statement in statements) + ";\n"


def _sql_literal(value: Any) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _scoped_triple_id(
    row: Mapping[str, Any],
    *,
    legacy_triple_id: str,
    scope_key_value: str,
) -> str:
    if scope_key_value == "global":
        return legacy_triple_id
    return _relationship_triple_id(
        subject_id=str(row.get("subject_id") or ""),
        predicate=str(row.get("predicate") or ""),
        object_id=str(row.get("object_id") or ""),
        scope_key=scope_key_value,
    )


def _decode_json_object(
    raw: Any,
    *,
    correction_id: str,
    field_name: str,
) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        decoded = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Cannot migrate correction {correction_id}: {field_name} is invalid JSON"
        ) from exc
    if not isinstance(decoded, Mapping):
        raise ValueError(
            f"Cannot migrate correction {correction_id}: {field_name} must be a JSON object"
        )
    return dict(decoded)


def _payload_scope(
    connection: Any,
    payload: Mapping[str, Any],
    *,
    correction_id: str,
    field_name: str,
) -> dict[str, Any]:
    quarantine_salt = str(payload.get("scope_key") or "") or (
        f"correction:{correction_id}:{field_name}"
    )
    if "scope_json" in payload:
        raw_scope_json = payload.get("scope_json")
        if raw_scope_json is None:
            raise ValueError(
                f"Cannot migrate correction {correction_id}: "
                f"{field_name}.scope_json cannot be null"
            )
        return _convert_scope_json(
            connection,
            raw_scope_json,
            quarantine_salt=quarantine_salt,
        )
    if "scope" not in payload or payload.get("scope") is None:
        return {}
    return _convert_scope(
        connection,
        payload.get("scope"),
        quarantine_salt=quarantine_salt,
    )


def _validate_payload_identity(
    payload: Mapping[str, Any],
    *,
    correction_id: str,
    field_name: str,
    target_kind: str,
) -> None:
    required_fields = (
        ("trait_value",)
        if target_kind == "assertion" and field_name == "before_json"
        else ("value",)
        if target_kind == "assertion"
        else ("subject_id", "predicate", "object_id")
    )
    missing = [
        field
        for field in required_fields
        if field not in payload or not str(payload.get(field) or "").strip()
    ]
    if missing:
        fields = ", ".join(missing)
        raise ValueError(
            f"Cannot migrate correction {correction_id}: "
            f"{field_name} is missing identity fields: {fields}"
        )


def _rewrite_payload_scope(
    connection: Any,
    payload: dict[str, Any],
    *,
    correction_id: str,
    field_name: str,
    target_kind: str,
    slot_key: str,
    scope_override: Mapping[str, Any] | None = None,
    legacy_triple_id: str = "",
) -> tuple[dict[str, Any], dict[str, Any], str, str, str | None]:
    _validate_payload_identity(
        payload,
        correction_id=correction_id,
        field_name=field_name,
        target_kind=target_kind,
    )
    scope = (
        dict(scope_override)
        if scope_override is not None
        else _payload_scope(
            connection,
            payload,
            correction_id=correction_id,
            field_name=field_name,
        )
    )
    key = _scope_key(scope)
    if "scope_json" in payload:
        payload["scope_json"] = _scope_json(scope)
        payload["scope_key"] = key
    if "scope" in payload:
        payload["scope"] = scope
    if "scope_key" in payload:
        payload["scope_key"] = key

    triple_id: str | None = None
    if target_kind == "assertion":
        value = payload.get("trait_value", payload.get("value"))
        fingerprint = _assertion_fingerprint(
            slot_key=slot_key,
            trait_value=value,
            scope_key=key,
        )
    else:
        edge_payload = dict(payload)
        edge_payload["slot_key"] = edge_payload.get("slot_key") or slot_key
        fingerprint = _edge_fingerprint(edge_payload, key)
        fallback_id = str(payload.get("triple_id") or legacy_triple_id or "")
        if not fallback_id:
            fallback_id = _relationship_triple_id(
                subject_id=str(payload.get("subject_id") or ""),
                predicate=str(payload.get("predicate") or ""),
                object_id=str(payload.get("object_id") or ""),
                scope_key="global",
            )
        triple_id = _scoped_triple_id(
            payload,
            legacy_triple_id=fallback_id,
            scope_key_value=key,
        )
        payload["triple_id"] = triple_id
    if "claim_fingerprint" in payload:
        payload["claim_fingerprint"] = fingerprint
    return payload, scope, key, fingerprint, triple_id


@dataclass(frozen=True, slots=True)
class _CorrectionPlan:
    correction: dict[str, Any]
    before: dict[str, Any]
    before_scope: dict[str, Any]
    before_scope_key: str
    before_fingerprint: str
    before_triple_id: str | None
    replacement: dict[str, Any] | None
    replacement_scope: dict[str, Any] | None
    replacement_scope_key: str | None
    replacement_fingerprint: str | None
    replacement_triple_id: str | None
    old_target_id: str
    old_replacement_id: str
    correction_scope_json: str | None
    inherited_replacement_scope: bool


def _preflight_correction_snapshots(connection: Any) -> None:
    """Reject incomplete correction history before any durable v13 data change."""
    for correction in _row_dicts(connection, "SELECT * FROM memory_corrections"):
        correction_id = str(correction["correction_id"])
        target_kind = str(correction["target_kind"])
        before = _decode_json_object(
            correction.get("before_json"),
            correction_id=correction_id,
            field_name="before_json",
        )
        if before is None:
            raise ValueError(f"Cannot migrate correction {correction_id}: before_json is required")
        _validate_payload_identity(
            before,
            correction_id=correction_id,
            field_name="before_json",
            target_kind=target_kind,
        )
        if "scope_json" in before and before.get("scope_json") is None:
            raise ValueError(
                f"Cannot migrate correction {correction_id}: "
                "before_json.scope_json cannot be null"
            )
        replacement = _decode_json_object(
            correction.get("replacement_json"),
            correction_id=correction_id,
            field_name="replacement_json",
        )
        if replacement is None:
            continue
        _validate_payload_identity(
            replacement,
            correction_id=correction_id,
            field_name="replacement_json",
            target_kind=target_kind,
        )
        if "scope_json" in replacement and replacement.get("scope_json") is None:
            raise ValueError(
                f"Cannot migrate correction {correction_id}: "
                "replacement_json.scope_json cannot be null"
            )


def _prepare_correction_plans(connection: Any) -> dict[str, _CorrectionPlan]:
    plans: dict[str, _CorrectionPlan] = {}
    corrections = _row_dicts(connection, "SELECT * FROM memory_corrections")
    for correction in corrections:
        correction_id = str(correction["correction_id"])
        target_kind = str(correction["target_kind"])
        slot_key = str(correction.get("slot_key") or "")
        before = _decode_json_object(
            correction.get("before_json"),
            correction_id=correction_id,
            field_name="before_json",
        )
        if before is None:
            raise ValueError(f"Cannot migrate correction {correction_id}: before_json is required")
        before, before_scope, before_scope_key, before_fingerprint, before_triple_id = (
            _rewrite_payload_scope(
                connection,
                before,
                correction_id=correction_id,
                field_name="before_json",
                target_kind=target_kind,
                slot_key=slot_key,
                legacy_triple_id=str(correction.get("target_id") or ""),
            )
        )

        raw_replacement = _decode_json_object(
            correction.get("replacement_json"),
            correction_id=correction_id,
            field_name="replacement_json",
        )
        old_replacement_id = str(correction.get("replacement_target_id") or "")
        if not old_replacement_id and raw_replacement is not None:
            old_replacement_id = str(raw_replacement.get("triple_id") or "")
        replacement = raw_replacement
        replacement_scope: dict[str, Any] | None = None
        replacement_scope_key: str | None = None
        replacement_fingerprint: str | None = None
        replacement_triple_id: str | None = None
        inherited_replacement_scope = bool(
            replacement is not None
            and str(correction.get("correction_kind") or "") != "scope_refinement"
        )
        if replacement is not None:
            (
                replacement,
                replacement_scope,
                replacement_scope_key,
                replacement_fingerprint,
                replacement_triple_id,
            ) = _rewrite_payload_scope(
                connection,
                replacement,
                correction_id=correction_id,
                field_name="replacement_json",
                target_kind=target_kind,
                slot_key=str(replacement.get("slot_key") or slot_key),
                scope_override=before_scope if inherited_replacement_scope else None,
                legacy_triple_id=old_replacement_id,
            )

        correction_kind = str(correction.get("correction_kind") or "")
        explicit_correction_scope: dict[str, Any] = {}
        if correction_kind == "scope_refinement" and correction.get("scope_json") is not None:
            explicit_correction_scope = _convert_scope_json(
                connection,
                correction["scope_json"],
                quarantine_salt=(
                    f"correction:{correction_id}:" f"{correction.get('target_id') or ''}"
                ),
            )
        effective_correction_scope = (
            (explicit_correction_scope or replacement_scope or before_scope)
            if correction_kind == "scope_refinement"
            else before_scope
        )
        correction_scope_json = (
            _scope_json(effective_correction_scope) if effective_correction_scope else None
        )
        plans[correction_id] = _CorrectionPlan(
            correction=correction,
            before=before,
            before_scope=before_scope,
            before_scope_key=before_scope_key,
            before_fingerprint=before_fingerprint,
            before_triple_id=before_triple_id,
            replacement=replacement,
            replacement_scope=replacement_scope,
            replacement_scope_key=replacement_scope_key,
            replacement_fingerprint=replacement_fingerprint,
            replacement_triple_id=replacement_triple_id,
            old_target_id=str(correction.get("target_id") or ""),
            old_replacement_id=old_replacement_id,
            correction_scope_json=correction_scope_json,
            inherited_replacement_scope=inherited_replacement_scope,
        )
    return plans


def _rewrite_reference_value(value: Any, id_map: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        replacement = id_map.get(value)
        if replacement is not None:
            return replacement
        for prefix in ("edge:", "relationship:"):
            if value.startswith(prefix):
                replacement = id_map.get(value[len(prefix) :])
                if replacement is not None:
                    return f"{prefix}{replacement}"
        return value
    if isinstance(value, list):
        return [_rewrite_reference_value(item, id_map) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _rewrite_reference_value(item, id_map) for key, item in value.items()}
    return value


def _rewrite_correction_payload_references(
    payload: dict[str, Any],
    id_map: Mapping[str, str],
) -> dict[str, Any]:
    triple_id = payload.get("triple_id")
    rewritten = _rewrite_reference_value(payload, id_map)
    assert isinstance(rewritten, dict)
    if triple_id is not None:
        rewritten["triple_id"] = triple_id
    return rewritten


def _migrate_corrections_and_rules(
    connection: Any,
    plans: Mapping[str, _CorrectionPlan],
    id_map: Mapping[str, str],
) -> None:
    for correction_id, plan in plans.items():
        before = _rewrite_correction_payload_references(plan.before, id_map)
        replacement = (
            _rewrite_correction_payload_references(plan.replacement, id_map)
            if plan.replacement is not None
            else None
        )
        if plan.before_triple_id is not None:
            before["triple_id"] = plan.before_triple_id
        if replacement is not None and plan.replacement_triple_id is not None:
            replacement["triple_id"] = plan.replacement_triple_id

        connection.execute(
            """
            UPDATE memory_corrections
            SET target_id = ?, replacement_target_id = ?, before_json = ?,
                replacement_json = ?, scope_json = ?, claim_fingerprint = ?
            WHERE correction_id = ?
            """,
            (
                plan.before_triple_id or plan.old_target_id,
                (
                    (plan.replacement_triple_id or plan.old_replacement_id or None)
                    if plan.replacement is not None
                    else None
                ),
                json.dumps(
                    before,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                (
                    json.dumps(
                        replacement,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    if replacement is not None
                    else None
                ),
                plan.correction_scope_json,
                plan.before_fingerprint,
                correction_id,
            ),
        )

        for rule in _row_dicts(
            connection,
            "SELECT * FROM memory_correction_rules WHERE correction_id = ?",
            (correction_id,),
        ):
            rule_kind = str(rule["rule_kind"])
            fingerprint = plan.before_fingerprint
            key = plan.before_scope_key
            if rule_kind == "authoritative_slot" and plan.replacement_fingerprint is not None:
                fingerprint = plan.replacement_fingerprint
                key = plan.replacement_scope_key or "global"
            elif rule_kind == "scope_only":
                key = plan.replacement_scope_key or plan.before_scope_key
            connection.execute(
                """
                UPDATE memory_correction_rules
                SET claim_fingerprint = ?, scope_key = ?
                WHERE rule_id = ?
                """,
                (fingerprint, key, rule["rule_id"]),
            )


@dataclass(frozen=True, slots=True)
class _PreparedEdge:
    row: dict[str, Any]
    scope: dict[str, Any]
    scope_key: str
    claim_fingerprint: str
    new_triple_id: str


@dataclass(frozen=True, slots=True)
class _PreparedEdgeVersion:
    row: dict[str, Any]
    scope: dict[str, Any]
    scope_key: str
    claim_fingerprint: str
    new_triple_id: str


def _current_edge_scope(
    connection: Any,
    row: Mapping[str, Any],
    plans: Mapping[str, _CorrectionPlan],
) -> dict[str, Any]:
    scope = _convert_scope_json(
        connection,
        row.get("scope_json"),
        quarantine_salt=str(row.get("scope_key") or ""),
    )
    authority_ref = str(row.get("authority_ref") or "")
    if not authority_ref.startswith("correction:"):
        return scope
    plan = plans.get(authority_ref.split(":", 1)[1])
    if (
        plan is None
        or plan.replacement_scope is None
        or str(row.get("triple_id") or "") != plan.old_replacement_id
    ):
        return scope
    return plan.replacement_scope


def _version_edge_scope(
    connection: Any,
    row: Mapping[str, Any],
    plans: Mapping[str, _CorrectionPlan],
) -> dict[str, Any]:
    scope = _convert_scope_json(
        connection,
        row.get("scope_json"),
        quarantine_salt=str(row.get("scope_key") or ""),
    )
    correction_id = str(row.get("correction_id") or "")
    plan = plans.get(correction_id)
    if (
        plan is None
        or not plan.inherited_replacement_scope
        or plan.replacement_scope is None
        or str(row.get("triple_id") or "") != plan.old_replacement_id
    ):
        return scope
    return plan.replacement_scope


def _prepare_edges(
    connection: Any,
    plans: Mapping[str, _CorrectionPlan],
) -> list[_PreparedEdge]:
    prepared: list[_PreparedEdge] = []
    for row in _row_dicts(connection, "SELECT * FROM knowledge_graph"):
        scope = _current_edge_scope(connection, row, plans)
        key = _scope_key(scope)
        prepared.append(
            _PreparedEdge(
                row=row,
                scope=scope,
                scope_key=key,
                claim_fingerprint=_edge_fingerprint(row, key),
                new_triple_id=_scoped_triple_id(
                    row,
                    legacy_triple_id=str(row["triple_id"]),
                    scope_key_value=key,
                ),
            )
        )
    final_ids = [item.new_triple_id for item in prepared]
    if len(final_ids) != len(set(final_ids)):
        raise ValueError("Cannot migrate relationships: scoped triple ids collide")
    return prepared


def _prepare_edge_versions(
    connection: Any,
    plans: Mapping[str, _CorrectionPlan],
) -> list[_PreparedEdgeVersion]:
    prepared: list[_PreparedEdgeVersion] = []
    for row in _row_dicts(connection, "SELECT * FROM knowledge_graph_versions"):
        scope = _version_edge_scope(connection, row, plans)
        key = _scope_key(scope)
        prepared.append(
            _PreparedEdgeVersion(
                row=row,
                scope=scope,
                scope_key=key,
                claim_fingerprint=_edge_fingerprint(row, key),
                new_triple_id=_scoped_triple_id(
                    row,
                    legacy_triple_id=str(row["triple_id"]),
                    scope_key_value=key,
                ),
            )
        )
    return prepared


def _apply_edge_identity_migration(
    connection: Any,
    prepared: Sequence[_PreparedEdge],
) -> dict[str, str]:
    id_map = {str(item.row["triple_id"]): item.new_triple_id for item in prepared}
    temporary_ids: dict[str, str] = {}
    for item in prepared:
        old_id = str(item.row["triple_id"])
        if old_id == item.new_triple_id:
            connection.execute(
                """
                UPDATE knowledge_graph
                SET scope_json = ?, scope_key = ?, claim_fingerprint = ?
                WHERE triple_id = ?
                """,
                (
                    _scope_json(item.scope),
                    item.scope_key,
                    item.claim_fingerprint,
                    old_id,
                ),
            )
            continue
        temporary_id = f"__v13_edge_{_identity_digest(old_id, item.new_triple_id)}"
        temporary_ids[old_id] = temporary_id
        connection.execute(
            """
            UPDATE knowledge_graph
            SET triple_id = ?, scope_json = ?, scope_key = ?,
                claim_fingerprint = ?, embedding_status = 'pending',
                embedding_profile_id = NULL, last_embedded_at = NULL
            WHERE triple_id = ?
            """,
            (
                temporary_id,
                _scope_json(item.scope),
                item.scope_key,
                item.claim_fingerprint,
                old_id,
            ),
        )
    for old_id, temporary_id in temporary_ids.items():
        connection.execute(
            "UPDATE knowledge_graph SET triple_id = ? WHERE triple_id = ?",
            (id_map[old_id], temporary_id),
        )
    for item in prepared:
        deprecated_by = item.row.get("deprecated_by")
        authority_ref = item.row.get("authority_ref")
        connection.execute(
            """
            UPDATE knowledge_graph
            SET deprecated_by = ?, authority_ref = ?
            WHERE triple_id = ?
            """,
            (
                id_map.get(str(deprecated_by), deprecated_by)
                if deprecated_by is not None
                else None,
                id_map.get(str(authority_ref), authority_ref)
                if authority_ref is not None
                else None,
                item.new_triple_id,
            ),
        )
    return id_map


def _apply_edge_version_identity_migration(
    connection: Any,
    prepared: Sequence[_PreparedEdgeVersion],
    id_map: Mapping[str, str],
) -> None:
    by_triple: dict[str, list[_PreparedEdgeVersion]] = {}
    for item in prepared:
        authority_ref = item.row.get("authority_ref")
        connection.execute(
            """
            UPDATE knowledge_graph_versions
            SET triple_id = ?, scope_json = ?, scope_key = ?,
                claim_fingerprint = ?, authority_ref = ?
            WHERE version_id = ?
            """,
            (
                item.new_triple_id,
                _scope_json(item.scope),
                item.scope_key,
                item.claim_fingerprint,
                id_map.get(str(authority_ref), authority_ref)
                if authority_ref is not None
                else None,
                item.row["version_id"],
            ),
        )
        by_triple.setdefault(item.new_triple_id, []).append(item)
    for versions in by_triple.values():
        previous_version_id: str | None = None
        for item in sorted(
            versions,
            key=lambda candidate: (
                float(candidate.row.get("created_at") or 0.0),
                str(candidate.row.get("version_id") or ""),
            ),
        ):
            connection.execute(
                """
                UPDATE knowledge_graph_versions
                SET previous_version_id = ?
                WHERE version_id = ?
                """,
                (previous_version_id, item.row["version_id"]),
            )
            previous_version_id = str(item.row["version_id"])


def _edge_reference_targets(
    prepared_edges: Sequence[_PreparedEdge],
    prepared_versions: Sequence[_PreparedEdgeVersion],
) -> dict[str, frozenset[str]]:
    """Resolve active references first, then unambiguous history-only ids."""
    current = {
        str(item.row["triple_id"]): frozenset((item.new_triple_id,)) for item in prepared_edges
    }
    history_only: dict[str, set[str]] = {}
    for item in prepared_versions:
        old_id = str(item.row["triple_id"])
        if old_id in current:
            continue
        history_only.setdefault(old_id, set()).add(item.new_triple_id)
    return {
        **current,
        **{old_id: frozenset(targets) for old_id, targets in history_only.items()},
    }


def _unambiguous_id_map(
    targets: Mapping[str, frozenset[str]],
) -> dict[str, str]:
    return {old_id: next(iter(new_ids)) for old_id, new_ids in targets.items() if len(new_ids) == 1}


def _rewrite_edge_dependencies(
    connection: Any,
    targets: Mapping[str, frozenset[str]],
) -> set[tuple[str, str, str, int]]:
    ambiguous_artifacts: set[tuple[str, str, str, int]] = set()
    for old_id, new_ids in targets.items():
        if new_ids == frozenset((old_id,)):
            continue
        rows = _row_dicts(
            connection,
            """
            SELECT * FROM memory_derivation_dependencies
            WHERE source_kind = 'edge' AND source_id = ?
            """,
            (old_id,),
        )
        if not rows:
            continue
        connection.execute(
            """
            DELETE FROM memory_derivation_dependencies
            WHERE source_kind = 'edge' AND source_id = ?
            """,
            (old_id,),
        )
        for row in rows:
            for new_id in sorted(new_ids):
                connection.execute(
                    """
                    INSERT INTO memory_derivation_dependencies(
                        artifact_kind, artifact_id, source_kind, source_id,
                        subject_key, source_revision, created_at
                    ) VALUES (?, ?, 'edge', ?, ?, ?, ?)
                    ON CONFLICT(artifact_kind, artifact_id, source_kind, source_id)
                    DO UPDATE SET
                        subject_key = excluded.subject_key,
                        source_revision = MAX(
                            memory_derivation_dependencies.source_revision,
                            excluded.source_revision
                        ),
                        created_at = MIN(
                            memory_derivation_dependencies.created_at,
                            excluded.created_at
                        )
                    """,
                    (
                        row["artifact_kind"],
                        row["artifact_id"],
                        new_id,
                        row["subject_key"],
                        row["source_revision"],
                        row["created_at"],
                    ),
                )
            if len(new_ids) > 1:
                ambiguous_artifacts.add(
                    (
                        str(row["artifact_kind"]),
                        str(row["artifact_id"]),
                        str(row["subject_key"]),
                        int(row["source_revision"]),
                    )
                )
    return ambiguous_artifacts


_JSON_REFERENCE_COLUMNS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "tom_snapshots": (
        "snapshot_id",
        "entity_id",
        (
            "preferences",
            "relationship_topology",
            "preferences_history",
            "relationship_history",
            "active_record_ids",
            "superseded_record_ids",
        ),
    ),
    "user_portrait_projection": (
        "user_id",
        "entity_id",
        (
            "world_json",
            "review_json",
            "recent_json",
            "prompt_summary_json",
            "evidence_refs_json",
            "source_counts_json",
        ),
    ),
    "user_profile_projection": (
        "user_id",
        "entity_id",
        (
            "communication_json",
            "identity_json",
            "preferences_json",
            "state_json",
            "field_sources_json",
            "field_conflicts_json",
        ),
    ),
}


def _contains_reference_value(value: Any, reference_ids: set[str]) -> bool:
    if isinstance(value, str):
        if value in reference_ids:
            return True
        return any(
            value.startswith(prefix) and value[len(prefix) :] in reference_ids
            for prefix in ("assertion:", "edge:", "relationship:")
        )
    if isinstance(value, list):
        return any(_contains_reference_value(item, reference_ids) for item in value)
    if isinstance(value, Mapping):
        return any(_contains_reference_value(item, reference_ids) for item in value.values())
    return False


def _rewrite_materialized_json_references(
    connection: Any,
    id_map: Mapping[str, str],
    *,
    ambiguous_ids: set[str] | None = None,
) -> dict[str, int]:
    invalidated_subjects: dict[str, int] = {}
    unresolved_ids = ambiguous_ids or set()
    for table, (
        identity_column,
        subject_column,
        columns,
    ) in _JSON_REFERENCE_COLUMNS.items():
        selected_columns = ", ".join((identity_column, subject_column, "source_revision", *columns))
        for row in _row_dicts(connection, f"SELECT {selected_columns} FROM {table}"):
            assignments: list[str] = []
            values: list[Any] = []
            for column in columns:
                raw = row.get(column)
                if raw is None:
                    continue
                try:
                    decoded = json.loads(str(raw))
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if unresolved_ids and _contains_reference_value(decoded, unresolved_ids):
                    subject_key = str(row[subject_column])
                    invalidated_subjects[subject_key] = max(
                        invalidated_subjects.get(subject_key, 1),
                        int(row.get("source_revision") or 0) + 1,
                    )
                rewritten = _rewrite_reference_value(decoded, id_map)
                if rewritten == decoded:
                    continue
                assignments.append(f"{column} = ?")
                values.append(
                    json.dumps(
                        rewritten,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
            if not assignments:
                continue
            connection.execute(
                f"UPDATE {table} SET {', '.join(assignments)} " f"WHERE {identity_column} = ?",
                (*values, row[identity_column]),
            )
    return invalidated_subjects


def _dependent_artifacts_for_sources(
    connection: Any,
    sources: Sequence[tuple[str, str]],
) -> set[tuple[str, str, str, int]]:
    artifacts: set[tuple[str, str, str, int]] = set()
    for source_kind, source_id in sources:
        for row in _row_dicts(
            connection,
            """
            SELECT artifact_kind, artifact_id, subject_key, source_revision
            FROM memory_derivation_dependencies
            WHERE source_kind = ? AND source_id = ?
            """,
            (source_kind, source_id),
        ):
            artifacts.add(
                (
                    str(row["artifact_kind"]),
                    str(row["artifact_id"]),
                    str(row["subject_key"]),
                    int(row["source_revision"]),
                )
            )
    return artifacts


def _merge_revision_requirements(
    *requirements: Mapping[str, int],
) -> dict[str, int]:
    merged: dict[str, int] = {}
    for requirement in requirements:
        for subject_key, revision in requirement.items():
            merged[subject_key] = max(merged.get(subject_key, 1), int(revision))
    return merged


def _invalidate_derived_artifacts(
    connection: Any,
    artifacts: set[tuple[str, str, str, int]],
    *,
    extra_subject_revisions: Mapping[str, int] | None = None,
) -> None:
    required_revision = dict(extra_subject_revisions or {})
    subjects = set(required_revision)
    insight_ids: set[str] = set()
    for artifact_kind, artifact_id, subject_key, source_revision in artifacts:
        subjects.add(subject_key)
        required_revision[subject_key] = max(
            required_revision.get(subject_key, 0),
            source_revision + 1,
        )
        if artifact_kind == "l3_insight":
            insight_ids.add(artifact_id)

    now = time.time()
    for subject_key in subjects:
        current = connection.execute(
            "SELECT revision FROM memory_subject_revisions WHERE subject_key = ?",
            (subject_key,),
        ).fetchone()
        revision = max(
            (int(current[0]) + 1) if current is not None else 1,
            required_revision.get(subject_key, 1),
        )
        connection.execute(
            """
            INSERT INTO memory_subject_revisions(subject_key, revision, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(subject_key) DO UPDATE SET
                revision = excluded.revision,
                updated_at = excluded.updated_at
            """,
            (subject_key, revision, now),
        )

    if insight_ids:
        placeholders = ", ".join("?" for _ in insight_ids)
        ordered_ids = tuple(sorted(insight_ids))
        connection.execute(
            f"""
            UPDATE summaries
            SET derivation_state = 'stale', embedding_status = 'pending',
                embedding_profile_id = NULL, embedding_chunk_count = 0,
                last_embedded_at = NULL, updated_at = ?
            WHERE summary_id IN ({placeholders})
            """,
            (now, *ordered_ids),
        )
        connection.execute(
            f"DELETE FROM l3_summaries_fts WHERE summary_id IN ({placeholders})",
            ordered_ids,
        )


def _edge_is_retrievable(row: Mapping[str, Any], *, now: float) -> bool:
    if _normalized_text(row.get("status") or "active") != "active":
        return False
    for field in ("valid_to", "expires_at"):
        value = row.get(field)
        if value is not None and float(value) <= now:
            return False
    return True


def _append_collision_version(
    connection: Any,
    *,
    triple_id: str,
    winner_id: str,
    cutoff: float,
    phase: str,
) -> None:
    row = _row_dicts(
        connection,
        "SELECT * FROM knowledge_graph WHERE triple_id = ?",
        (triple_id,),
    )[0]
    previous = connection.execute(
        """
        SELECT version_id, created_at FROM knowledge_graph_versions
        WHERE triple_id = ?
        ORDER BY created_at DESC, version_id DESC
        LIMIT 1
        """,
        (triple_id,),
    ).fetchone()
    previous_id = str(previous[0]) if previous is not None else None
    created_at = max(
        cutoff,
        (float(previous[1]) + 0.000001) if previous is not None else cutoff,
    )
    version_id = f"kgv_v13_{_identity_digest(triple_id, winner_id, phase)[:32]}"
    connection.execute(
        """
        INSERT OR IGNORE INTO knowledge_graph_versions(
            version_id, triple_id, previous_version_id, slot_key, claim_fingerprint,
            subject_id, subject_type, predicate, object_id, object_type, fact_kind,
            confidence, evidence_event_ids, evidence_text, status, valid_from,
            valid_to, scope_key, scope_json, authority_ref, correction_id,
            created_at, natural_summary, observation_count, first_observed_at,
            last_observed_at, last_confirmed_at, source_type, extraction_method,
            expires_at, evidence_class, edge_created_at, governance_complete
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1
        )
        """,
        (
            version_id,
            triple_id,
            previous_id,
            row["slot_key"],
            row["claim_fingerprint"],
            row["subject_id"],
            row["subject_type"],
            row["predicate"],
            row["object_id"],
            row["object_type"],
            row["fact_kind"],
            row["confidence"],
            row["evidence_event_ids"],
            row["evidence_text"],
            row["status"],
            row["valid_from"],
            row["valid_to"],
            row["scope_key"],
            row["scope_json"],
            row["authority_ref"],
            created_at,
            row["natural_summary"],
            row["observation_count"],
            row["first_observed_at"],
            row["last_observed_at"],
            row["last_confirmed_at"],
            row["source_type"],
            row["extraction_method"],
            row["expires_at"],
            row["evidence_class"],
            row["created_at"],
        ),
    )


def _reconcile_edge_scope_collisions(connection: Any) -> dict[str, str]:
    now = time.time()
    collision_losers: dict[str, str] = {}
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in _row_dicts(
        connection,
        "SELECT * FROM knowledge_graph WHERE status = 'active'",
    ):
        groups.setdefault(
            (str(row.get("slot_key") or ""), str(row.get("scope_key") or "global")),
            [],
        ).append(row)
    for group in groups.values():
        if len(group) <= 1:
            continue
        winner = max(
            group,
            key=lambda row: (
                _edge_is_retrievable(row, now=now),
                bool(row.get("authority_ref")),
                _normalized_text(row.get("evidence_class")) == "user_self_report",
                float(row.get("updated_at") or 0.0),
                float(row.get("created_at") or 0.0),
                str(row.get("triple_id") or ""),
            ),
        )
        winner_id = str(winner["triple_id"])
        for loser in group:
            loser_id = str(loser["triple_id"])
            if loser_id == winner_id:
                continue
            cutoff = max(
                float(winner.get("updated_at") or 0.0),
                float(winner.get("valid_from") or winner.get("created_at") or 0.0),
                float(loser.get("updated_at") or 0.0),
                float(loser.get("valid_from") or loser.get("created_at") or 0.0),
            )
            existing_valid_to = loser.get("valid_to")
            valid_from = float(loser.get("valid_from") or loser.get("created_at") or 0.0)
            valid_to = cutoff
            if existing_valid_to is not None:
                valid_to = min(valid_to, float(existing_valid_to))
            valid_to = max(valid_from, valid_to)
            _append_collision_version(
                connection,
                triple_id=loser_id,
                winner_id=winner_id,
                cutoff=cutoff,
                phase="active",
            )
            connection.execute(
                """
                UPDATE knowledge_graph
                SET status = 'deprecated',
                    status_reason = 'v13_scope_alias_collision',
                    deprecated_by = ?, deprecated_at = ?, valid_to = ?,
                    embedding_status = 'disabled', embedding_profile_id = NULL,
                    last_embedded_at = NULL, updated_at = ?
                WHERE triple_id = ?
                """,
                (winner_id, cutoff, valid_to, cutoff, loser_id),
            )
            _append_collision_version(
                connection,
                triple_id=loser_id,
                winner_id=winner_id,
                cutoff=cutoff,
                phase="closed",
            )
            collision_losers[loser_id] = winner_id
    return collision_losers


def _retire_collision_authority(
    connection: Any,
    *,
    assertion_losers: Mapping[str, str],
    edge_losers: Mapping[str, str],
    plans: Mapping[str, _CorrectionPlan],
) -> tuple[set[tuple[str, str, str, int]], dict[str, int]]:
    loser_ids = set(assertion_losers) | set(edge_losers)
    if not loser_ids:
        return set(), {}

    placeholders = ", ".join("?" for _ in loser_ids)
    ordered_losers = tuple(sorted(loser_ids))
    correction_ids = [
        str(row[0])
        for row in connection.execute(
            f"""
            SELECT correction_id
            FROM memory_corrections
            WHERE replacement_target_id IN ({placeholders})
            ORDER BY correction_id
            """,
            ordered_losers,
        ).fetchall()
    ]
    for correction_id in correction_ids:
        connection.execute(
            """
            UPDATE memory_correction_rules
            SET active = 0
            WHERE active = 1 AND rule_kind = 'authoritative_slot'
              AND correction_id = ?
            """,
            (correction_id,),
        )
        plan = plans.get(correction_id)
        replacement_scope_key = plan.replacement_scope_key if plan is not None else None
        replacement_converged = bool(
            plan is not None
            and plan.replacement_fingerprint is not None
            and plan.before_fingerprint == plan.replacement_fingerprint
            and plan.before_scope_key == replacement_scope_key
        )
        if replacement_converged:
            connection.execute(
                """
                UPDATE memory_correction_rules
                SET active = 0
                WHERE active = 1 AND rule_kind = 'scope_only'
                  AND correction_id = ?
                """,
                (correction_id,),
            )
    sources = [
        *(("assertion", loser_id) for loser_id in assertion_losers),
        *(("edge", loser_id) for loser_id in edge_losers),
    ]
    artifacts = _dependent_artifacts_for_sources(connection, sources)
    subjects = _rewrite_materialized_json_references(
        connection,
        {},
        ambiguous_ids=loser_ids,
    )
    return artifacts, subjects


@dataclass(frozen=True, slots=True)
class _EdgeMigrationResult:
    reference_id_map: dict[str, str]
    ambiguous_artifacts: set[tuple[str, str, str, int]]
    ambiguous_subject_revisions: dict[str, int]
    collision_losers: dict[str, str]


def _migrate_edges(
    connection: Any,
    plans: Mapping[str, _CorrectionPlan],
) -> _EdgeMigrationResult:
    _rebuild_knowledge_graph_for_scoped_identity(connection)
    prepared_edges = _prepare_edges(connection, plans)
    prepared_versions = _prepare_edge_versions(connection, plans)
    _apply_edge_identity_migration(connection, prepared_edges)
    reference_targets = _edge_reference_targets(prepared_edges, prepared_versions)
    reference_id_map = _unambiguous_id_map(reference_targets)
    ambiguous_ids = {
        old_id for old_id, target_ids in reference_targets.items() if len(target_ids) > 1
    }
    _apply_edge_version_identity_migration(
        connection,
        prepared_versions,
        reference_id_map,
    )
    ambiguous_artifacts = _rewrite_edge_dependencies(connection, reference_targets)
    ambiguous_subject_revisions = _rewrite_materialized_json_references(
        connection,
        reference_id_map,
        ambiguous_ids=ambiguous_ids,
    )
    collision_losers = _reconcile_edge_scope_collisions(connection)
    return _EdgeMigrationResult(
        reference_id_map=reference_id_map,
        ambiguous_artifacts=ambiguous_artifacts,
        ambiguous_subject_revisions=ambiguous_subject_revisions,
        collision_losers=collision_losers,
    )


def upgrade() -> None:
    connection = op.get_bind().connection
    _preflight_correction_snapshots(connection)
    connection.executescript(SCHEMA_SQL)
    connection.execute("SAVEPOINT v13_stable_context_data")
    try:
        _seed_builtin_contexts(connection)
        assertion_losers = _migrate_assertions(connection)
        plans = _prepare_correction_plans(connection)
        edge_result = _migrate_edges(connection, plans)
        _migrate_corrections_and_rules(
            connection,
            plans,
            edge_result.reference_id_map,
        )
        collision_artifacts, collision_subjects = _retire_collision_authority(
            connection,
            assertion_losers=assertion_losers,
            edge_losers=edge_result.collision_losers,
            plans=plans,
        )
        _invalidate_derived_artifacts(
            connection,
            edge_result.ambiguous_artifacts | collision_artifacts,
            extra_subject_revisions=_merge_revision_requirements(
                edge_result.ambiguous_subject_revisions,
                collision_subjects,
            ),
        )
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT v13_stable_context_data")
        connection.execute("RELEASE SAVEPOINT v13_stable_context_data")
        raise
    connection.execute("RELEASE SAVEPOINT v13_stable_context_data")


def downgrade() -> None:
    raise RuntimeError(
        "Stable context identities cannot be downgraded without losing workspace bindings"
    )


__all__ = [
    "SCHEMA_SQL",
    "downgrade",
    "schema_sql_for_fresh_database",
    "upgrade",
]
