"""Behavior evolution database schema helpers.

Schema is owned by alembic (``magi.db.migrations.behavior_evolution``).
"""

from __future__ import annotations

from pathlib import Path


class BehaviorEvolutionSchemaMixin:
    """Initialize behavior evolution database directory."""

    _expanded_db_path: str

    async def init(self):
        """No-op kept for compatibility — schema is alembic-managed."""
        Path(self._expanded_db_path).parent.mkdir(parents=True, exist_ok=True)


__all__ = ["BehaviorEvolutionSchemaMixin"]
