"""Concurrency tests for online sqlite-vec rebuild coordination."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest

from magi.memory.embedding.embedding_service import EmbeddingResult
from magi.memory.embedding import sqlite_vec_index as sqlite_vec_index_module
from magi.memory.embedding.sqlite_vec_index import (
    EmbeddingRebuildIdentityChangedError,
    SqliteVecIndex,
)


def _embedding(
    vector: list[float],
    *,
    identity: str = "current-model",
) -> EmbeddingResult:
    return EmbeddingResult(
        model_name="test-model",
        dimension=len(vector),
        vector=vector,
        index_identity=identity,
    )


def _index(tmp_path) -> SqliteVecIndex:
    return SqliteVecIndex(
        db_path=str(tmp_path / "vec.db"),
        registry_table="test_registry",
        entity_column="entity_id",
        vec_table_prefix="test_vec",
    )


async def _registry_models(index: SqliteVecIndex, entity_id: str) -> set[str]:
    async with index._db_lock:
        db = index._require_db()
        async with db.execute(
            "SELECT embedding_model FROM test_registry WHERE entity_id = ?",
            (entity_id,),
        ) as cursor:
            return {str(row[0]) for row in await cursor.fetchall()}


async def _cancel_commit_and_assert_rollback(
    index: SqliteVecIndex,
    monkeypatch: pytest.MonkeyPatch,
    operation: Callable[[], Awaitable[None]],
) -> None:
    db = index._require_db()
    real_commit = db.commit
    real_rollback = db.rollback
    rollback_finished = asyncio.Event()

    async def cancelled_commit() -> None:
        raise asyncio.CancelledError

    async def tracked_rollback() -> None:
        await real_rollback()
        rollback_finished.set()

    monkeypatch.setattr(db, "commit", cancelled_commit)
    monkeypatch.setattr(db, "rollback", tracked_rollback)
    try:
        with pytest.raises(asyncio.CancelledError):
            await operation()
        assert rollback_finished.is_set()
    finally:
        monkeypatch.setattr(db, "commit", real_commit)
        monkeypatch.setattr(db, "rollback", real_rollback)


@pytest.mark.asyncio
async def test_normal_upsert_wins_over_later_stale_rebuild_write(tmp_path):
    index = _index(tmp_path)
    start_normal_write = asyncio.Event()
    normal_write_finished = asyncio.Event()

    async def write_current_value() -> None:
        await start_normal_write.wait()
        await index.upsert(
            entity_id="entity-1",
            embedding=_embedding([0.0, 1.0]),
        )
        normal_write_finished.set()

    normal_writer = asyncio.create_task(write_current_value())
    try:
        async with index.rebuild_session():
            start_normal_write.set()
            await normal_write_finished.wait()
            await index.upsert(
                entity_id="entity-1",
                embedding=_embedding([1.0, 0.0]),
            )

        await normal_writer
        assert await index.get_vectors(entity_ids=["entity-1"]) == {
            "entity-1": pytest.approx([0.0, 1.0])
        }
        assert index._entity_write_epochs == {}
    finally:
        normal_writer.cancel()
        await asyncio.gather(normal_writer, return_exceptions=True)
        await index.close()


@pytest.mark.asyncio
async def test_rebuild_rejects_an_embedding_identity_change(tmp_path):
    index = _index(tmp_path)
    try:
        with pytest.raises(
            EmbeddingRebuildIdentityChangedError,
            match="identity changed",
        ):
            async with index.rebuild_session():
                await index.upsert(
                    entity_id="first",
                    embedding=_embedding([1.0, 0.0], identity="model-a"),
                )
                await index.upsert(
                    entity_id="second",
                    embedding=_embedding([0.0, 1.0], identity="model-b"),
                )

        assert await _registry_models(index, "first") == {"model-a"}
        assert await _registry_models(index, "second") == set()
    finally:
        await index.close()


@pytest.mark.asyncio
async def test_get_vectors_requires_one_identity_during_online_model_transition(tmp_path):
    index = _index(tmp_path)
    new_identity_published = asyncio.Event()
    finish_rebuild = asyncio.Event()

    async def rebuild() -> None:
        async with index.rebuild_session():
            await index.upsert(
                entity_id="entity-1",
                embedding=_embedding([0.0, 1.0, 0.0], identity="new-model"),
            )
            new_identity_published.set()
            await finish_rebuild.wait()

    rebuild_task: asyncio.Task[None] | None = None
    try:
        await index.upsert(
            entity_id="entity-1",
            embedding=_embedding([1.0, 0.0], identity="old-model"),
        )
        await index.upsert(
            entity_id="entity-2",
            embedding=_embedding([1.0, 0.0], identity="old-model"),
        )
        rebuild_task = asyncio.create_task(rebuild())
        await new_identity_published.wait()

        assert await index.get_vectors(entity_ids=["entity-1", "entity-2"]) == {}
        assert await index.get_vectors(
            entity_ids=["entity-1", "entity-2"],
            model_key="new-model",
            dimension=3,
        ) == {"entity-1": pytest.approx([0.0, 1.0, 0.0])}
        assert await index.get_vectors(
            entity_ids=["entity-1", "entity-2"],
            model_key="old-model",
            dimension=2,
        ) == {
            "entity-1": pytest.approx([1.0, 0.0]),
            "entity-2": pytest.approx([1.0, 0.0]),
        }
        finish_rebuild.set()
        await rebuild_task
    finally:
        if rebuild_task is not None:
            rebuild_task.cancel()
            await asyncio.gather(rebuild_task, return_exceptions=True)
        await index.close()


@pytest.mark.asyncio
async def test_rebuild_rejects_a_dimension_change_with_the_same_model_key(tmp_path):
    index = _index(tmp_path)
    try:
        with pytest.raises(EmbeddingRebuildIdentityChangedError):
            async with index.rebuild_session():
                await index.upsert(
                    entity_id="first",
                    embedding=_embedding([1.0, 0.0], identity="same-model"),
                )
                await index.upsert(
                    entity_id="second",
                    embedding=_embedding([0.0, 1.0, 0.0], identity="same-model"),
                )
    finally:
        await index.close()


@pytest.mark.asyncio
async def test_rebuild_rejects_an_active_profile_becoming_unavailable(tmp_path):
    index = _index(tmp_path)
    try:
        with pytest.raises(EmbeddingRebuildIdentityChangedError):
            async with index.rebuild_session():
                await index.upsert(
                    entity_id="first",
                    embedding=_embedding([1.0, 0.0], identity="model-a"),
                )
                index.verify_rebuild_target(model_key=None)
    finally:
        await index.close()


@pytest.mark.asyncio
async def test_normal_writes_do_not_accumulate_fence_state_without_a_rebuild(tmp_path):
    index = _index(tmp_path)
    try:
        for item_index in range(20):
            await index.upsert(
                entity_id=f"entity-{item_index}",
                embedding=_embedding([1.0, 0.0]),
            )

        assert index._entity_write_epochs == {}
    finally:
        await index.close()


@pytest.mark.asyncio
async def test_normal_delete_wins_over_later_stale_rebuild_write(tmp_path):
    index = _index(tmp_path)
    start_delete = asyncio.Event()
    delete_finished = asyncio.Event()
    await index.upsert(
        entity_id="entity-1",
        embedding=_embedding([0.0, 1.0]),
    )

    async def delete_current_value() -> None:
        await start_delete.wait()
        await index.delete_entity(entity_id="entity-1")
        delete_finished.set()

    normal_deleter = asyncio.create_task(delete_current_value())
    try:
        async with index.rebuild_session():
            start_delete.set()
            await delete_finished.wait()
            await index.upsert(
                entity_id="entity-1",
                embedding=_embedding([1.0, 0.0]),
            )

        await normal_deleter
        assert await index.get_vectors(entity_ids=["entity-1"]) == {}
        assert await _registry_models(index, "entity-1") == set()
    finally:
        normal_deleter.cancel()
        await asyncio.gather(normal_deleter, return_exceptions=True)
        await index.close()


@pytest.mark.asyncio
async def test_normal_write_on_a_second_index_instance_wins_over_rebuild(tmp_path):
    rebuild_index = _index(tmp_path)
    normal_index = _index(tmp_path)
    try:
        async with rebuild_index.rebuild_session():
            await normal_index.upsert(
                entity_id="entity-1",
                embedding=_embedding([0.0, 1.0]),
            )
            await rebuild_index.upsert(
                entity_id="entity-1",
                embedding=_embedding([1.0, 0.0]),
            )

        assert await rebuild_index.get_vectors(entity_ids=["entity-1"]) == {
            "entity-1": pytest.approx([0.0, 1.0])
        }
    finally:
        await rebuild_index.close()
        await normal_index.close()


@pytest.mark.asyncio
async def test_commit_cancellation_cannot_unfence_a_committed_normal_write(
    tmp_path,
    monkeypatch,
):
    rebuild_index = _index(tmp_path)
    normal_index = _index(tmp_path)
    await normal_index.initialize()
    db = normal_index._require_db()
    real_commit = db.commit

    async def committed_then_cancelled() -> None:
        await real_commit()
        raise asyncio.CancelledError

    monkeypatch.setattr(db, "commit", committed_then_cancelled)
    try:
        async with rebuild_index.rebuild_session():
            with pytest.raises(asyncio.CancelledError):
                await normal_index.upsert(
                    entity_id="entity-1",
                    embedding=_embedding([0.0, 1.0]),
                )
            await rebuild_index.upsert(
                entity_id="entity-1",
                embedding=_embedding([1.0, 0.0]),
            )

        assert await rebuild_index.get_vectors(entity_ids=["entity-1"]) == {
            "entity-1": pytest.approx([0.0, 1.0])
        }
    finally:
        monkeypatch.setattr(db, "commit", real_commit)
        await rebuild_index.close()
        await normal_index.close()


@pytest.mark.asyncio
async def test_successful_rebuild_retires_only_refreshed_entity_old_models(tmp_path):
    index = _index(tmp_path)
    try:
        await index.upsert(
            entity_id="refreshed",
            embedding=_embedding([1.0, 0.0], identity="old-model"),
        )
        await index.upsert(
            entity_id="untouched",
            embedding=_embedding([1.0, 0.0], identity="old-model"),
        )

        async with index.rebuild_session():
            await index.upsert(
                entity_id="refreshed",
                embedding=_embedding([0.0, 1.0], identity="new-model"),
            )
            assert await _registry_models(index, "refreshed") == {
                "old-model",
                "new-model",
            }

        assert await _registry_models(index, "refreshed") == {"new-model"}
        assert await _registry_models(index, "untouched") == {"old-model"}
    finally:
        await index.close()


@pytest.mark.asyncio
async def test_discarded_rebuild_embedding_keeps_the_old_model_copy(tmp_path):
    index = _index(tmp_path)
    old_embedding = _embedding([1.0, 0.0], identity="old-model")
    new_embedding = _embedding([0.0, 1.0], identity="new-model")
    try:
        await index.upsert(entity_id="entity-1", embedding=old_embedding)

        async with index.rebuild_session():
            await index.upsert(entity_id="entity-1", embedding=new_embedding)
            await index.delete_embedding(
                entity_id="entity-1",
                embedding=new_embedding,
            )

        assert await _registry_models(index, "entity-1") == {"old-model"}
    finally:
        await index.close()


@pytest.mark.asyncio
async def test_failed_rebuild_preserves_old_model_rows(tmp_path):
    index = _index(tmp_path)
    try:
        await index.upsert(
            entity_id="entity-1",
            embedding=_embedding([1.0, 0.0], identity="old-model"),
        )

        with pytest.raises(RuntimeError, match="rebuild failed"):
            async with index.rebuild_session():
                await index.upsert(
                    entity_id="entity-1",
                    embedding=_embedding([0.0, 1.0], identity="new-model"),
                )
                raise RuntimeError("rebuild failed")

        assert await _registry_models(index, "entity-1") == {
            "old-model",
            "new-model",
        }
        old_hits = await index.search(
            embedding=_embedding([1.0, 0.0], identity="old-model"),
            limit=1,
        )
        assert [hit.entity_id for hit in old_hits] == ["entity-1"]
    finally:
        await index.close()


@pytest.mark.asyncio
async def test_successful_rebuild_prunes_vectors_without_a_valid_parent(tmp_path):
    index = _index(tmp_path)
    try:
        await index.initialize()
        async with index._db_lock:
            db = index._require_db()
            await db.execute("CREATE TABLE valid_entities(entity_id TEXT PRIMARY KEY)")
            await db.execute("INSERT INTO valid_entities(entity_id) VALUES ('valid')")
            await db.commit()
        await index.upsert(entity_id="valid", embedding=_embedding([1.0, 0.0]))
        await index.upsert(entity_id="orphan", embedding=_embedding([0.0, 1.0]))

        async with index.rebuild_session():
            pruned = await index.prune_orphans(
                valid_entity_query="SELECT entity_id FROM valid_entities"
            )

        assert pruned == 1
        assert set(await index.get_vectors(entity_ids=["valid", "orphan"])) == {"valid"}
    finally:
        await index.close()


@pytest.mark.asyncio
async def test_cancelled_rebuild_preserves_old_model_rows(tmp_path):
    index = _index(tmp_path)
    rebuild_waiting = asyncio.Event()
    never_finish = asyncio.Event()
    await index.upsert(
        entity_id="entity-1",
        embedding=_embedding([1.0, 0.0], identity="old-model"),
    )

    async def rebuild() -> None:
        async with index.rebuild_session():
            await index.upsert(
                entity_id="entity-1",
                embedding=_embedding([0.0, 1.0], identity="new-model"),
            )
            rebuild_waiting.set()
            await never_finish.wait()

    rebuild_task = asyncio.create_task(rebuild())
    try:
        await rebuild_waiting.wait()
        rebuild_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await rebuild_task

        assert await _registry_models(index, "entity-1") == {
            "old-model",
            "new-model",
        }
    finally:
        rebuild_task.cancel()
        await asyncio.gather(rebuild_task, return_exceptions=True)
        await index.close()


@pytest.mark.asyncio
async def test_failed_same_model_rebuild_keeps_successfully_published_vector(tmp_path):
    index = _index(tmp_path)
    try:
        await index.upsert(
            entity_id="entity-1",
            embedding=_embedding([1.0, 0.0]),
            metadata={"version": "before"},
        )

        with pytest.raises(RuntimeError, match="rebuild failed"):
            async with index.rebuild_session():
                await index.upsert(
                    entity_id="entity-1",
                    embedding=_embedding([0.0, 1.0]),
                    metadata={"version": "during"},
                )
                raise RuntimeError("rebuild failed")

        vectors = await index.get_vectors(entity_ids=["entity-1"])
        assert vectors["entity-1"] == pytest.approx([0.0, 1.0])
        async with index._db_lock:
            db = index._require_db()
            async with db.execute(
                "SELECT metadata FROM test_registry WHERE entity_id = ?",
                ("entity-1",),
            ) as cursor:
                row = await cursor.fetchone()
        assert row is not None
        assert row["metadata"] == '{"version": "during"}'
    finally:
        await index.close()


@pytest.mark.asyncio
async def test_rebuild_sessions_are_exclusive_per_index_instance(tmp_path):
    index = _index(tmp_path)
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    second_started = asyncio.Event()
    second_entered = asyncio.Event()

    async def first_rebuild() -> None:
        async with index.rebuild_session():
            first_entered.set()
            await release_first.wait()

    async def second_rebuild() -> None:
        second_started.set()
        async with index.rebuild_session():
            second_entered.set()

    first_task = asyncio.create_task(first_rebuild())
    second_task: asyncio.Task[None] | None = None
    try:
        await first_entered.wait()
        second_task = asyncio.create_task(second_rebuild())
        await second_started.wait()
        assert not second_entered.is_set()

        release_first.set()
        await second_entered.wait()
        await asyncio.gather(first_task, second_task)
    finally:
        release_first.set()
        first_task.cancel()
        if second_task is not None:
            second_task.cancel()
        await asyncio.gather(
            first_task,
            *(task for task in [second_task] if task is not None),
            return_exceptions=True,
        )
        await index.close()


@pytest.mark.asyncio
async def test_concurrent_initialize_opens_one_connection(tmp_path, monkeypatch):
    index = _index(tmp_path)
    real_connect = sqlite_vec_index_module.connect_aiosqlite
    first_connect_started = asyncio.Event()
    release_first_connect = asyncio.Event()
    second_initialize_started = asyncio.Event()
    connect_calls = 0

    async def tracked_connect(*args, **kwargs):
        nonlocal connect_calls
        connect_calls += 1
        first_connect_started.set()
        await release_first_connect.wait()
        return await real_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite_vec_index_module, "connect_aiosqlite", tracked_connect)

    async def initialize_second() -> None:
        second_initialize_started.set()
        await index.initialize()

    first_task = asyncio.create_task(index.initialize())
    second_task: asyncio.Task[None] | None = None
    try:
        await first_connect_started.wait()
        second_task = asyncio.create_task(initialize_second())
        await second_initialize_started.wait()
        assert connect_calls == 1

        release_first_connect.set()
        await asyncio.gather(first_task, second_task)
        assert connect_calls == 1
    finally:
        release_first_connect.set()
        first_task.cancel()
        if second_task is not None:
            second_task.cancel()
        await asyncio.gather(
            first_task,
            *(task for task in [second_task] if task is not None),
            return_exceptions=True,
        )
        await index.close()


@pytest.mark.asyncio
async def test_cancelled_upsert_rolls_back_persistent_connection(tmp_path, monkeypatch):
    index = _index(tmp_path)
    await index.initialize()
    try:
        await _cancel_commit_and_assert_rollback(
            index,
            monkeypatch,
            lambda: index.upsert(
                entity_id="cancelled",
                embedding=_embedding([1.0, 0.0]),
            ),
        )

        assert await _registry_models(index, "cancelled") == set()
        await index.upsert(
            entity_id="after-cancellation",
            embedding=_embedding([0.0, 1.0]),
        )
        assert await _registry_models(index, "after-cancellation") == {"current-model"}
    finally:
        await index.close()


@pytest.mark.asyncio
async def test_cancelled_delete_rolls_back_persistent_connection(tmp_path, monkeypatch):
    index = _index(tmp_path)
    await index.upsert(
        entity_id="entity-1",
        embedding=_embedding([1.0, 0.0]),
    )
    try:
        await _cancel_commit_and_assert_rollback(
            index,
            monkeypatch,
            lambda: index.delete_entity(entity_id="entity-1"),
        )

        assert await _registry_models(index, "entity-1") == {"current-model"}
        assert set(await index.get_vectors(entity_ids=["entity-1"])) == {"entity-1"}
    finally:
        await index.close()


@pytest.mark.asyncio
async def test_cancelled_clear_rolls_back_persistent_connection(tmp_path, monkeypatch):
    index = _index(tmp_path)
    await index.upsert(
        entity_id="entity-1",
        embedding=_embedding([1.0, 0.0]),
    )
    try:
        await _cancel_commit_and_assert_rollback(index, monkeypatch, index.clear)

        assert await _registry_models(index, "entity-1") == {"current-model"}
        assert set(await index.get_vectors(entity_ids=["entity-1"])) == {"entity-1"}
    finally:
        await index.close()
