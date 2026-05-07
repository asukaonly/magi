"""Background task store initialization helper.

Schema is owned by alembic (``magi.db.migrations.background_tasks``).
"""

from __future__ import annotations

from pathlib import Path


class BackgroundTaskSchemaMixin:
    """Initialize background task store directory."""

    db_path: str
    _initialized: bool

    async def initialize(self) -> None:
        if self._initialized:
            return
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialized = True


__all__ = ["BackgroundTaskSchemaMixin"]
