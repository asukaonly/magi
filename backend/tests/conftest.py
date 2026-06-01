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
