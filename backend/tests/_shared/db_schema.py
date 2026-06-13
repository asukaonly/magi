"""Generic per-file schema bootstrap for ANY alembic chain.

All runtime SQLite schemas are alembic-owned (``magi.db``); the legacy
in-store DDL was removed, so any test that opens a store against a fresh
tmp-path db file must apply the owning chain first — exactly what
production's ``DatabaseMigrationModule`` does at boot.

``apply_chain_schema(chain, db_path)`` migrates each chain ONCE per process
into a template db and file-copies it for fresh paths (an Alembic run costs
~100ms, a copy is ~free). Unlike ``memory_schema.py`` (hand-maintained
migration list, memory_shared only) this runs the real ``upgrade head``, so
new migrations are picked up automatically for every chain.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from pathlib import Path

_TEMPLATES: dict[str, Path] = {}
_HANDLED: set[tuple[str, str]] = set()


def _migrate_chain(chain: str, db_path: Path) -> None:
    from alembic import command

    from magi.db.runner import MIGRATION_TARGETS, _build_config

    target = next(t for t in MIGRATION_TARGETS if t.name == chain)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(_build_config(target, db_path), "head")


def _has_alembic_stamp(path: Path) -> bool:
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'"
        ).fetchone()
    return row is not None


def apply_chain_schema(chain: str, db_path) -> None:
    """Bring ``db_path`` to the head of ``chain``.

    Three cases:
    - file absent  -> copy a pre-migrated template (the common case)
    - file present with an ``alembic_version`` stamp -> ``upgrade head``
    - file present WITHOUT a stamp -> leave untouched (the test hand-built
      its own schema; running the chain from scratch would collide)
    """
    if not db_path:
        return
    path = Path(db_path).expanduser()
    key = (chain, str(path))
    if key in _HANDLED:
        return
    template = _TEMPLATES.get(chain)
    if template is None:
        template = Path(tempfile.mkdtemp(prefix=f"magi-schema-{chain}-")) / "template.db"
        _migrate_chain(chain, template)
        _TEMPLATES[chain] = template
    if path.exists():
        if _has_alembic_stamp(path):
            _migrate_chain(chain, path)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(template, path)
    _HANDLED.add(key)


__all__ = ["apply_chain_schema"]
