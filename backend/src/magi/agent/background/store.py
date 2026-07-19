"""SQLite persistence facade for background tasks."""

from __future__ import annotations

from pathlib import Path

from .store_completions import BackgroundTaskCompletionStoreMixin
from .store_events import BackgroundTaskEventStoreMixin
from .store_mapping import BackgroundTaskRowMappingMixin
from .store_schema import BackgroundTaskSchemaMixin
from .store_tasks import BackgroundTaskRowStoreMixin


_DEFAULT_DB_PATH = "~/.magi/runtime/background_tasks.db"


class BackgroundTaskStore(
    BackgroundTaskCompletionStoreMixin,
    BackgroundTaskRowStoreMixin,
    BackgroundTaskEventStoreMixin,
    BackgroundTaskSchemaMixin,
    BackgroundTaskRowMappingMixin,
):
    """Persist and query background tasks plus their event logs."""

    def __init__(self, *, db_path: str = _DEFAULT_DB_PATH) -> None:
        self.db_path = str(Path(db_path).expanduser())
        self._initialized = False


__all__ = ["BackgroundTaskStore"]
