"""Storage shape constraints for evidence-grounded catalog names."""

from __future__ import annotations

import unicodedata

MAX_ENTITY_NAME_CHARS = 200


def valid_entity_name(value: str) -> bool:
    """Validate a name's shape without interpreting its language or meaning."""
    text = value.strip()
    return (
        bool(text)
        and len(text) <= MAX_ENTITY_NAME_CHARS
        and not any(unicodedata.category(char) == "Cc" for char in text)
    )
