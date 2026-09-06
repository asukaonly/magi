"""Top-level test fixtures.

Phase J: ``runtime_paths_with_schema`` builds a :class:`RuntimePaths`
rooted at a tmp directory and runs every Alembic migration so DAOs
can query their tables without hand-applying DDL inside each test
fixture.

Most tests just need:

    def test_x(runtime_paths_with_schema):
        store = SomeStore(db_path=str(runtime_paths_with_schema.chat_db_path))
        # tables exist; just use it

The fixture is per-test (function scope) so tests can't leak state
into each other. If a suite needs to share schema across many tests
for speed, copy this fixture and re-scope to ``session``.
"""

from __future__ import annotations

import pytest

from magi.db import run_upgrade_head
from magi.utils.runtime import RuntimePaths


@pytest.fixture
def runtime_paths_with_schema(tmp_path):
    """A :class:`RuntimePaths` tree with all Alembic migrations applied.

    Use this in any test that needs to query a Magi SQLite store
    (chat, runtime_trace, channels, background_tasks, etc.). The
    schemas are bootstrapped via the production ``run_upgrade_head``
    path, so adding new migrations gets caught automatically.
    """
    paths = RuntimePaths(base_dir=tmp_path)
    # RuntimePaths.__init__ already ensures the standard directory
    # tree exists; ``run_upgrade_head`` makes any leftover parent dirs
    # itself before invoking Alembic.
    run_upgrade_head(paths)
    return paths


@pytest.fixture
def ensure_db_schema():
    """Callable ``(chain, db_path)`` applying an alembic chain to a db file.

    Backed by ``tests/_shared/db_schema.py`` (real ``upgrade head`` with a
    template-copy fast path). Use for any store opened against a fresh
    tmp-path db file — schemas are alembic-owned, stores carry no DDL.
    """
    from _shared.db_schema import apply_chain_schema

    return apply_chain_schema


@pytest.fixture(autouse=True)
def _reset_chat_read_singletons():
    """Reset chat readers that freeze runtime paths at construction."""
    from magi.core.container import get_container

    def reset() -> None:
        try:
            container = get_container()
            for provider in (
                container.chat_read_service,
                container.chat_trace_read_service,
            ):
                provider.reset_override()
                provider.reset()
        except Exception:
            pass

    reset()
    yield
    reset()


@pytest.fixture(autouse=True)
def _hermetic_user_preferences(monkeypatch, tmp_path):
    """Tests must not read the developer's real runtime config.

    ``magi.i18n.get_preferred_language`` falls back to the process-wide user
    preference store — the developer's real ``~/.magi`` config once any
    earlier test happens to initialize the config loader. That flipped the
    LLM target-language validation to the developer's UI language (zh)
    mid-suite and rejected English mock outputs (order-dependent failures).
    Pin preferences to defaults; tests that need a specific language use
    ``language_context()``/``set_current_language``.
    """
    import magi.config.loader as config_loader

    monkeypatch.setattr(config_loader, "get_magi_home", lambda: tmp_path / "host-config")
    monkeypatch.setattr(config_loader, "_loader", config_loader.ConfigLoader())
    monkeypatch.setattr(config_loader, "get_user_preference", lambda key, default=None: default)


_STORE_PATCHES: list | None = None


def _build_store_patches():
    from _shared.db_schema import apply_chain_schema

    from magi.agent.background.store import BackgroundTaskStore
    from magi.chat.store import ChatStore
    from magi.events.runtime_queue import SQLiteRuntimeCommandQueue
    from magi.memory.l1.event_store import L1EventStore
    from magi.memory.l2.entities.catalog import L2EntityCatalog
    from magi.memory.l2.store import L2CognitionStore
    from magi.memory.l3.summary_store import L3SummaryStore
    from magi.memory.l4.procedural_memory import L4ProceduralMemoryStore
    from magi.memory.unified_store import UnifiedMemoryStore
    from magi.runtime_trace.store import RuntimeTraceStore
    from magi.scheduler.repository import ScheduleRepository

    def _wrap_initialize(original, chain_paths):
        async def initialize(self, *args, **kwargs):
            for chain, path in chain_paths(self):
                apply_chain_schema(chain, path)
            return await original(self, *args, **kwargs)

        return initialize

    def _wrap_init(original, chain_paths):
        # For stores without an initialize() (schema assumed present at boot).
        def __init__(self, *args, **kwargs):
            original(self, *args, **kwargs)
            for chain, path in chain_paths(self):
                apply_chain_schema(chain, path)

        return __init__

    return [
        (
            UnifiedMemoryStore,
            "initialize",
            _wrap_initialize(
                UnifiedMemoryStore.initialize,
                lambda s: [
                    ("memory_shared", s.memory_db_path),
                    ("l1", s.l1.db_path if s.l1 is not None else None),
                ],
            ),
        ),
        (L1EventStore, "initialize", _wrap_initialize(L1EventStore.initialize, lambda s: [("l1", s.db_path)])),
        (L2CognitionStore, "initialize", _wrap_initialize(L2CognitionStore.initialize, lambda s: [("memory_shared", s.db_path)])),
        (L2EntityCatalog, "initialize", _wrap_initialize(L2EntityCatalog.initialize, lambda s: [("memory_shared", s.db_path)])),
        (L3SummaryStore, "initialize", _wrap_initialize(L3SummaryStore.initialize, lambda s: [("memory_shared", s.db_path)])),
        (
            L4ProceduralMemoryStore,
            "initialize",
            _wrap_initialize(L4ProceduralMemoryStore.initialize, lambda s: [("memory_shared", s.db_path)]),
        ),
        (RuntimeTraceStore, "initialize", _wrap_initialize(RuntimeTraceStore.initialize, lambda s: [("runtime_trace", s.db_path)])),
        (ScheduleRepository, "initialize", _wrap_initialize(ScheduleRepository.initialize, lambda s: [("scheduler", s._db_path)])),
        (ChatStore, "initialize", _wrap_initialize(ChatStore.initialize, lambda s: [("chat", s.db_path)])),
        (SQLiteRuntimeCommandQueue, "__init__", _wrap_init(SQLiteRuntimeCommandQueue.__init__, lambda s: [("message_queue", s.db_path)])),
        (BackgroundTaskStore, "__init__", _wrap_init(BackgroundTaskStore.__init__, lambda s: [("background_tasks", s.db_path)])),
    ]


@pytest.fixture(autouse=True)
def _alembic_schema_for_stores(monkeypatch):
    """Apply Alembic schema to every store-opened db file, like production boot.

    Production runs ``DatabaseMigrationModule`` before any store opens a
    connection; stores carry no DDL of their own. Tests construct stores
    against fresh tmp paths, so the owning chain is applied on first touch.
    """
    global _STORE_PATCHES
    if _STORE_PATCHES is None:
        _STORE_PATCHES = _build_store_patches()
    for cls, attr, wrapper in _STORE_PATCHES:
        monkeypatch.setattr(cls, attr, wrapper)
    yield
