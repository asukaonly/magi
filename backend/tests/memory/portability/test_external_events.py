"""Portability crosses real external event storage without reading stale local data."""

import asyncio
import sqlite3

import pytest
import yaml

from _shared.storage_plugins import mysql_settings, mysql_package, install_mysql, select
from magi.bootstrap.storage_selection import binding_file
from magi.bootstrap.storage_transfer import migrate_storage
from magi.config.storage_models import StructuredStorageSettings
from magi.bootstrap.portable_event_storage import open_portable_event_storage
from magi.db.logical_transfer import snapshot_digest

from _shared.mysql_storage_plugin.events.snapshots import MysqlEventStateTransfer
from magi.memory.portability.backup import build_memory_backup
from magi.memory.portability.preflight import inspect_memory_backup
from magi.memory.portability.storage import create_memory_snapshot, discard_snapshot
from magi.memory.portability.recovery import read_restore_journal, recover_pending_memory_restore
from magi.memory.portability.restore import prepare_memory_restore
from magi.utils.runtime import RuntimePaths
from memory.l1.test_event_repository import command
from memory.l1.test_mysql_event_repository import mysql_environment as _mysql_environment

from ._helpers import migrate_memory_databases
from .test_restore_recovery import SimulatedProcessCrash, _create_scenario

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


@pytest.fixture
async def external_scenario(mysql_settings, mysql_package, tmp_path):
    scenario = _create_scenario(tmp_path / "restore")
    paths = scenario.runtime_paths
    remote = await install_mysql(paths, mysql_package, mysql_settings)
    settings = StructuredStorageSettings(memory_events=remote)
    select(paths, settings)
    await migrate_storage(paths, "memory_events")
    return scenario, settings


@pytest.mark.parametrize("failure", ["after_l1_cutover", "after_memory_cutover", "after_cutover_complete"])
async def test_external_cutover_crash_recovers_exact_remote_state(external_scenario, failure):
    scenario, _settings = external_scenario
    paths = scenario.runtime_paths
    local_bytes = paths.l1_memory_db_path.read_bytes()
    async with open_portable_event_storage(paths) as storage:
        before = await storage.transfer.export_state()

    def crash(phase):
        if phase == failure:
            raise SimulatedProcessCrash()

    transaction = await prepare_memory_restore(
        candidate=scenario.candidate, runtime_paths=paths, failpoint=crash,
    )
    assert read_restore_journal(paths).external_events.center_id == binding_file(paths, "memory_events").read_or_create().center_id
    with pytest.raises(SimulatedProcessCrash):
        await asyncio.to_thread(transaction.cutover)
    async with open_portable_event_storage(paths) as storage:
        assert [fact.event_id for fact in (await storage.transfer.export_state()).facts] == ["event-new"]
    assert await asyncio.to_thread(recover_pending_memory_restore, paths) == "rolled_back"
    async with open_portable_event_storage(paths) as storage:
        assert snapshot_digest(await storage.transfer.export_state()) == snapshot_digest(before)
    assert paths.l1_memory_db_path.read_bytes() == local_bytes
    assert read_restore_journal(paths) is None


async def test_external_restore_commit_does_not_restore_inactive_local_file(external_scenario):
    scenario, _settings = external_scenario
    paths = scenario.runtime_paths
    paths.l1_memory_db_path.unlink()
    transaction = await prepare_memory_restore(candidate=scenario.candidate, runtime_paths=paths)
    await asyncio.to_thread(transaction.cutover)
    await asyncio.to_thread(transaction.commit)
    assert await asyncio.to_thread(recover_pending_memory_restore, paths) == "committed"
    async with open_portable_event_storage(paths) as storage:
        assert [fact.event_id for fact in (await storage.transfer.export_state()).facts] == ["event-new"]
    assert not paths.l1_memory_db_path.exists()


async def test_external_recovery_blocks_changed_configuration_and_retains_rollback(external_scenario):
    scenario, settings = external_scenario
    paths = scenario.runtime_paths
    transaction = await prepare_memory_restore(candidate=scenario.candidate, runtime_paths=paths)
    await asyncio.to_thread(transaction.cutover)
    config_file = paths.base_dir / "config" / "agent.yaml"
    select(paths, StructuredStorageSettings())
    with pytest.raises(RuntimeError, match="active owner"):
        await asyncio.to_thread(recover_pending_memory_restore, paths)
    assert read_restore_journal(paths) is not None
    select(paths, settings)
    assert await asyncio.to_thread(recover_pending_memory_restore, paths) == "rolled_back"
