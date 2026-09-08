"""Stable entity identity helpers independent of display-name slugs."""

from __future__ import annotations

import json
import unicodedata
import uuid


def normalized_entity_name(value: str) -> str:
    """Normalize spelling without discarding any source-language characters."""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def allocate_entity_id() -> str:
    """Allocate an identity for a new referent independently of spelling and type."""
    return f"entity:{uuid.uuid4().hex}"


def scoped_entity_id(entity_type: str, namespace: str, source_key: str) -> str:
    """Keep a producer's identity stable without conflating it with its label."""
    identity = json.dumps([namespace, source_key], ensure_ascii=False)
    return f"entity:{uuid.uuid5(uuid.NAMESPACE_URL, identity).hex}"


def entity_hint_id(hint: dict, *, source: str, event_id: str, source_ordinal: int = 0) -> str:
    """Resolve source-owned structured identity, using event scope for unnamed identities."""
    kind = str(hint.get("entity_type") or "").strip().casefold()
    if hint.get("resolved_entity_id"):
        return str(hint["resolved_entity_id"])
    key = str(hint.get("source_entity_key") or "").strip()
    if key:
        return scoped_entity_id(kind, source, key)
    return scoped_entity_id(kind, f"{source}:event:{event_id}", str(source_ordinal))
