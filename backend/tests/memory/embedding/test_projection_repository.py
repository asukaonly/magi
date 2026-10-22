"""Durable remote vector intent survives restart and fences obsolete receipts."""

import pytest

from magi.memory.embedding.embedding_service import EmbeddingResult
from magi.memory.embedding.sqlite_projection import SqliteVectorProjectionRepository


@pytest.fixture
async def repository(tmp_path, ensure_db_schema):
    path = str(tmp_path / "memory.db")
    ensure_db_schema("memory_shared", path)
    repository = SqliteVectorProjectionRepository(path)
    await repository.bind("l1", "test-server")
    return repository, path


def _embedding(value=1.0):
    return EmbeddingResult(model_name="test", dimension=2, vector=[value, 0.0])


@pytest.mark.asyncio
async def test_desired_revision_and_outbox_survive_restart(repository):
    writer, path = repository
    entry = await writer.upsert(
        "l1", entity_id="event", embedding=_embedding(), metadata={"partition_value": "u1"}
    )
    restored = SqliteVectorProjectionRepository(path)
    await restored.bind("l1", "test-server")
    assert await restored.current("l1") == [entry]
    pending = await restored.pending("l1")
    assert len(pending) == 1 and pending[0].payload["vector"] == [1.0, 0.0]
    await restored.acknowledge("l1", pending[0])
    assert (await restored.current("l1"))[0].published
    assert await restored.pending("l1") == []


@pytest.mark.asyncio
async def test_obsolete_upsert_receipt_cannot_publish_replacement(repository):
    writer, _ = repository
    old = await writer.upsert("l1", entity_id="event", embedding=_embedding(), metadata=None)
    receipt = (await writer.pending("l1"))[0]
    current = await writer.upsert("l1", entity_id="event", embedding=_embedding(0.5), metadata=None)
    assert current.record_id != old.record_id and current.revision > old.revision
    await writer.acknowledge("l1", receipt)
    assert await writer.current("l1") == [current]
    pending = await writer.pending("l1")
    assert [(op.kind, op.record_id) for op in pending] == [
        ("delete", old.record_id),
        ("upsert", current.record_id),
    ]
    for operation in pending:
        await writer.acknowledge("l1", operation)
    assert (await writer.current("l1"))[0].published


@pytest.mark.asyncio
async def test_delete_cancels_payload_but_keeps_remote_cleanup(repository):
    writer, _ = repository
    old = await writer.upsert(
        "l1", entity_id="event", embedding=_embedding(), metadata={"private": "private marker"}
    )
    receipt = (await writer.pending("l1"))[0]
    await writer.delete("l1", entity_id="event")
    await writer.acknowledge("l1", receipt)
    assert await writer.current("l1") == []
    pending = await writer.pending("l1")
    assert len(pending) == 1 and pending[0].kind == "delete"
    assert pending[0].record_id == old.record_id and pending[0].payload is None


@pytest.mark.asyncio
async def test_clear_advances_generation_and_preserves_collection_cleanup(repository):
    writer, path = repository
    old = await writer.upsert("l1", entity_id="event", embedding=_embedding(), metadata=None)
    receipt = (await writer.pending("l1"))[0]
    await writer.clear("l1")
    restored = SqliteVectorProjectionRepository(path)
    await restored.acknowledge("l1", receipt)
    assert await restored.current("l1") == []
    cleanup = await restored.pending("l1")
    assert len(cleanup) == 1 and cleanup[0].kind == "clear"
    assert cleanup[0].collection_id == old.collection_id and cleanup[0].payload is None
    new = await restored.upsert("l1", entity_id="event", embedding=_embedding(), metadata=None)
    assert new.generation == old.generation + 1 and new.collection_id != old.collection_id
    await restored.acknowledge("l1", cleanup[0])
    assert await restored.current("l1") == [new]


@pytest.mark.asyncio
async def test_namespace_cannot_silently_change_remote_backend(repository):
    writer, _ = repository
    with pytest.raises(ValueError, match="explicit storage migration"):
        await writer.bind("l1", "different-server")
    await writer.bind("l1", "test-server")


@pytest.mark.asyncio
async def test_two_centers_cannot_collide_in_one_remote_database(
    repository, tmp_path, ensure_db_schema
):
    first, _ = repository
    other_path = str(tmp_path / "second.db")
    ensure_db_schema("memory_shared", other_path)
    second = SqliteVectorProjectionRepository(other_path)
    await second.bind("l1", "test-server")
    left = await first.upsert("l1", entity_id="event", embedding=_embedding(), metadata={})
    right = await second.upsert("l1", entity_id="event", embedding=_embedding(), metadata={})
    assert left.collection_id != right.collection_id
    assert left.record_id != right.record_id


@pytest.mark.asyncio
async def test_backup_excludes_remote_intents_and_restore_retains_only_local_cleanup(
    repository, tmp_path, ensure_db_schema
):
    from pathlib import Path
    from magi.memory.embedding.projection_restore import carry_forward_vector_cleanup
    from magi.memory.portability.storage import _sanitize_memory_snapshot

    live, live_path = repository
    original = await live.upsert(
        "l1", entity_id="private-live", embedding=_embedding(), metadata={}
    )
    imported_path = tmp_path / "imported.db"
    ensure_db_schema("memory_shared", str(imported_path))
    imported = SqliteVectorProjectionRepository(str(imported_path))
    await imported.bind("l1", "different-center")
    foreign = await imported.upsert(
        "l1", entity_id="private-imported", embedding=_embedding(), metadata={}
    )
    _sanitize_memory_snapshot(imported_path, include_l0=False)
    assert await imported.current("l1") == []
    assert await imported.pending("l1") == []
    assert await imported.collections("l1") == {}
    carry_forward_vector_cleanup(live_path=Path(live_path), staged_path=imported_path)
    await imported.bind("l1", "test-server")
    assert await imported.collections("l1") == {original.collection_id: False}
    assert foreign.collection_id not in await imported.collections("l1")
    assert await imported.pending("l1") == []
    assert await imported.current("l1") == []
    restored = await imported.upsert(
        "l1", entity_id="private-live", embedding=_embedding(), metadata={}
    )
    assert restored.generation > original.generation
    assert restored.collection_id != original.collection_id
    assert await live.current("l1") == [original]


@pytest.mark.asyncio
async def test_invalid_batch_does_not_leave_partial_desired_state(repository):
    writer, _ = repository
    with pytest.raises(ValueError, match="invalid embedding"):
        await writer.upsert_many(
            "l1",
            [
                {"entity_id": "valid", "embedding": _embedding()},
                {"entity_id": "invalid", "embedding": _embedding(float("nan"))},
            ],
        )
    assert await writer.current("l1") == []
    assert await writer.pending("l1") == []
