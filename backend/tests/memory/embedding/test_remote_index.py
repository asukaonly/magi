"""Remote failures, immutable records and rebuild fences using the real journal."""

import asyncio
import math
import os

import pytest

from magi.config.memory_models import ChromaVectorSettings
from magi.memory.embedding.chroma_client import ChromaVectorClient
from magi.memory.embedding.embedding_service import EmbeddingResult
from magi.memory.embedding.ports import EmbeddingRebuildIdentityChangedError
from magi.memory.embedding.remote_index import RemoteVectorHit, RemoteVectorIndex
from magi.memory.embedding.sqlite_projection import SqliteVectorProjectionRepository


class FakeRemote:
    def __init__(self):
        self.data = {}
        self.fail = False
        self.attempted = []

    async def apply(self, operation):
        self.attempted.append(operation)
        if self.fail:
            raise TimeoutError("Remote outcome is unknown")
        if operation.kind == "upsert":
            self.data.setdefault(operation.collection_id, {})[operation.record_id] = (
                operation.payload
            )
        elif operation.kind == "delete":
            self.data.get(operation.collection_id, {}).pop(operation.record_id, None)
        else:
            self.data.pop(operation.collection_id, None)

    async def search(self, collection, vector, limit, partition):
        hits = [
            RemoteVectorHit(key, value["entity_id"], math.dist(vector, value["vector"]))
            for key, value in self.data.get(collection, {}).items()
            if partition is None or value["metadata"].get("partition_value") == partition
        ]
        return sorted(hits, key=lambda hit: hit.distance)[:limit]

    async def vectors(self, collection, record_ids):
        return {
            key: value["vector"]
            for key, value in self.data.get(collection, {}).items()
            if key in record_ids
        }

    async def reconcile(self, collection, current_ids):
        if current_ids is None:
            self.data.pop(collection, None)
        else:
            current = await current_ids(list(self.data.get(collection, {})))
            self.data[collection] = {
                key: value
                for key, value in self.data.get(collection, {}).items()
                if key in current
            }


def embedding(value=1.0, model="test"):
    return EmbeddingResult(model_name=model, dimension=2, vector=[value, 0.0])


@pytest.fixture
async def setup_index(tmp_path, ensure_db_schema):
    path = str(tmp_path / "memory.db")
    ensure_db_schema("memory_shared", path)
    repository = SqliteVectorProjectionRepository(path)
    remote = FakeRemote()
    indexes = []

    def create(client=remote):
        index = RemoteVectorIndex(
            namespace="l1",
            backend_identity="test-server",
            repository=repository,
            client=client,
            retry_interval=3600,
        )
        indexes.append(index)
        return index

    yield create, remote, repository
    for index in indexes:
        await index.clear()
        await index.close()


@pytest.mark.asyncio
async def test_restart_replays_durable_intent_without_reembedding(setup_index):
    create, remote, repository = setup_index
    index = create()
    remote.fail = True
    with pytest.raises(TimeoutError):
        await index.upsert(entity_id="event", embedding=embedding())
    await index.close()
    remote.fail = False
    recovered = create()
    await recovered.flush()
    assert await repository.pending("l1") == []
    assert await recovered.get_vectors(entity_ids=["event"]) == {"event": [1.0, 0.0]}


@pytest.mark.asyncio
async def test_late_superseded_write_is_invisible_and_reconciled(setup_index):
    create, remote, repository = setup_index
    index = create()
    remote.fail = True
    with pytest.raises(TimeoutError):
        await index.upsert(entity_id="event", embedding=embedding(1))
    late = remote.attempted[-1]
    remote.fail = False
    await index.upsert(entity_id="event", embedding=embedding(5))
    await remote.apply(late)
    hits = await index.search(embedding=embedding(1), limit=5)
    assert [(hit.entity_id, hit.distance) for hit in hits] == [("event", 4.0)]
    await index.flush()
    collection = (await repository.current("l1"))[0].collection_id
    assert len(remote.data[collection]) == 1


@pytest.mark.asyncio
async def test_deleted_and_cleared_late_writes_never_reappear(setup_index):
    create, remote, repository = setup_index
    index = create()
    await index.upsert(entity_id="deleted", embedding=embedding())
    late_delete = remote.attempted[-1]
    await index.delete_entity(entity_id="deleted")
    await remote.apply(late_delete)
    assert await index.search(embedding=embedding(), limit=2) == []
    await index.upsert(entity_id="cleared", embedding=embedding())
    late_clear = remote.attempted[-1]
    await index.clear()
    await remote.apply(late_clear)
    await index.close()
    recovered = create()
    await recovered.flush()
    assert await recovered.search(embedding=embedding(), limit=2) == []
    assert late_clear.collection_id not in remote.data
    assert await repository.current("l1") == []


@pytest.mark.asyncio
async def test_rebuild_preserves_newer_ingestion_and_old_models_on_failure(setup_index):
    create, _, _ = setup_index
    index = create()
    await index.upsert(entity_id="event", embedding=embedding(1, "old"))
    release = asyncio.Event()
    started = asyncio.Event()

    async def rebuild():
        async with index.rebuild_session():
            started.set()
            await release.wait()
            await index.upsert(entity_id="event", embedding=embedding(2, "new"))

    task = asyncio.create_task(rebuild())
    await started.wait()
    await index.upsert(entity_id="event", embedding=embedding(3, "old"))
    release.set()
    await task
    assert await index.get_vectors(entity_ids=["event"], model_key="old") == {"event": [3.0, 0.0]}
    assert await index.get_vectors(entity_ids=["event"], model_key="new") == {}
    with pytest.raises(RuntimeError, match="Abort"):
        async with index.rebuild_session():
            await index.upsert(entity_id="event", embedding=embedding(4, "new"))
            raise RuntimeError("Abort")
    assert await index.get_vectors(entity_ids=["event"], model_key="old")
    async with index.rebuild_session():
        await index.upsert(entity_id="event", embedding=embedding(5, "new"))
    assert await index.get_vectors(entity_ids=["event"], model_key="old") == {}


