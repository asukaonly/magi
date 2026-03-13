"""Memory management API for L1-L5 memory layers."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from ..services import get_chat_read_service
from ...core.logger import get_logger

logger = get_logger(__name__)

memory_router = APIRouter()

_model_download_jobs: Dict[str, Dict[str, Any]] = {}


class MemoryResponse(BaseModel):
    id: str
    type: str
    content: Dict[str, Any]
    metadata: Dict[str, Any]
    created_at: datetime
    updated_at: Optional[datetime] = None


class SemanticSearchRequest(BaseModel):
    query: str = Field(..., description="Search text")
    search_type: str = Field(default="hybrid", description="hybrid|semantic|keyword|relation")
    limit: int = Field(default=10, ge=1, le=200)


class SemanticSearchResult(BaseModel):
    event_id: str
    similarity: float
    text: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EventContextResponse(BaseModel):
    event_id: str
    depth: int
    related_events: Dict[int, List[Dict[str, Any]]]


class SummaryResponse(BaseModel):
    period_type: str
    period_key: str
    start_time: float
    end_time: float
    event_count: int
    summary: str
    event_types: Dict[str, int]
    metrics: Dict[str, Any]


class CapabilityResponse(BaseModel):
    capability_id: str
    name: str
    description: str
    success_rate: float
    usage_count: int
    avg_duration: float
    last_used: float


class MemoryStatisticsResponse(BaseModel):
    l1_raw: Dict[str, Any]
    l2_relations: Dict[str, Any]
    l3_embeddings: Optional[Dict[str, Any]] = None
    l4_summaries: Optional[Dict[str, Any]] = None
    l5_capabilities: Optional[Dict[str, Any]] = None
    integration_stats: Optional[Dict[str, Any]] = None


class ModelDownloadRequest(BaseModel):
    model: str


class ModelDownloadStatusResponse(BaseModel):
    model: str
    status: str
    progress: int
    message: Optional[str] = None
    updated_at: float


class InstalledModelsResponse(BaseModel):
    models: List[str]


def _derive_capability_response(capability: Any) -> CapabilityResponse:
    usage_count = int(getattr(capability, "usage_count", 0) or 0)
    success_count = int(getattr(capability, "success_count", 0) or 0)
    success_rate = (success_count / usage_count) if usage_count > 0 else 0.0
    avg_duration = float(getattr(capability, "avg_duration", 0.0) or 0.0)
    return CapabilityResponse(
        capability_id=str(getattr(capability, "capability_id")),
        name=str(getattr(capability, "name", "")),
        description=str(getattr(capability, "description", "")),
        success_rate=success_rate,
        usage_count=usage_count,
        avg_duration=avg_duration,
        last_used=float(getattr(capability, "last_used", 0.0) or 0.0),
    )


def get_unified_memory():
    try:
        from ...agent import get_unified_memory

        return get_unified_memory()
    except RuntimeError:
        return None


def get_memory_integration():
    try:
        from ...agent import get_memory_integration

        return get_memory_integration()
    except RuntimeError:
        return None


def _get_models_dir() -> Path:
    models_dir = Path.home() / ".magi" / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    return models_dir


def _model_ready_file(model_name: str) -> Path:
    return _get_models_dir() / f"{model_name.replace('/', '__')}.ready"


async def _simulate_model_download(model_name: str):
    for progress in (10, 25, 45, 65, 80, 100):
        await asyncio.sleep(0.4)
        _model_download_jobs[model_name] = {
            "status": "downloading" if progress < 100 else "ready",
            "progress": progress,
            "updated_at": time.time(),
            "message": "Downloading embedding model" if progress < 100 else "Model ready",
        }
    _model_ready_file(model_name).write_text(str(time.time()), encoding="utf-8")


@memory_router.get("/l1/events")
async def get_l1_events(
    limit: int = Query(default=50, ge=1, le=500),
    event_type: Optional[str] = Query(None),
):
    unified_memory = get_unified_memory()
    if not unified_memory or not unified_memory.l1_raw:
        return {"events": [], "stats": {"total": 0}}

    try:
        events = await unified_memory.l1_raw.list_events(limit=limit, event_type=event_type)
        total = await unified_memory.l1_raw.count_events()
        return {"events": events, "stats": {"total": total}}
    except Exception as exc:
        logger.error(f"Failed to fetch L1 events: {exc}")
        return {"events": [], "stats": {"total": 0}}


@memory_router.get("/l2/statistics")
async def get_l2_statistics():
    unified_memory = get_unified_memory()
    if not unified_memory or not unified_memory.l2_relations:
        return {"total_events": 0, "total_relations": 0}

    try:
        return unified_memory.l2_relations.get_statistics()
    except Exception as exc:
        logger.error(f"Failed to fetch L2 statistics: {exc}")
        return {"total_events": 0, "total_relations": 0}


@memory_router.get("/statistics", response_model=MemoryStatisticsResponse)
async def get_memory_statistics():
    unified_memory = get_unified_memory()
    memory_integration = get_memory_integration()

    if not unified_memory:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory system not initialized",
        )

    stats = unified_memory.get_statistics()
    if memory_integration:
        stats["integration_stats"] = memory_integration.get_statistics()

    return stats


@memory_router.post("/search", response_model=List[SemanticSearchResult])
async def semantic_search(request: SemanticSearchRequest):
    unified_memory = get_unified_memory()
    if not unified_memory or not unified_memory.l3_embeddings:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Semantic search unavailable (L3 disabled)",
        )

    try:
        results = await unified_memory.search(
            query=request.query,
            search_type=request.search_type,
            limit=request.limit,
        )
        return [
            SemanticSearchResult(
                event_id=result.get("event_id", ""),
                similarity=float(result.get("similarity") or result.get("combined_score") or 0.0),
                text=result.get("text", ""),
                metadata=result.get("metadata", {}),
            )
            for result in results
        ]
    except Exception as exc:
        logger.error(f"Semantic search failed: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {exc}",
        )


@memory_router.get("/event/{event_id}/context", response_model=EventContextResponse)
async def get_event_context(
    event_id: str,
    max_depth: int = Query(default=2, ge=1, le=5),
):
    unified_memory = get_unified_memory()
    if not unified_memory:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory system not initialized",
        )

    try:
        related = unified_memory.get_related_events(event_id=event_id, max_depth=max_depth)
        return EventContextResponse(event_id=event_id, depth=max_depth, related_events=related)
    except Exception as exc:
        logger.error(f"Failed to get event context: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get event context: {exc}",
        )


@memory_router.get("/summary/{period_type}", response_model=Optional[SummaryResponse])
async def get_summary(
    period_type: str,
    period_key: Optional[str] = Query(None),
    force_generate: bool = Query(False),
):
    if period_type not in {"hour", "day", "week", "month"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="period_type must be one of hour/day/week/month",
        )

    unified_memory = get_unified_memory()
    if not unified_memory or not unified_memory.l4_summaries:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Summary service unavailable (L4 disabled)",
        )

    summary = (
        unified_memory.generate_summary(period_type=period_type, period_key=period_key, force=True)
        if force_generate
        else unified_memory.get_summary(period_type=period_type, period_key=period_key)
    )

    if not summary:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Summary not found for {period_type}/{period_key or 'current'}",
        )

    return SummaryResponse(
        period_type=summary.period_type,
        period_key=summary.period_key,
        start_time=summary.start_time,
        end_time=summary.end_time,
        event_count=summary.event_count,
        summary=summary.summary,
        event_types=summary.event_types,
        metrics=summary.metrics,
    )


@memory_router.get("/capabilities", response_model=List[CapabilityResponse])
async def get_capabilities(limit: int = Query(default=50, ge=1, le=200)):
    unified_memory = get_unified_memory()
    if not unified_memory or not unified_memory.l5_capabilities:
        return []

    capabilities = unified_memory.l5_capabilities.get_all_capabilities()
    capabilities.sort(key=lambda cap: cap.usage_count, reverse=True)
    capabilities = capabilities[:limit]

    return [_derive_capability_response(cap) for cap in capabilities]


@memory_router.get("/capabilities/{capability_id}", response_model=CapabilityResponse)
async def get_capability(capability_id: str):
    unified_memory = get_unified_memory()
    if not unified_memory or not unified_memory.l5_capabilities:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Capability service unavailable (L5 disabled)",
        )

    capability = unified_memory.l5_capabilities.get_capability(capability_id)
    if not capability:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Capability {capability_id} not found",
        )

    return _derive_capability_response(capability)


@memory_router.post("/summaries/generate")
async def generate_pending_summaries():
    memory_integration = get_memory_integration()
    if not memory_integration:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memory integration unavailable",
        )

    await memory_integration.generate_pending_summaries()
    return {"success": True, "message": "Pending summaries generated"}


@memory_router.delete("/capabilities/{capability_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_capability(capability_id: str):
    unified_memory = get_unified_memory()
    if not unified_memory or not unified_memory.l5_capabilities:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Capability service unavailable",
        )

    if not unified_memory.l5_capabilities.delete_capability(capability_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Capability {capability_id} not found",
        )


@memory_router.post("/models/download", response_model=ModelDownloadStatusResponse)
async def download_embedding_model(request: ModelDownloadRequest):
    model = request.model.strip()
    if not model:
        raise HTTPException(status_code=400, detail="Model is required")

    if _model_ready_file(model).exists():
        status_obj = {
            "status": "ready",
            "progress": 100,
            "updated_at": time.time(),
            "message": "Model already installed",
        }
        _model_download_jobs[model] = status_obj
        return ModelDownloadStatusResponse(model=model, **status_obj)

    existing = _model_download_jobs.get(model)
    if existing and existing.get("status") == "downloading":
        return ModelDownloadStatusResponse(model=model, **existing)

    _model_download_jobs[model] = {
        "status": "downloading",
        "progress": 0,
        "updated_at": time.time(),
        "message": "Download started",
    }
    asyncio.create_task(_simulate_model_download(model))
    return ModelDownloadStatusResponse(model=model, **_model_download_jobs[model])


@memory_router.get("/models/download/{model_name}/status", response_model=ModelDownloadStatusResponse)
async def get_embedding_model_status(model_name: str):
    if _model_ready_file(model_name).exists():
        status_obj = {
            "status": "ready",
            "progress": 100,
            "updated_at": time.time(),
            "message": "Model installed",
        }
        _model_download_jobs[model_name] = status_obj
        return ModelDownloadStatusResponse(model=model_name, **status_obj)

    existing = _model_download_jobs.get(model_name)
    if existing:
        return ModelDownloadStatusResponse(model=model_name, **existing)

    return ModelDownloadStatusResponse(
        model=model_name,
        status="not_downloaded",
        progress=0,
        updated_at=time.time(),
        message="Model not downloaded",
    )


@memory_router.get("/models", response_model=InstalledModelsResponse)
async def list_installed_embedding_models():
    models = [file.stem.replace("__", "/") for file in _get_models_dir().glob("*.ready")]
    return InstalledModelsResponse(models=sorted(models))


@memory_router.delete("/clear")
async def clear_all_memories():
    unified_memory = get_unified_memory()

    results = {
        "l1_raw": {"cleared": False, "count": 0},
        "l2_relations": {"cleared": False, "count": 0},
        "l3_embeddings": {"cleared": False, "count": 0},
        "l4_summaries": {"cleared": False, "count": 0},
        "l5_capabilities": {"cleared": False, "count": 0},
        "chat_context": {"cleared": False, "count": 0},
    }
    warnings: List[str] = []

    if unified_memory:
        try:
            count = await unified_memory.l1_raw.clear()
            results["l1_raw"] = {"cleared": True, "count": count}
        except Exception as exc:
            warnings.append(f"L1: {exc}")

        try:
            count = unified_memory.l2_relations.clear()
            unified_memory.l2_relations._save_to_disk()
            results["l2_relations"] = {"cleared": True, "count": count}
        except Exception as exc:
            warnings.append(f"L2: {exc}")

        try:
            if unified_memory.l3_embeddings:
                count = unified_memory.l3_embeddings.clear()
                results["l3_embeddings"] = {"cleared": True, "count": count}
        except Exception as exc:
            warnings.append(f"L3: {exc}")

        try:
            if unified_memory.l4_summaries:
                count = unified_memory.l4_summaries.clear()
                results["l4_summaries"] = {"cleared": True, "count": count}
        except Exception as exc:
            warnings.append(f"L4: {exc}")

        try:
            if unified_memory.l5_capabilities:
                count = unified_memory.l5_capabilities.clear()
                results["l5_capabilities"] = {"cleared": True, "count": count}
        except Exception as exc:
            warnings.append(f"L5: {exc}")

    try:
        read_service = get_chat_read_service()
        session_count = read_service.clear_all_sessions()
        results["chat_context"] = {"cleared": True, "count": session_count}
    except Exception as exc:
        warnings.append(f"ChatContext: {exc}")

    response = {"success": True, "results": results}
    if warnings:
        response["warnings"] = warnings
    return response


_legacy_memory_store: Dict[str, Dict[str, Any]] = {
    "mem_1": {
        "id": "mem_1",
        "type": "self",
        "content": {"event": "Learned to use Python"},
        "metadata": {"source": "learning", "importance": 0.8},
        "created_at": datetime.now(),
        "updated_at": None,
    },
    "mem_2": {
        "id": "mem_2",
        "type": "other",
        "content": {"user": "Alice", "preference": "likes cats"},
        "metadata": {"source": "conversation", "importance": 0.6},
        "created_at": datetime.now(),
        "updated_at": None,
    },
}


@memory_router.get("/legacy/", response_model=List[MemoryResponse])
async def list_memories(memory_type: Optional[str] = None, limit: int = 100, offset: int = 0):
    memories = list(_legacy_memory_store.values())
    if memory_type:
        memories = [memory for memory in memories if memory["type"] == memory_type]
    memories.sort(key=lambda item: item["created_at"], reverse=True)
    return memories[offset : offset + limit]


@memory_router.get("/legacy/{memory_id}", response_model=MemoryResponse)
async def get_memory(memory_id: str):
    if memory_id not in _legacy_memory_store:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Memory {memory_id} not found")
    return _legacy_memory_store[memory_id]


@memory_router.delete("/legacy/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(memory_id: str):
    if memory_id not in _legacy_memory_store:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Memory {memory_id} not found")
    del _legacy_memory_store[memory_id]
