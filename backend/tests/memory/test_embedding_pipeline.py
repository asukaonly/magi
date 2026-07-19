from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from magi.memory.embedding.chunking import ChunkedText
from magi.memory.embedding.embedding_service import EmbeddingResult


class _RecordingEmbeddingService:
    def __init__(self) -> None:
        self.batch_calls: list[list[str]] = []
        self.single_calls: list[str] = []

    async def embed_text(self, text: str):
        self.single_calls.append(text)
        return EmbeddingResult(model_name="test-embedding", dimension=2, vector=[1.0, 0.0])

    async def embed_texts(self, texts: list[str]):
        self.batch_calls.append(list(texts))
        return [
            EmbeddingResult(model_name="test-embedding", dimension=2, vector=[1.0, float(index)])
            for index, _text in enumerate(texts)
        ]

    def result_for_index(
        self, result: EmbeddingResult, *, text_builder_version: str
    ) -> EmbeddingResult:
        return EmbeddingResult(
            model_name=result.model_name,
            dimension=result.dimension,
            vector=result.vector,
            model_identity=result.model_identity,
            index_identity=f"{result.model_name}:{result.dimension}:{text_builder_version}",
        )


class _FallbackVectorIndex:
    def __init__(self) -> None:
        self.upsert_many_calls: list[list[str]] = []
        self.upsert_calls: list[str] = []

    async def upsert_many(self, items: list[dict[str, object]]) -> None:
        self.upsert_many_calls.append([str(item["entity_id"]) for item in items])
        raise RuntimeError("force fallback")

    async def upsert(self, *, entity_id: str, embedding, metadata=None) -> None:
        _ = (embedding, metadata)
        self.upsert_calls.append(entity_id)


class _StrictFallbackVectorIndex(_FallbackVectorIndex):
    def in_rebuild_session(self) -> bool:
        return True


class _EmptyEmbeddingService(_RecordingEmbeddingService):
    async def embed_texts(self, texts: list[str]):
        self.batch_calls.append(list(texts))
        return []


class _RecordingVectorIndex:
    def __init__(self) -> None:
        self.index_identities: list[str | None] = []

    async def upsert_many(self, items: list[dict[str, object]]) -> None:
        self.index_identities = [
            getattr(item["embedding"], "index_identity", None) for item in items
        ]


class _SwitchableProfileEmbeddingService(_RecordingEmbeddingService):
    def __init__(self) -> None:
        super().__init__()
        self.profile_id = "profile-old"
        self.embedding_started = asyncio.Event()
        self.release_embedding = asyncio.Event()
        self.block_embedding = False

    def get_active_profile(self, *, text_builder_version: str):
        assert text_builder_version
        return SimpleNamespace(profile_id=self.profile_id, dimension=2)

    async def embed_texts(self, texts: list[str]):
        self.batch_calls.append(list(texts))
        if self.block_embedding:
            self.embedding_started.set()
            await self.release_embedding.wait()
        return [
            EmbeddingResult(model_name="old-model", dimension=2, vector=[1.0, 0.0])
            for _text in texts
        ]

    def result_for_index(
        self, result: EmbeddingResult, *, text_builder_version: str
    ) -> EmbeddingResult:
        return EmbeddingResult(
            model_name=result.model_name,
            dimension=result.dimension,
            vector=result.vector,
            index_identity=self.profile_id,
        )


class _StrictRecordingVectorIndex(_RecordingVectorIndex):
    def in_rebuild_session(self) -> bool:
        return True


def test_embedding_pipeline_partitions_items_without_canonical_chunks():
    from magi.memory.embedding.embedding_pipeline import (
        EmbeddingPipelineItem,
        partition_embedding_pipeline_items,
    )

    with_text = EmbeddingPipelineItem(
        parent_id="with-text",
        chunks=[
            ChunkedText(
                chunk_id="with-text::chunk-0",
                text="searchable text",
                chunk_index=0,
                char_start=0,
                char_end=15,
                token_estimate=4,
            )
        ],
    )
    without_text = EmbeddingPipelineItem(parent_id="without-text", chunks=[])

    embeddable, unembeddable = partition_embedding_pipeline_items([without_text, with_text])

    assert embeddable == [with_text]
    assert unembeddable == [without_text]


