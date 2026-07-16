"""Deterministic identities for governed memory claims and scopes."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from ...context_scope.models import (
    canonical_context_scope,
    context_conditions,
    normalize_context_scope,
)

_WHITESPACE_RE = re.compile(r"\s+")
GLOBAL_SCOPE_KEY = "global"
SUPPORTED_SCOPE_FIELDS = frozenset({"all_of"})


def _normalized_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return _WHITESPACE_RE.sub(" ", text).casefold()


def _stable_digest(*parts: Any) -> str:
    payload = "\x1f".join(_normalized_text(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def canonical_claim_value(value: Any) -> str:
    """Return a stable comparison form without changing stored display text."""
    if isinstance(value, (Mapping, Sequence)) and not isinstance(value, (str, bytes, bytearray)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
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


def canonical_scope_json(scope: Mapping[str, Any] | None) -> str:
    """Serialize an identity-based correction scope in a stable order."""
    return canonical_context_scope(scope)


def scope_key(scope: Mapping[str, Any] | None) -> str:
    """Return ``global`` for no scope, otherwise a deterministic scope id."""
    canonical = canonical_scope_json(scope)
    if canonical == "{}":
        return GLOBAL_SCOPE_KEY
    return f"scope_{_stable_digest(canonical)}"


def stored_context_scope(snapshot: Mapping[str, Any]) -> dict[str, list[dict[str, str]]]:
    """Return the validated context scope stored in a claim snapshot."""
    raw_scope: object = snapshot.get("scope_json")
    if raw_scope in (None, ""):
        raw_scope = snapshot.get("scope")
    if isinstance(raw_scope, str):
        try:
            raw_scope = json.loads(raw_scope)
        except json.JSONDecodeError as exc:
            raise ValueError("Stored context scope is malformed") from exc
    return normalize_context_scope(raw_scope)


def scope_matches(
    claim_scope: Mapping[str, Any] | None,
    context_scope: Mapping[str, Any] | None,
) -> bool:
    """Return whether every claim constraint is present in the query context.

    An empty claim scope is global and matches every explicit context. An empty
    query context intentionally matches only global claims, preventing scoped
    refinements from leaking into ordinary recall.
    """
    claim = set(context_conditions(claim_scope))
    context = set(context_conditions(context_scope))
    if not claim:
        return True
    if not context:
        return False
    return claim <= context


def scope_specificity(scope: Mapping[str, Any] | None) -> int:
    """Return the deterministic precedence of a matching claim scope."""
    return len(context_conditions(scope))


def assertion_slot_key(
    *,
    entity_type: str,
    entity_id: str,
    trait_name: str,
    target_entity_id: str = "",
) -> str:
    """Identify the logical assertion field independent of value and scope."""
    return "assertion_slot_" + _stable_digest(entity_type, entity_id, trait_name, target_entity_id)


def assertion_claim_fingerprint(
    *,
    slot_key_value: str,
    trait_value: Any,
    scope_key_value: str = GLOBAL_SCOPE_KEY,
) -> str:
    """Identify one concrete assertion value in one scope."""
    return "assertion_claim_" + _stable_digest(
        slot_key_value,
        scope_key_value,
        canonical_claim_value(trait_value),
    )


def relationship_slot_key(
    *,
    subject_id: str,
    predicate: str,
    object_id: str,
    predicate_slot: str | None = None,
) -> str:
    """Identify a relationship slot, keeping non-exclusive objects isolated."""
    effective_slot = str(predicate_slot or "").strip()
    if effective_slot:
        return "edge_slot_" + _stable_digest(subject_id, effective_slot)
    return "edge_slot_" + _stable_digest(subject_id, predicate, object_id)


def relationship_claim_fingerprint(
    *,
    slot_key_value: str,
    subject_id: str,
    predicate: str,
    object_id: str,
    scope_key_value: str = GLOBAL_SCOPE_KEY,
) -> str:
    """Identify one concrete graph relation in one scope."""
    return "edge_claim_" + _stable_digest(
        slot_key_value,
        subject_id,
        predicate,
        object_id,
        scope_key_value,
    )


def relationship_triple_id(
    *,
    subject_id: str,
    predicate: str,
    object_id: str,
    scope_key_value: str = GLOBAL_SCOPE_KEY,
) -> str:
    """Return a stable relationship row id without collapsing distinct scopes."""
    triple_key = f"{subject_id}:{predicate}:{object_id}"
    if scope_key_value != GLOBAL_SCOPE_KEY:
        triple_key = f"{triple_key}:{scope_key_value}"
    return f"triple_{uuid.uuid5(uuid.NAMESPACE_DNS, triple_key)}"


__all__ = [
    "GLOBAL_SCOPE_KEY",
    "SUPPORTED_SCOPE_FIELDS",
    "assertion_claim_fingerprint",
    "assertion_slot_key",
    "canonical_claim_value",
    "canonical_scope_json",
    "relationship_claim_fingerprint",
    "relationship_slot_key",
    "relationship_triple_id",
    "scope_matches",
    "scope_specificity",
    "scope_key",
    "stored_context_scope",
]
