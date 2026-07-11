"""Runtime constants for L2 experience persistence.

The actual DDL lives in the memory_shared v1 Alembic baseline. Runtime code
imports these names to avoid string drift.
"""

from __future__ import annotations

EXPERIENCES_TABLE = "experiences"
EXPERIENCE_MEMBERS_TABLE = "experience_members"
EXPERIENCE_KEY_EVENTS_TABLE = "experience_key_events"
EXPERIENCE_SEEDS_TABLE = "experience_seeds"
EXPERIENCE_SEED_EVIDENCE_TABLE = "experience_seed_evidence"
EXPERIENCE_DRAFTS_TABLE = "experience_drafts"
EXPERIENCE_CHAPTERS_TABLE = "experience_chapters"

__all__ = [
    "EXPERIENCES_TABLE",
    "EXPERIENCE_KEY_EVENTS_TABLE",
    "EXPERIENCE_MEMBERS_TABLE",
    "EXPERIENCE_SEEDS_TABLE",
    "EXPERIENCE_SEED_EVIDENCE_TABLE",
    "EXPERIENCE_DRAFTS_TABLE",
    "EXPERIENCE_CHAPTERS_TABLE",
]
