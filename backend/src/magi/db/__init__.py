"""Alembic-managed schema migrations for Magi runtime SQLite databases.

This package owns the migration version chains for the six core
runtime databases. Each subdirectory is an independent Alembic
environment with its own ``alembic_version`` table:

    chat              chat.db
    l1                l1_events.db
    memory_shared     memory.db (L0 / L2 / L3 / L4)
    runtime_trace     runtime_trace.db
    llm_usage         llm_usage.db
    persona_registry  persona_registry.db

Smaller, low-churn databases (behavior_evolution, emotional_state,
growth_memory, scheduler, message_queue, sensor_state,
background_tasks) are intentionally excluded; their lifecycle modules
manage schema directly.
"""

from .runner import MIGRATION_TARGETS, MigrationTarget, run_upgrade_head

__all__ = ["MIGRATION_TARGETS", "MigrationTarget", "run_upgrade_head"]
