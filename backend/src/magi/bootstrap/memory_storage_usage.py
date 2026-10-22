"""Select a complete footprint reader without exposing filenames to the API."""

from pathlib import Path

from ..config.memory_models import MemorySettings
from ..config.storage_models import StructuredStorageSettings
from ..memory.local_storage_usage import LocalMemoryStorageUsage
from ..memory.storage_usage import MemoryStorageUsage
from ..utils.runtime import RuntimePaths


def compose_memory_storage_usage(
    paths: RuntimePaths, memory: MemorySettings, structured: StructuredStorageSettings,
) -> MemoryStorageUsage | None:
    if structured.memory_events != "sqlite" or memory.vector_storage.backend != "sqlite_vec":
        return None
    databases = [paths.l1_memory_db_path, paths.memory_db_path]
    if memory.vector_storage.sqlite_path:
        databases.append(Path(memory.vector_storage.sqlite_path).expanduser())
    return LocalMemoryStorageUsage(tuple(databases))
