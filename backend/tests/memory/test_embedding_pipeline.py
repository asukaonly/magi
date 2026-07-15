from __future__ import annotations

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


class _RecordingVectorIndex:
    def __init__(self) -> None:
        self.index_identities: list[str | None] = []

    async def upsert_many(self, items: list[dict[str, object]]) -> None:
        self.index_identities = [
            getattr(item["embedding"], "index_identity", None) for item in items
        ]


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
