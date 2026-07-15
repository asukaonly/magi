"""Memory embedding status and rebuild routes."""

from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel, Field

from ....memory.embedding.vector_admin import (
    EmbeddingRebuildPausedError,
    EmbeddingRebuildManager,
    build_embedding_vector_status,
)
from .dependencies import _resolve_unified_memory
from .router import memory_router


class StartEmbeddingRebuildRequest(BaseModel):
    layers: list[str] | None = Field(default=None)


_embedding_rebuild_manager = EmbeddingRebuildManager()


@memory_router.get("/embeddings/status")
async def get_embedding_vector_status():
    return await build_embedding_vector_status(_embedding_rebuild_manager)


@memory_router.post("/embeddings/rebuild")
async def start_embedding_rebuild(body: StartEmbeddingRebuildRequest | None = None):
    unified_memory = _resolve_unified_memory()
    if unified_memory is None:
        raise HTTPException(status_code=503, detail="Memory runtime is not available")
    try:
        return await _embedding_rebuild_manager.start_rebuild(
            unified_memory=unified_memory,
            layers=body.layers if body is not None else None,
        )
    except EmbeddingRebuildPausedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@memory_router.get("/embeddings/rebuild/{job_id}")
async def get_embedding_rebuild_job(job_id: str):
    job = await _embedding_rebuild_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Embedding rebuild job not found")
    return job


@memory_router.post("/embeddings/rebuild/{job_id}/cancel")
async def cancel_embedding_rebuild_job(job_id: str):
    job = await _embedding_rebuild_manager.cancel_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Embedding rebuild job not found")
    return job


__all__ = ["_embedding_rebuild_manager"]
