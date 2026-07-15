"""Deterministic identities for governed memory claims and scopes."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

_WHITESPACE_RE = re.compile(r"\s+")
GLOBAL_SCOPE_KEY = "global"


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
    """Serialize a controlled correction scope in a stable order."""
    if not scope:
        return "{}"
    return json.dumps(scope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def scope_key(scope: Mapping[str, Any] | None) -> str:
    """Return ``global`` for no scope, otherwise a deterministic scope id."""
    canonical = canonical_scope_json(scope)
    if canonical == "{}":
        return GLOBAL_SCOPE_KEY
    return f"scope_{_stable_digest(canonical)}"


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


__all__ = [
    "GLOBAL_SCOPE_KEY",
    "assertion_claim_fingerprint",
    "assertion_slot_key",
    "canonical_claim_value",
    "canonical_scope_json",
    "relationship_claim_fingerprint",
    "relationship_slot_key",
    "scope_key",
]
