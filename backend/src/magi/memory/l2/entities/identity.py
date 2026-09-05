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
