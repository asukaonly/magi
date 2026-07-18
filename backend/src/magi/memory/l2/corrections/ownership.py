"""Ownership helpers for correction-created memory records."""

from __future__ import annotations

from typing import Any

CORRECTION_AUTHORITY_PREFIX = "correction:"


def correction_authority_ref(correction_id: str) -> str:
    """Return the durable authority marker for one correction."""
    return f"{CORRECTION_AUTHORITY_PREFIX}{correction_id}"


def has_correction_owner(authority_ref: Any) -> bool:
    """Return whether a record is owned by any correction."""
    return str(authority_ref or "").startswith(CORRECTION_AUTHORITY_PREFIX)


def correction_owns_record(authority_ref: Any, correction_id: str) -> bool:
    """Return whether a record is exclusively owned by one correction."""
    return str(authority_ref or "") == correction_authority_ref(correction_id)


__all__ = [
    "CORRECTION_AUTHORITY_PREFIX",
    "correction_authority_ref",
    "correction_owns_record",
    "has_correction_owner",
]