@pytest.mark.asyncio
async def test_embedding_pipeline_batches_chunks_and_falls_back_to_single_upserts():
    from magi.memory.embedding.embedding_pipeline import (
        EmbeddingPipelineItem,
        MemoryEmbeddingPipeline,
    )

    embedding_service = _RecordingEmbeddingService()
    vector_index = _FallbackVectorIndex()
    pipeline = MemoryEmbeddingPipeline(
        embedding_service=embedding_service,
        vector_index=vector_index,
    )

    items = [
        EmbeddingPipelineItem(
            parent_id="summary-1",
            chunks=[
                ChunkedText(
                    chunk_id="summary-1::chunk-0",
                    text="career summary first block",
                    chunk_index=0,
                    char_start=0,
                    char_end=26,
                    token_estimate=6,
                ),
                ChunkedText(
                    chunk_id="summary-1::chunk-1",
                    text="career summary second block",
                    chunk_index=1,
                    char_start=27,
                    char_end=54,
                    token_estimate=6,
                ),
            ],
            metadata={"layer": "l3"},
        ),
        EmbeddingPipelineItem(
            parent_id="entity-1",
            chunks=[
                ChunkedText(
                    chunk_id="entity-1::chunk-0",
                    text="organization openai openai labs",
                    chunk_index=0,
                    char_start=0,
                    char_end=31,
                    token_estimate=7,
                )
            ],
            metadata={"layer": "l2"},
        ),
    ]

    results = await pipeline.upsert_items(items)

    assert embedding_service.batch_calls == [
        [
            "career summary first block",
            "career summary second block",
            "organization openai openai labs",
        ]
    ]
    assert vector_index.upsert_many_calls == [
        [
            "summary-1::chunk-0",
            "summary-1::chunk-1",
            "entity-1::chunk-0",
        ]
    ]
    assert vector_index.upsert_calls == [
        "summary-1::chunk-0",
        "summary-1::chunk-1",
        "entity-1::chunk-0",
    ]
    assert [result.parent_id for result in results] == ["summary-1", "entity-1"]
    assert [len(result.chunks) for result in results] == [2, 1]


@pytest.mark.asyncio
async def test_embedding_pipeline_stamps_index_identity_with_text_builder_version():
    from magi.memory.embedding.embedding_pipeline import (
        EmbeddingPipelineItem,
        MemoryEmbeddingPipeline,
    )

    embedding_service = _RecordingEmbeddingService()
    vector_index = _RecordingVectorIndex()
    pipeline = MemoryEmbeddingPipeline(
        embedding_service=embedding_service,
        vector_index=vector_index,
        text_builder_version="l3_summary_v1",
    )

    await pipeline.upsert_items(
        [
            EmbeddingPipelineItem(
                parent_id="summary-1",
                chunks=[
                    ChunkedText(
                        chunk_id="summary-1::chunk-0",
                        text="career summary",
                        chunk_index=0,
                        char_start=0,
                        char_end=14,
                        token_estimate=4,
                    )
                ],
            )
        ]
    )

    assert vector_index.index_identities == ["test-embedding:2:l3_summary_v1"]