@pytest.mark.asyncio
async def test_clear_fences_active_rebuild_and_model_switch_fails_closed(setup_index):
    create, _, _ = setup_index
    index = create()
    async with index.rebuild_session():
        await index.upsert(entity_id="event", embedding=embedding())
        await index.clear()
        await index.upsert(entity_id="event", embedding=embedding())
    assert await index.get_vectors(entity_ids=["event"]) == {}
    with pytest.raises(EmbeddingRebuildIdentityChangedError):
        async with index.rebuild_session():
            await index.upsert(entity_id="event", embedding=embedding())
            await index.upsert(entity_id="other", embedding=embedding(model="different"))


@pytest.mark.asyncio
async def test_rejected_rebuild_publication_preserves_prior_model(setup_index):
    create, _, _ = setup_index
    index = create()
    await index.upsert(entity_id="event", embedding=embedding(model="old"))
    async with index.rebuild_session():
        await index.upsert(entity_id="event", embedding=embedding(model="new"))
        await index.delete_embedding(entity_id="event", embedding=embedding(model="new"))
    assert await index.get_vectors(entity_ids=["event"], model_key="old")


@pytest.mark.asyncio
async def test_source_visibility_owns_orphan_pruning(setup_index):
    create, _, _ = setup_index
    index = create()
    for entity_id in ["a", "b", "c"]:
        await index.upsert(entity_id=entity_id, embedding=embedding())

    async def visible(ids):
        return set(ids) & {"b"}

    assert await index.prune_orphans(valid_entity_ids=visible, batch_size=1) == 2
    assert set(await index.get_vectors(entity_ids=["a", "b", "c"])) == {"b"}


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("MAGI_TEST_CHROMA_PORT"),
    reason="Requires a dedicated Chroma HTTP test server",
)
async def test_real_chroma_http_distance_partition_update_restart_and_clear(setup_index):
    create, _, repository = setup_index
    client = ChromaVectorClient(
        ChromaVectorSettings(host="127.0.0.1", port=int(os.environ["MAGI_TEST_CHROMA_PORT"]))
    )
    index = create(client)
    await index.upsert(entity_id="a", embedding=embedding(1), metadata={"partition_value": "first"})
    await index.upsert(
        entity_id="b", embedding=embedding(4), metadata={"partition_value": "second"}
    )
    hits = await index.search(embedding=embedding(1), limit=10)
    assert [(hit.entity_id, hit.distance) for hit in hits] == [("a", 0.0), ("b", 3.0)]
    assert [
        hit.entity_id
        for hit in await index.search(embedding=embedding(1), limit=10, max_distance=2)
    ] == ["a"]
    assert [
        hit.entity_id
        for hit in await index.search(embedding=embedding(1), limit=10, partition_value="second")
    ] == ["b"]
    await index.upsert(entity_id="a", embedding=embedding(7), metadata={"partition_value": "first"})
    assert await index.get_vectors(entity_ids=["a"]) == {"a": [7.0, 0.0]}
    await index.close()
    recovered = create(client)
    await recovered.flush()
    assert await recovered.get_vectors(entity_ids=["b"]) == {"b": [4.0, 0.0]}
    await recovered.delete_entity(entity_id="b")
    await recovered.clear()
    assert await repository.current("l1") == []
    assert await recovered.search(embedding=embedding(), limit=10) == []


@pytest.mark.asyncio
async def test_idle_recovery_does_not_repeat_full_collection_audits(setup_index):
    from unittest.mock import AsyncMock

    create, remote, repository = setup_index
    index = create()
    await index.upsert(entity_id="event", embedding=embedding())
    remote.reconcile = AsyncMock(wraps=remote.reconcile)
    await index.recover_once()
    assert await repository.pending("l1") == []
    await index.recover_once()
    await index.recover_once()
    assert remote.reconcile.await_count == 1


@pytest.mark.asyncio
async def test_remote_audit_allows_reads_and_preserves_concurrent_new_revisions(setup_index):
    create, remote, repository = setup_index
    index = create()
    await index.upsert(entity_id="event", embedding=embedding())
    entered, release = asyncio.Event(), asyncio.Event()
    original = remote.reconcile

    async def paused(collection, current_ids):
        entered.set()
        await release.wait()
        await original(collection, current_ids)

    remote.reconcile = paused
    audit = asyncio.create_task(index.flush())
    await entered.wait()
    try:
        hits = await asyncio.wait_for(index.search(embedding=embedding(), limit=1), timeout=1)
        assert hits[0].entity_id == "event"
        await asyncio.wait_for(index.upsert(entity_id="event", embedding=embedding(3)), timeout=1)
    finally:
        release.set()
        await audit
    current, = await repository.current("l1")
    assert current.record_id in remote.data[current.collection_id]
    assert await index.get_vectors(entity_ids=["event"]) == {"event": [3, 0]}
