"""Human-readable display fallback for entity_id when canonical_name is missing.

Round 4 (C2 fix): Phase 5's drop-if-unresolved policy was too aggressive on
fresh / partial entity_catalog deployments. This helper provides a graceful
middle ground:

1. canonical_name from catalog → best display
2. else parse entity_id slug (the part after 'type:'):
   - human-readable slug → use it
   - hash-like slug → '(未命名 {type})'
3. else (no 'type:slug' shape at all) → None (caller drops the finding/ref)

This preserves Phase 5's safety invariant ('never render raw hash as the
primary display field') while keeping the system usable when the
entity_catalog hasn't been fully backfilled.
"""

from __future__ import annotations

from typing import Optional

# Hash-likeness threshold: a slug is treated as a hash when length >= 8 AND
# >= 80% of characters are lowercase hex (0-9, a-f). Empirical: matches the
# uuid-style ids used by L2 (e.g. 74f953b57f75) without false-positive on
# common username/topic forms.
_MIN_HASH_LENGTH = 8
_HASH_RATIO_THRESHOLD = 0.8
_HEX_CHARS = frozenset("0123456789abcdef")


def parse_entity_id(entity_id: str) -> Optional[tuple[str, str]]:
    """Parse 'type:slug' into (type, slug). Only splits on the first colon
    so slugs containing ':' are preserved (e.g. 'preference:address_form:子涵'
    → ('preference', 'address_form:子涵')). Returns None when the format
    isn't valid."""
    if not entity_id:
        return None
    if ":" not in entity_id:
        return None
    entity_type, _, slug = entity_id.partition(":")
    if not entity_type or not slug:
        return None
    return entity_type, slug


def is_hash_like_slug(slug: str) -> bool:
    """True when the slug looks like a UUID / hash rather than human text.

    Heuristic: length >= 8 AND >= 80% of characters are lowercase hex digits.
    Short strings (<8 chars) and strings with significant non-hex characters
    are treated as human-readable."""
    if len(slug) < _MIN_HASH_LENGTH:
        return False
    hex_count = sum(1 for c in slug if c in _HEX_CHARS)
    return (hex_count / len(slug)) >= _HASH_RATIO_THRESHOLD


def display_name_for(
    entity_id: str,
    canonical_names: Optional[dict[str, str]],
) -> Optional[str]:
    """Resolve entity_id to a human-readable display string.

    Priority:
    1. canonical_names[entity_id] if present
    2. slug part of 'type:slug' if slug looks human-readable
    3. '(未命名 {type})' if slug looks like a hash
    4. None if entity_id isn't 'type:slug' shape (caller drops)
    """
    if canonical_names and entity_id in canonical_names:
        return canonical_names[entity_id]
    parsed = parse_entity_id(entity_id)
    if parsed is None:
        return None
    entity_type, slug = parsed
    if is_hash_like_slug(slug):
        return f"(未命名 {entity_type})"
    return slug