@pytest.mark.asyncio
async def test_embedding_pipeline_does_not_hide_rebuild_write_failures():
    from magi.memory.embedding.embedding_pipeline import (
        EmbeddingPipelineItem,
        MemoryEmbeddingPipeline,
    )

    vector_index = _StrictFallbackVectorIndex()
    pipeline = MemoryEmbeddingPipeline(
        embedding_service=_RecordingEmbeddingService(),
        vector_index=vector_index,
    )
    item = EmbeddingPipelineItem(
        parent_id="entity-1",
        chunks=[
            ChunkedText(
                chunk_id="entity-1",
                text="strict rebuild",
                chunk_index=0,
                char_start=0,
                char_end=14,
                token_estimate=4,
            )
        ],
    )

    with pytest.raises(RuntimeError, match="force fallback"):
        await pipeline.upsert_items([item])

    assert vector_index.upsert_calls == []


@pytest.mark.asyncio
async def test_embedding_pipeline_rejects_missing_vectors_during_rebuild():
    from magi.memory.embedding.embedding_pipeline import (
        EmbeddingPipelineIncompleteError,
        EmbeddingPipelineItem,
        MemoryEmbeddingPipeline,
    )

    pipeline = MemoryEmbeddingPipeline(
        embedding_service=_EmptyEmbeddingService(),
        vector_index=_StrictFallbackVectorIndex(),
    )
    item = EmbeddingPipelineItem(
        parent_id="entity-1",
        chunks=[
            ChunkedText(
                chunk_id="entity-1",
                text="missing vector",
                chunk_index=0,
                char_start=0,
                char_end=14,
                token_estimate=4,
            )
        ],
    )

    with pytest.raises(EmbeddingPipelineIncompleteError, match="no vectors"):
        await pipeline.prepare_items([item])


@pytest.mark.asyncio
async def test_embedding_pipeline_can_prepare_without_mutating_vector_index():
    from magi.memory.embedding.embedding_pipeline import (
        EmbeddingPipelineItem,
        MemoryEmbeddingPipeline,
    )

    embedding_service = _RecordingEmbeddingService()
    vector_index = _FallbackVectorIndex()
    pipeline = MemoryEmbeddingPipeline(
        embedding_service=embedding_service,
        vector_index=vector_index,
    )
    item = EmbeddingPipelineItem(
        parent_id="summary-prepare",
        chunks=[
            ChunkedText(
                chunk_id="summary-prepare::chunk-0",
                text="prepared outside mutation lock",
                chunk_index=0,
                char_start=0,
                char_end=30,
                token_estimate=5,
            )
        ],
    )

    prepared = await pipeline.prepare_items([item])

    assert [result.parent_id for result in prepared] == ["summary-prepare"]
    assert vector_index.upsert_many_calls == []
    assert vector_index.upsert_calls == []

    persisted = await pipeline.persist_results(prepared)

    assert [result.parent_id for result in persisted] == ["summary-prepare"]
    assert vector_index.upsert_many_calls == [["summary-prepare::chunk-0"]]
    assert vector_index.upsert_calls == ["summary-prepare::chunk-0"]


def _profile_switch_item():
    from magi.memory.embedding.embedding_pipeline import EmbeddingPipelineItem

    return EmbeddingPipelineItem(
        parent_id="summary-profile-switch",
        chunks=[
            ChunkedText(
                chunk_id="summary-profile-switch::chunk-0",
                text="prepared with the old embedding model",
                chunk_index=0,
                char_start=0,
                char_end=37,
                token_estimate=9,
            )
        ],
    )


@pytest.mark.asyncio
async def test_embedding_pipeline_discards_inflight_results_after_identity_change():
    from magi.memory.embedding.embedding_pipeline import MemoryEmbeddingPipeline

    embedding_service = _SwitchableProfileEmbeddingService()
    embedding_service.block_embedding = True
    vector_index = _RecordingVectorIndex()
    pipeline = MemoryEmbeddingPipeline(
        embedding_service=embedding_service,
        vector_index=vector_index,
        text_builder_version="l3_summary_v1",
    )

    write_task = asyncio.create_task(pipeline.upsert_items([_profile_switch_item()]))
    await asyncio.wait_for(embedding_service.embedding_started.wait(), timeout=1)
    embedding_service.profile_id = "profile-new"
    embedding_service.release_embedding.set()

    assert await write_task == []
    assert vector_index.index_identities == []


