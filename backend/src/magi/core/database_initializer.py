"""First-run marker for runtime-owned SQLite stores."""

from __future__ import annotations

import logging

from ..utils.runtime import RuntimePaths

logger = logging.getLogger(__name__)


class DatabaseInitializer:
    """Track whether the runtime has completed its first-run setup.

    Each store (chat, L0–L4 memory, personality DBs) owns its own
    ``CREATE TABLE`` statements and runs them at construction time. This
    class only records that the runtime has been brought up at least
    once via a marker file, so other lifecycle modules can skip
    one-shot setup work on subsequent boots.
    """

    INIT_MARKER_FILE = ".db_initialized"

    def __init__(self, runtime_paths: RuntimePaths):
        self.runtime_paths = runtime_paths

    @property
    def is_first_run(self) -> bool:
        return not (self.runtime_paths.runtime_dir / self.INIT_MARKER_FILE).exists()

    def mark_initialized(self) -> None:
        marker_file = self.runtime_paths.runtime_dir / self.INIT_MARKER_FILE
        marker_file.touch()
        logger.info("Marked runtime as initialized: %s", marker_file)

    async def initialize_all(self) -> None:
        """Ensure runtime directories exist; stores create their own schemas."""
        self.runtime_paths.data_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_paths.app_data_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_paths.memory_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_paths.chat_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_paths.resources_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_paths.runtime_dir.mkdir(parents=True, exist_ok=True)

    async def insert_default_data(self) -> None:
        """Mark first-run setup complete. Stores own their own seed data."""
        if self.is_first_run:
            self.mark_initialized()


_database_initializer: DatabaseInitializer | None = None


def get_database_initializer() -> DatabaseInitializer | None:
    return _database_initializer


def set_database_initializer(initializer: DatabaseInitializer) -> None:
    global _database_initializer
    _database_initializer = initializer
