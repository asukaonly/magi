"""Stable entity identity helpers independent of display-name slugs."""

from __future__ import annotations

import json
import unicodedata
import uuid


def normalized_entity_name(value: str) -> str:
    """Normalize spelling without discarding any source-language characters."""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def canonical_entity_id(entity_type: str, canonical_name: str) -> str:
    """Build a collision-resistant identity for one newly resolved named entity."""
    kind = str(entity_type).strip().casefold()
    name = normalized_entity_name(canonical_name)
    if not kind or not name:
        raise ValueError("Entity type and canonical name must be non-empty")
    identity = json.dumps([kind, name], ensure_ascii=False, separators=(",", ":"))
    return f"{kind}:{uuid.uuid5(uuid.NAMESPACE_URL, identity).hex}"


# These types denote reusable concepts. People, places, works and projects need identity evidence.
CONCEPT_ENTITY_TYPES = frozenset({"topic", "concept", "technology", "software", "food", "language", "skill"})


def scoped_entity_id(entity_type: str, namespace: str, source_key: str) -> str:
    """Keep a producer's identity stable without conflating it with its label."""
    identity = json.dumps([entity_type, namespace, source_key], ensure_ascii=False)
    return f"{entity_type}:source:{uuid.uuid5(uuid.NAMESPACE_URL, identity).hex}"


def entity_hint_id(hint: dict, *, source: str, event_id: str) -> str:
    """Resolve source-owned structured identity, using event scope for unnamed identities."""
    kind = str(hint.get("entity_type") or "").strip().casefold()
    key = str(hint.get("source_entity_key") or "").strip()
    if key:
        return scoped_entity_id(kind, source, key)
    if hint.get("resolved_entity_id"):
        return str(hint["resolved_entity_id"])
    name = str(hint.get("canonical_name_hint") or hint.get("mention_text") or "")
    if kind in CONCEPT_ENTITY_TYPES:
        return canonical_entity_id(kind, name)
    return scoped_entity_id(kind, f"{source}:event:{event_id}", normalized_entity_name(name))
