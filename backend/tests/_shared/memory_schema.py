"""Shared schema setup for memory tests.

Single source of truth for the memory_shared release baseline, used by
tests/memory/l2/conftest.py, tests/memory/l3/conftest.py, and
tests/api/conftest.py.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import aiosqlite

_MIGRATIONS_DIR = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "magi"
    / "db"
    / "migrations"
    / "memory_shared"
    / "versions"
)

MEMORY_SHARED_MIGRATIONS: tuple[str, ...] = (
    "v1_initial.py",
    "v2_experience_drafts.py",
    "v3_experience_draft_cover.py",
    "v4_memory_corrections.py",
    "v5_assertion_scope_uniqueness.py",
    "v6_relationship_governance_slots.py",
    "v7_l3_derivation_state.py",
    "v9_memory_clear_generation.py",
    "v10_relationship_version_snapshot.py",
    "v11_correction_evidence_governance.py",
    "v12_scheduled_correction_transitions.py",
    "v13_stable_context_scopes.py",
    "v14_relationship_conflict_effects.py",
    "v15_correction_evidence_fail_closed.py",
    "v16_relationship_correction_reconciliation.py",
    "v17_scheduled_correction_cancellation.py",
    "v18_persistent_forget_governance.py",
    "v19_claim_evidence_ledger.py",
    "v20_identity_rekey_indexes.py",
    "v21_source_event_forgetting.py",
    "v22_l4_source_event_links.py",
    "v23_l0_tactic_source_tombstones.py",
    "v24_entity_name_evidence.py",
    "v25_daily_mood_source_events.py",
    "v26_manual_entry_projection_intent.py",
    "v27_durable_forget_operations.py",
    "v28_time_range_forget_barriers.py",
    "v29_correction_revert_blocks.py",
    "v30_correction_request_fingerprints.py",
    "v31_correction_replacement_slot_index.py",
    "v32_forget_source_owner_refs.py",
    "v33_chat_forget_activation.py",
    "v35_l0_attention_state.py",
    "v36_history_imports.py",
    "v37_history_import_selection.py",
    "v38_l2_grounded_claims.py",
    "v39_l2_projection_leases.py",
    "v40_l2_entity_link_outbox.py",
    "v41_l2_claim_subject_revisions.py",
    "v42_l2_projection_batch_descriptors.py",
    "v43_assertion_semantic_lineage.py",
    "v44_l2_pending_reviews.py",
)


def _load_migration(filename: str) -> ModuleType:
    migration_path = _MIGRATIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(f"memory_shared_{filename}", migration_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load migration {migration_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def apply_memory_shared_schema(db_path: str) -> None:
    """Apply the memory_shared release baseline to a fresh sqlite file."""
    for filename in MEMORY_SHARED_MIGRATIONS:
        migration = _load_migration(filename)
        fresh_schema = getattr(migration, "schema_sql_for_fresh_database", None)
        sql = fresh_schema() if fresh_schema is not None else migration.SCHEMA_SQL
        async with aiosqlite.connect(db_path) as db:
            # executescript runs its own implicit COMMIT — no explicit commit needed.
            await db.executescript(sql)
