"""Explicit SQLite composition for isolated memory tests."""

from pathlib import Path
from typing import Any

from magi_plugin_sdk.runtime_paths import get_magi_home

from magi.memory.embedding.sqlite_factory import SqliteVectorIndexFactory
from magi.memory.l1.event_store import L1EventStore
from magi.memory.l1.storage.events import SqliteMemoryEventRepository
from magi.memory.unified_store import UnifiedMemoryStore

from .db_schema import apply_chain_schema


def build_l1_store(*, db_path: str | None = None, **options: Any) -> L1EventStore:
    path = str(Path(db_path or get_magi_home() / "data/memory/l1_events.db").expanduser())
    apply_chain_schema("l1", path)
    repository = options.pop("event_repository", None)
    indexes = options.pop("vector_index_factory", None)
    return L1EventStore(
        event_repository=repository if repository is not None else SqliteMemoryEventRepository(path),
        vector_index_factory=indexes if indexes is not None else SqliteVectorIndexFactory(l1_db_path=path, memory_db_path=path),
        **options,
    )


def build_memory_store(*args: Any, **options: Any) -> UnifiedMemoryStore:
    paths = UnifiedMemoryStore._resolve_memory_store_paths(
        db_path=options.get("db_path", args[0] if args else None),
        persist_dir=options.get("persist_dir", args[1] if len(args) > 1 else None),
        l1_db_path=options.get("l1_db_path"), memory_db_path=options.get("memory_db_path"),
        archive_dir_path=options.get("archive_dir_path"),
    )
    if options.get("enable_l1", True):
        apply_chain_schema("l1", paths.l1_db_path)
        options.setdefault("event_repository", SqliteMemoryEventRepository(paths.l1_db_path))
    return UnifiedMemoryStore(*args, **options)


def l1_database_path(store: L1EventStore) -> str:
    """Access the concrete test adapter for fault injection, never production use."""
    assert isinstance(store.event_repository, SqliteMemoryEventRepository)
    return store.event_repository._db_path
