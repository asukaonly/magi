"""Offline cutover and restart fences for external event storage."""

import pytest
from sqlalchemy import text
from uuid import uuid4

from channels.test_storage_transfer import environment as _channel_environment
from magi.bootstrap.event_storage import (
    binding_file,
    compose_event_repository,
    migrate_event_storage,
    preflight_storage_selection,
    storage_target,
)
from magi.db.mysql import MysqlDatabase
from magi.db.logical_transfer import snapshot_digest
from magi.db.storage_bindings import StorageBindingFile
from magi.memory.l1.storage.events import SqliteMemoryEventRepository
from magi.memory.l1.storage.snapshots import SqliteEventStateTransfer
from magi.memory.l1.storage.mysql.snapshots import MysqlEventStateTransfer
from .test_event_repository import command

environment = _channel_environment


@pytest.fixture
async def event_environment(environment, ensure_db_schema):
    paths, config = environment
    ensure_db_schema("l1", paths.l1_memory_db_path)
    yield paths, config.mysql


async def test_live_selection_requires_explicit_verified_cutover(event_environment):
    paths, settings = event_environment
    source = SqliteMemoryEventRepository(str(paths.l1_memory_db_path))
    await source.append(command("local-source"))
    before = await SqliteEventStateTransfer(str(paths.l1_memory_db_path)).export_state()
    with pytest.raises(RuntimeError, match="Local memory events"):
        await preflight_storage_selection(paths, "mysql", settings)
    await migrate_event_storage(paths, destination="mysql", mysql=settings)
    database = MysqlDatabase(settings)
    try:
        repository = await compose_event_repository(paths, "mysql", settings, database)
        assert await repository.get("local-source") is not None
        await repository.append(command("new-remote"))
        with pytest.raises(RuntimeError, match="storage changed"):
            await compose_event_repository(paths, "sqlite", settings, None)
        with pytest.raises(ValueError, match="Destination has data"):
            await migrate_event_storage(paths, destination="sqlite", mysql=settings)
        await migrate_event_storage(
            paths, destination="sqlite", mysql=settings, replace_destination=True
        )
        restored = await compose_event_repository(paths, "sqlite", settings, None)
        assert await restored.get("new-remote") is not None
        assert snapshot_digest(
            await SqliteEventStateTransfer(str(paths.l1_memory_db_path)).export_state()
        ) != snapshot_digest(before)
        assert await repository.get("new-remote") is not None
    finally:
        await database.close()


async def test_cutover_crash_retains_intent_and_resumes_exact_snapshot(
    event_environment, monkeypatch
):
    paths, settings = event_environment
    source = SqliteMemoryEventRepository(str(paths.l1_memory_db_path))
    await source.append(command("source"))
    original = StorageBindingFile.write
    interrupted = False

    def fail_activation(self, binding):
        nonlocal interrupted
        if (
            binding.active is not None
            and binding.active.kind == "mysql"
            and binding.pending is None
            and not interrupted
        ):
            interrupted = True
            raise OSError("interrupted activation")
        original(self, binding)

    monkeypatch.setattr(StorageBindingFile, "write", fail_activation)
    with pytest.raises(OSError, match="interrupted"):
        await migrate_event_storage(paths, destination="mysql", mysql=settings)
    assert binding_file(paths).read_or_create().pending is not None
    with pytest.raises(RuntimeError, match="incomplete"):
        await preflight_storage_selection(paths, "mysql", settings)
    await migrate_event_storage(paths, destination="mysql", mysql=settings)
    binding = binding_file(paths).read_or_create()
    assert binding.pending is None
    assert binding.active == storage_target("mysql", settings)
    database = MysqlDatabase(settings)
    try:
        remote = MysqlEventStateTransfer(database, center_id=binding.center_id)
        assert snapshot_digest(await remote.export_state()) == snapshot_digest(
            await SqliteEventStateTransfer(str(paths.l1_memory_db_path)).export_state()
        )
    finally:
        await database.close()


