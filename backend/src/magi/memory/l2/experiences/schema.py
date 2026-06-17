"""Runtime constants for L2 experience persistence.

The actual DDL lives in the memory_shared Alembic migration
``0015_l2_experiences``. Runtime code imports these names to avoid string drift.
"""

from __future__ import annotations

EXPERIENCES_TABLE = "experiences"
EXPERIENCE_MEMBERS_TABLE = "experience_members"
EXPERIENCE_KEY_EVENTS_TABLE = "experience_key_events"

__all__ = [
    "EXPERIENCES_TABLE",
    "EXPERIENCE_KEY_EVENTS_TABLE",
    "EXPERIENCE_MEMBERS_TABLE",
]
