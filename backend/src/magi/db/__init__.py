"""Alembic-managed schema migrations for Magi runtime SQLite databases.

This package owns every runtime SQLite migration chain. Each subdirectory
is an independent Alembic environment with its own ``alembic_version``
table. ``MIGRATION_TARGETS`` binds those chains to runtime database paths,
including scheduler jobs and source cursors, fingerprints, and statistics.
Store lifecycle modules initialize access after the owning chain is applied.
"""

from .runner import MIGRATION_TARGETS, MigrationTarget, run_upgrade_head

__all__ = ["MIGRATION_TARGETS", "MigrationTarget", "run_upgrade_head"]