async def test_remote_to_remote_cutover_requires_the_original_source(event_environment):
    paths, settings = event_environment
    await SqliteMemoryEventRepository(str(paths.l1_memory_db_path)).append(command("retained"))
    await migrate_event_storage(paths, destination="mysql", mysql=settings)
    admin = MysqlDatabase(settings)
    name = "magi_test_event_destination_" + uuid4().hex
    async with admin.transaction() as connection:
        await connection.execute(
            text(f"CREATE DATABASE {name} CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin")
        )
    target_settings = settings.model_copy(update={"database": name})
    target_database = MysqlDatabase(target_settings)
    try:
        with pytest.raises(ValueError, match="Source MySQL settings"):
            await migrate_event_storage(paths, destination="mysql", mysql=target_settings)
        await migrate_event_storage(
            paths, destination="mysql", mysql=target_settings, source_mysql=settings
        )
        repository = await compose_event_repository(
            paths, "mysql", target_settings, target_database
        )
        assert await repository.get("retained") is not None
        source_snapshot = await MysqlEventStateTransfer(
            admin, center_id=binding_file(paths).read_or_create().center_id
        ).export_state()
        assert [row.event_id for row in source_snapshot.facts] == ["retained"]
    finally:
        await target_database.close()
        async with admin.transaction() as connection:
            await connection.execute(text(f"DROP DATABASE {name}"))
        await admin.close()


async def test_runtime_composes_mysql_events_with_local_channels_and_shared_pool(event_environment):
    from magi.bootstrap.context import RuntimeBootstrapContext
    from magi.bootstrap.structured_storage import StructuredStorageModule
    from magi.config.models import AppConfig
    from magi.config.storage_models import StructuredStorageSettings
    from magi.memory.l1.storage.mysql.events import MysqlMemoryEventRepository
    from magi.memory.lifecycle import MemoryStoreModule
    from types import SimpleNamespace

    paths, settings = event_environment
    context = RuntimeBootstrapContext()
    context.core.runtime_paths = paths
    context.core.config = AppConfig(
        structured_storage=StructuredStorageSettings(memory_events="mysql", mysql=settings)
    )
    module = StructuredStorageModule(context)
    await module.init()
    try:
        assert isinstance(context.memory.event_repository, MysqlMemoryEventRepository)
        assert context.memory.event_repository._database is module._mysql
        memory = MemoryStoreModule(context, enable_embedding=False)._build_unified_memory_store(
            runtime_paths=paths,
            scenario_llm_pool=None,
            plugin_projection_service=SimpleNamespace(
                build_temporal_summary_features=lambda: {}, iter_extraction_profiles=lambda: []
            ),
            memory_config=context.core.config.agent.memory,
        )
        assert memory.l1.event_repository is context.memory.event_repository
        await memory.l1.initialize(start_workers=False)
        await memory.l1.store(command("persisted").event)
        assert (await context.memory.event_state_transfer.export_state()).facts[
            0
        ].event_id == "persisted"
        await memory.l1.shutdown()
    finally:
        await module.shutdown()
    assert context.memory.event_repository is None
    assert context.memory.event_state_transfer is None
    assert module._mysql is None
    await module.init()
    try:
        assert await context.memory.event_repository.get("persisted") is not None
    finally:
        await module.shutdown()


def test_transfer_cli_refuses_a_running_center_before_loading_config(tmp_path, monkeypatch):
    from magi.bootstrap.event_storage_transfer import main
    from magi.utils.worker_instance import WorkerInstance

    monkeypatch.setattr(
        "sys.argv", ["event-storage", "--root", str(tmp_path), "--target", "sqlite"]
    )
    with WorkerInstance(tmp_path):
        with pytest.raises(RuntimeError, match="already owns"):
            main()
    assert not (tmp_path / "data/memory/event-storage-binding.json").exists()


async def test_transfer_cli_uses_configured_target_under_offline_lease(
    event_environment, monkeypatch
):
    import asyncio
    import yaml
    from magi.bootstrap.event_storage_transfer import main

    paths, settings = event_environment
    await SqliteMemoryEventRepository(str(paths.l1_memory_db_path)).append(command("cli-source"))
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    (paths.config_dir / "agent.yaml").write_text(
        yaml.safe_dump(
            {
                "structured_storage": {
                    "memory_events": "mysql",
                    "mysql": settings.model_dump(mode="json"),
                }
            }
        )
    )
    monkeypatch.setattr(
        "sys.argv", ["event-storage", "--root", str(paths.base_dir), "--target", "mysql"]
    )
    await asyncio.to_thread(main)
    binding = binding_file(paths).read_or_create()
    assert binding.pending is None
    assert binding.active == storage_target("mysql", settings)
