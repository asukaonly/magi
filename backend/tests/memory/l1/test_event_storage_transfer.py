"""Real SQLite/MySQL logical round trips preserve event governance and pending work."""

import json
import sqlite3

import pytest
from sqlalchemy import select, text

from magi.core.persistence_errors import PersistenceUnavailableError
from magi.memory.l1.storage.events import SqliteMemoryEventRepository
from magi.memory.l1.storage.snapshots import SqliteEventStateTransfer
from magi.memory.l1.storage.mysql.snapshots import MysqlEventStateTransfer
from magi.memory.l1.storage.mysql import schema as s
from magi.memory.l1.storage_snapshot import EventStorageSnapshot
from .test_event_repository import command, embedding_publication
from .test_mysql_event_repository import mysql_environment  # noqa: F401


def canonical(snapshot):
    values = snapshot.model_dump(mode="json")
    for name, rows in values.items():
        if isinstance(rows, list):
            rows.sort(key=lambda row: json.dumps(row, sort_keys=True, ensure_ascii=False))
    return values


async def seed(repo):
    for name in ("ready", "pending", "deleted", "purged", "skipped"):
        value = command(name, key=name)
        value.event.timestamp = 10
        await repo.append(value)
    await repo.publish_event_embeddings([await embedding_publication(repo, "ready")])
    publication = await embedding_publication(repo, "skipped")
    await repo.remove_event_embedding_chunks([publication.source])
    await repo.complete_cognition_handoff("ready")
    await repo.retry_cognition_handoff("pending", error="needs retry", now=100)
    await repo.write_event_entities([("ready", "manual", "topic", 0.5)])
    await repo.replace_projected_event_entities_batch(
        projections=[("ready", 1, "lease", 2, 0, [("derived", "topic", 0.8)])]
    )
    await repo.soft_delete_events(["deleted", "purged"], deleted_at=101)
    await repo.purge_deleted_events(["purged"])


async def test_sqlite_mysql_sqlite_round_trip_preserves_complete_event_state(
    mysql_environment, tmp_path, ensure_db_schema
):
    remote_repo, database = mysql_environment
    source_path, target_path = str(tmp_path / "source.db"), str(tmp_path / "target.db")
    for path in (source_path, target_path):
        ensure_db_schema("l1", path)
    source_repo = SqliteMemoryEventRepository(source_path)
    await seed(source_repo)
    local = SqliteEventStateTransfer(source_path)
    snapshot = await local.export_state()
    remote = MysqlEventStateTransfer(database, center_id="center-test")
    await remote.import_state(snapshot)
    assert canonical(await remote.export_state()) == canonical(snapshot)
    assert await remote_repo.get("deleted", visibility="active") is None
    assert "ready" not in await remote_repo.list_ready_cognition_handoffs(now=1e20)
    assert "pending" not in await remote_repo.list_ready_cognition_handoffs(now=100)
    assert await remote_repo.visible_embedding_chunk_ids(["ready::chunk-0"]) == {"ready::chunk-0"}
    assert [key for key, _ in await remote_repo.bm25_search("爵士乐")]
    with pytest.raises(ValueError, match="explicit replacement"):
        await remote.import_state(snapshot)
    await remote_repo.append(command("remote-new"))
    remote_snapshot = await remote.export_state()
    target = SqliteEventStateTransfer(target_path)
    await target.import_state(remote_snapshot)
    assert canonical(await target.export_state()) == canonical(remote_snapshot)
    assert canonical(await local.export_state()) == canonical(snapshot)
    restored_repo = SqliteMemoryEventRepository(target_path)
    assert await restored_repo.get("remote-new") is not None
    assert (await restored_repo.get("skipped")).event.embedding_status == "skipped"
    assert await restored_repo.resolve_event_entities(["ready"]) == ["derived", "manual"]
    assert await restored_repo.bm25_search("爵士乐")
    assert "ready" not in await restored_repo.list_ready_cognition_handoffs(now=1e20)
    assert await restored_repo.count_events() == await remote_repo.count_events()


async def test_mysql_import_failure_preserves_previous_snapshot_and_binding(
    mysql_environment, tmp_path, ensure_db_schema
):
    repo, database = mysql_environment
    await seed(repo)
    remote = MysqlEventStateTransfer(database, center_id="center-test")
    before = await remote.export_state()
    empty = EventStorageSnapshot(event_sequence=70, entity_link_generation=9)
    async with database.transaction() as connection:
        await connection.execute(
            text(
                "CREATE TRIGGER reject_transfer BEFORE DELETE ON magi_l1_events FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='transfer interrupted'"
            )
        )
    with pytest.raises(PersistenceUnavailableError):
        await remote.import_state(empty, replace=True)
    assert canonical(await remote.export_state()) == canonical(before)
    async with database.transaction() as connection:
        assert (await connection.execute(select(s.state.c.center_id))).scalar_one() == "center-test"
        await connection.execute(text("DROP TRIGGER reject_transfer"))
    await remote.import_state(empty, replace=True)
    assert canonical(await remote.export_state()) == canonical(empty)
    await repo.append(command("new"))
    assert (await repo.get("new")).event.id == 71


async def test_sqlite_import_failure_rolls_back_all_owners(tmp_path, ensure_db_schema):
    path = str(tmp_path / "events.db")
    ensure_db_schema("l1", path)
    repo = SqliteMemoryEventRepository(path)
    await seed(repo)
    transfer = SqliteEventStateTransfer(path)
    before = await transfer.export_state()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TRIGGER reject_transfer BEFORE DELETE ON fact_events BEGIN SELECT RAISE(ABORT, 'interrupted'); END"
        )
    from magi.core.persistence_errors import PersistenceConflictError

    with pytest.raises(PersistenceConflictError):
        await transfer.import_state(
            EventStorageSnapshot(event_sequence=100, entity_link_generation=4), replace=True
        )
    assert canonical(await transfer.export_state()) == canonical(before)


def test_snapshot_rejects_unknown_codes_orphaned_rows_and_nonmonotonic_ids():
    empty = EventStorageSnapshot(event_sequence=0, entity_link_generation=0)
    assert empty.is_empty()
    with pytest.raises(ValueError, match="orphaned"):
        EventStorageSnapshot.model_validate(
            {
                **empty.model_dump(),
                "payloads": [{"event_id": "missing", "content": "x", "created_at": 1}],
            }
        )
    with pytest.raises(ValueError):
        EventStorageSnapshot.model_validate(
            {
                **empty.model_dump(),
                "embeddings": [
                    {
                        "event_id": "missing",
                        "embedding_status": 99,
                        "embedding_profile_id": None,
                        "embedding_chunk_count": 0,
                        "last_embedded_at": None,
                        "updated_at": 1,
                    }
                ],
            }
        )
