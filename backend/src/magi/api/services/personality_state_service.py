"""Explicit API services for personality state access."""

from __future__ import annotations

from ...personality.current_state import (
    get_current_personality,
    set_current_personality,
)


def get_current_personality_name() -> str:
    """Return the active personality name."""
    return get_current_personality()


def set_current_personality_name(name: str) -> bool:
    """Update the active personality name."""
    return set_current_personality(name)


__all__ = [
    "get_current_personality_name",
    "set_current_personality_name",
]