@pytest.mark.asyncio
async def test_embedding_pipeline_rechecks_identity_at_publication(
    monkeypatch: pytest.MonkeyPatch,
):
    from magi.config import embedding_coordination as config_coordination
    from magi.memory.embedding.embedding_pipeline import MemoryEmbeddingPipeline

    publication_lock = asyncio.Lock()
    monkeypatch.setattr(
        config_coordination,
        "_EMBEDDING_PUBLICATION_LOCK",
        publication_lock,
    )
    embedding_service = _SwitchableProfileEmbeddingService()
    vector_index = _RecordingVectorIndex()
    pipeline = MemoryEmbeddingPipeline(
        embedding_service=embedding_service,
        vector_index=vector_index,
        text_builder_version="l3_summary_v1",
    )
    prepared = await pipeline.prepare_items([_profile_switch_item()])

    await publication_lock.acquire()
    persist_task = asyncio.create_task(pipeline.persist_results(prepared))
    await asyncio.sleep(0)
    assert vector_index.index_identities == []

    embedding_service.profile_id = "profile-new"
    publication_lock.release()

    assert await persist_task == []
    assert vector_index.index_identities == []


@pytest.mark.asyncio
async def test_embedding_rebuild_fails_if_identity_changes_before_publication():
    from magi.memory.embedding.embedding_pipeline import MemoryEmbeddingPipeline
    from magi.memory.embedding.sqlite_vec_index import EmbeddingRebuildIdentityChangedError

    embedding_service = _SwitchableProfileEmbeddingService()
    vector_index = _StrictRecordingVectorIndex()
    pipeline = MemoryEmbeddingPipeline(
        embedding_service=embedding_service,
        vector_index=vector_index,
        text_builder_version="l3_summary_v1",
    )
    prepared = await pipeline.prepare_items([_profile_switch_item()])

    embedding_service.profile_id = "profile-new"

    with pytest.raises(EmbeddingRebuildIdentityChangedError, match="before vector publication"):
        await pipeline.persist_results(prepared)
    assert vector_index.index_identities == []


@pytest.mark.asyncio
async def test_embedding_pipeline_discards_results_across_coordinated_config_generation():
    from magi.config.embedding_coordination import (
        pause_rebuilds_for_embedding_config_change,
    )
    from magi.memory.embedding.embedding_pipeline import MemoryEmbeddingPipeline

    def config(model_id: str):
        def layer():
            return SimpleNamespace(enabled=True, vectors_enabled=True)

        return SimpleNamespace(
            memory=SimpleNamespace(
                db_path="memory.db",
                embedding=SimpleNamespace(
                    backend="sqlite_vec",
                    mode="local",
                    local=SimpleNamespace(
                        model_source="managed",
                        managed_model_id=model_id,
                        model_dir_path="",
                        variant="fp16",
                    ),
                ),
                l1=layer(),
                l2=layer(),
                l3=layer(),
                l4=layer(),
            ),
            llm=SimpleNamespace(selections={}, providers={}),
        )

    class RebuildManager:
        async def pause_starts_and_cancel_all(self) -> int:
            return 0

        async def resume_starts(self) -> None:
            return None

    embedding_service = _SwitchableProfileEmbeddingService()
    vector_index = _RecordingVectorIndex()
    pipeline = MemoryEmbeddingPipeline(
        embedding_service=embedding_service,
        vector_index=vector_index,
        text_builder_version="l3_summary_v1",
    )
    prepared = await pipeline.prepare_items([_profile_switch_item()])

    async with pause_rebuilds_for_embedding_config_change(
        current_config=config("model-a"),
        proposed_config=config("model-b"),
        manager_factory=RebuildManager,
    ):
        pass

    assert await pipeline.persist_results(prepared) == []
    assert vector_index.index_identities == []
