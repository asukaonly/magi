"""Memory-suite fixtures.

The schema bootstrap (autouse store-initialize wrapper + the generic
``ensure_db_schema`` callable) and the hermetic user-preference guard live in
the ROOT ``tests/conftest.py`` — integration/agent suites construct memory
stores against tmp paths too. This file only keeps the memory-local alias.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def ensure_memory_schema(ensure_db_schema):
    """Callable ``(chain, db_path)`` for tests that open db files directly.

    Store-constructing tests are covered by the root autouse wrapper; tests
    that hand a raw path to ``sqlite_connection_async`` (e.g. the L4
    maintenance/soft-delete suites, whose legacy ``ensure_*_schema`` helpers
    are now alembic-managed no-ops) request this fixture and apply the chain
    themselves.
    """
    return ensure_db_schema
