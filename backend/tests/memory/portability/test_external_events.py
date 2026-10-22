"""Portability crosses real external event storage without reading stale local data."""

import sqlite3

from magi.memory.l1.storage.mysql.snapshots import MysqlEventStateTransfer
from magi.memory.portability.backup import build_memory_backup
from magi.memory.portability.preflight import inspect_memory_backup
from magi.memory.portability.storage import create_memory_snapshot, discard_snapshot
from magi.utils.runtime import RuntimePaths
from memory.l1.test_event_repository import command
from memory.l1.test_mysql_event_repository import mysql_environment as _mysql_environment

from ._helpers import migrate_memory_databases

mysql_environment = _mysql_environment


async def test_external_backup_uses_selected_owner_without_local_event_file(
    mysql_environment, tmp_path,
):
    repository, database = mysql_environment
    await repository.append(command("external-only"))
    paths = RuntimePaths(tmp_path / "runtime")
    migrate_memory_databases(paths)
    paths.l1_memory_db_path.unlink()
    archive = paths.memory_dir / "archive"
    archive.mkdir(exist_ok=True)
    transfer = MysqlEventStateTransfer(database, center_id="center-test")
    snapshot = await create_memory_snapshot(
        runtime_paths=paths, archive_dir=archive, unified_memory=None,
        include_l0=True, event_state_transfer=transfer,
    )
    try:
        assert snapshot.counts["l1_events"] == 1
        with sqlite3.connect(snapshot.root / "databases" / "l1_events.db") as connection:
            assert connection.execute("SELECT event_id FROM fact_events").fetchone() == ("external-only",)
        output = tmp_path / "output"
        output.mkdir()
        backup, _ = build_memory_backup(
            snapshot=snapshot, output_directory=output, encryption="none", password=None,
        )
        inspection = inspect_memory_backup(
            source_path=backup, password=None, runtime_paths=paths, archive_target=archive,
        )
        assert inspection.counts["l1_events"] == 1
        assert not paths.l1_memory_db_path.exists()
    finally:
        discard_snapshot(snapshot)
