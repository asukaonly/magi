"""Runtime hooks for Alembic-managed schema migrations.

Each runtime SQLite database that participates in Alembic has its
schema versioned by an environment under ``magi/db/migrations/<name>``.
At process startup, ``DatabaseMigrationModule`` (``db/lifecycle.py``)
calls ``run_upgrade_head`` for each registered target after the runtime
paths have been resolved; this brings the on-disk schema up to the
latest committed revision before any store opens its connection.

Migration files are written by hand (no SQLAlchemy models, no
autogenerate). The ``v1`` revision in each environment loads the
canonical baseline DDL via ``op.executescript``; later revisions use
the high-level ``op.add_column`` / ``op.create_index`` APIs.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Callable, Iterable

from alembic import command
from alembic.config import Config

from ..core.logger import get_logger
from ..utils.runtime import RuntimePaths

logger = get_logger(__name__)

_MIGRATIONS_ROOT = Path(__file__).resolve().parent / "migrations"


@dataclass(frozen=True)
class MigrationTarget:
    """A single Alembic environment driving one runtime SQLite file."""

    name: str
    """Environment name (matches the directory under ``migrations/``)."""

    db_path: Callable[[RuntimePaths], Path]
    """Resolves the DB file path from the active runtime paths."""

    def script_location(self) -> Path:
        return _MIGRATIONS_ROOT / self.name


MIGRATION_TARGETS: tuple[MigrationTarget, ...] = (
    MigrationTarget(name="chat", db_path=lambda rp: rp.chat_db_path),
    MigrationTarget(name="l1", db_path=lambda rp: rp.l1_memory_db_path),
    MigrationTarget(name="memory_shared", db_path=lambda rp: rp.memory_db_path),
    MigrationTarget(name="runtime_trace", db_path=lambda rp: rp.runtime_trace_db_path),
    MigrationTarget(name="llm_usage", db_path=lambda rp: rp.llm_usage_db_path),
    MigrationTarget(
        name="persona_registry",
        db_path=lambda rp: rp.persona_registry_db_path,
    ),
    MigrationTarget(name="behavior_evolution", db_path=lambda rp: rp.behavior_db_path),
    MigrationTarget(name="emotional", db_path=lambda rp: rp.emotional_db_path),
    MigrationTarget(name="growth_memory", db_path=lambda rp: rp.growth_db_path),
    MigrationTarget(name="scheduler", db_path=lambda rp: rp.scheduler_db_path),
    MigrationTarget(name="sensor_state", db_path=lambda rp: rp.sensor_state_db_path),
    MigrationTarget(
        name="background_tasks",
        db_path=lambda rp: rp.background_tasks_db_path,
    ),
    MigrationTarget(
        name="message_queue",
        db_path=lambda rp: rp.message_queue_db_path,
    ),
    MigrationTarget(
        name="permission_rules",
        db_path=lambda rp: rp.permission_rules_db_path,
    ),
    MigrationTarget(name="channels", db_path=lambda rp: rp.channels_db_path),
    MigrationTarget(name="identity", db_path=lambda rp: rp.identity_db_path),
    MigrationTarget(name="batch", db_path=lambda rp: rp.batch_db_path),
)


def _build_config(target: MigrationTarget, db_path: Path) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(target.script_location()))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    cfg.set_main_option("version_path_separator", "os")
    return cfg


def run_upgrade_head(
    runtime_paths: RuntimePaths,
    *,
    targets: Iterable[MigrationTarget] | None = None,
) -> None:
    """Run ``alembic upgrade head`` for every registered migration target.

    ``targets`` is a hook for tests or partial rollouts; production
    callers omit it to upgrade everything.
    """
    selected = tuple(targets) if targets is not None else MIGRATION_TARGETS
    for target in selected:
        db_path = target.db_path(runtime_paths)
        before = _database_file_snapshot(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        cfg = _build_config(target, db_path)
        logger.info(
            "Database migration started",
            process_id=os.getpid(),
            target=target.name,
            db_path=str(db_path),
            existed_before=before["exists"],
            identity_before=before["identity"],
        )
        command.upgrade(cfg, "head")
        after = _database_file_snapshot(db_path)
        logger.info(
            "Database migration completed",
            process_id=os.getpid(),
            target=target.name,
            db_path=str(db_path),
            identity_after=after["identity"],
            size_bytes=after["size_bytes"],
        )


def _database_file_snapshot(db_path: Path) -> dict[str, Any]:
    """Return non-content file identity fields for startup diagnostics."""

    try:
        details = db_path.stat()
    except FileNotFoundError:
        return {
            "exists": False,
            "identity": None,
            "size_bytes": None,
        }
    except OSError:
        return {
            "exists": None,
            "identity": None,
            "size_bytes": None,
        }
    return {
        "exists": True,
        "identity": f"{details.st_dev}:{details.st_ino}",
        "size_bytes": int(details.st_size),
    }
