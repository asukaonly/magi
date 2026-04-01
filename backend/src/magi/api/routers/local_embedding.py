"""API endpoints for local embedding model management."""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...config.local_embedding_registry import (
    LocalEmbeddingModelMeta,
    get_local_embedding_registry,
)
from ...utils.runtime import RuntimePaths

logger = logging.getLogger(__name__)
local_embedding_router = APIRouter()

# Track in-progress downloads keyed by model_id
_download_tasks: dict[str, asyncio.Task[None]] = {}
_download_progress: dict[str, dict[str, Any]] = {}


# ── Response models ─────────────────────────────────────────────────────


class LocalEmbeddingModelInfo(BaseModel):
    """Preset model info with download status."""

    id: str
    label: str
    repo: str
    dimension: int
    max_tokens: int
    pooling: str
    normalize: bool
    size_mb: int
    quantized: bool
    languages: list[str]
    recommended: bool
    description: str
    downloaded: bool
    download_in_progress: bool
    download_progress_pct: Optional[float] = None


class DiscoveredModel(BaseModel):
    """A model discovered in the external model directory."""

    dir_name: str
    path: str
    has_onnx: bool
    has_tokenizer: bool
    has_config: bool
    dimension: Optional[int] = None


class DownloadStatusResponse(BaseModel):
    """Download progress response."""

    model_id: str
    status: str  # "downloading", "completed", "failed", "not_found"
    progress_pct: Optional[float] = None
    error: Optional[str] = None


# ── Endpoints ───────────────────────────────────────────────────────────


@local_embedding_router.get("/models")
async def list_models() -> list[LocalEmbeddingModelInfo]:
    """List all preset local embedding models with download status."""
    registry = get_local_embedding_registry()
    paths = RuntimePaths()
    result = []
    for model in registry.models:
        model_dir = Path(paths.managed_embedding_model_dir(model.id))
        downloaded = _is_model_downloaded(model_dir)
        in_progress = model.id in _download_tasks and not _download_tasks[model.id].done()
        progress = _download_progress.get(model.id, {})
        result.append(
            LocalEmbeddingModelInfo(
                id=model.id,
                label=model.label,
                repo=model.repo,
                dimension=model.dimension,
                max_tokens=model.max_tokens,
                pooling=model.pooling,
                normalize=model.normalize,
                size_mb=model.size_mb,
                quantized=model.quantized,
                languages=model.languages,
                recommended=model.recommended,
                description=model.description,
                downloaded=downloaded,
                download_in_progress=in_progress,
                download_progress_pct=progress.get("pct"),
            )
        )
    return result


@local_embedding_router.post("/models/{model_id}/download")
async def download_model(model_id: str) -> DownloadStatusResponse:
    """Trigger download of a preset model."""
    registry = get_local_embedding_registry()
    meta = registry.get(model_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Unknown model: {model_id}")

    # Check if already downloading
    existing_task = _download_tasks.get(model_id)
    if existing_task is not None and not existing_task.done():
        progress = _download_progress.get(model_id, {})
        return DownloadStatusResponse(
            model_id=model_id,
            status="downloading",
            progress_pct=progress.get("pct"),
        )

    # Check if already downloaded
    paths = RuntimePaths()
    model_dir = Path(paths.managed_embedding_model_dir(model_id))
    if _is_model_downloaded(model_dir):
        return DownloadStatusResponse(model_id=model_id, status="completed")

    # Start download task
    _download_progress[model_id] = {"pct": 0.0, "error": None}
    task = asyncio.create_task(_download_model_task(meta, model_dir))
    _download_tasks[model_id] = task

    return DownloadStatusResponse(
        model_id=model_id,
        status="downloading",
        progress_pct=0.0,
    )


@local_embedding_router.get("/models/{model_id}/status")
async def get_download_status(model_id: str) -> DownloadStatusResponse:
    """Get download progress for a model."""
    progress = _download_progress.get(model_id)
    task = _download_tasks.get(model_id)

    if progress is None and task is None:
        # Check if already downloaded
        paths = RuntimePaths()
        registry = get_local_embedding_registry()
        meta = registry.get(model_id)
        if meta is None:
            raise HTTPException(status_code=404, detail=f"Unknown model: {model_id}")
        model_dir = Path(paths.managed_embedding_model_dir(model_id))
        if _is_model_downloaded(model_dir):
            return DownloadStatusResponse(model_id=model_id, status="completed")
        return DownloadStatusResponse(model_id=model_id, status="not_found")

    error = (progress or {}).get("error")
    if error:
        return DownloadStatusResponse(
            model_id=model_id,
            status="failed",
            error=error,
        )

    if task is not None and task.done():
        exc = task.exception() if not task.cancelled() else None
        if exc:
            return DownloadStatusResponse(
                model_id=model_id,
                status="failed",
                error=str(exc),
            )
        return DownloadStatusResponse(model_id=model_id, status="completed")

    return DownloadStatusResponse(
        model_id=model_id,
        status="downloading",
        progress_pct=(progress or {}).get("pct"),
    )


@local_embedding_router.delete("/models/{model_id}")
async def delete_model(model_id: str) -> dict[str, str]:
    """Delete a downloaded model."""
    paths = RuntimePaths()
    model_dir = Path(paths.managed_embedding_model_dir(model_id))

    # Cancel any in-progress download
    task = _download_tasks.get(model_id)
    if task is not None and not task.done():
        task.cancel()

    if model_dir.exists():
        await asyncio.to_thread(shutil.rmtree, str(model_dir))
        _download_progress.pop(model_id, None)
        _download_tasks.pop(model_id, None)
        return {"status": "deleted"}

    raise HTTPException(status_code=404, detail="Model not found on disk")


@local_embedding_router.get("/discovered")
async def discover_external_models() -> list[DiscoveredModel]:
    """Scan the embedding models directory for user-provided models."""
    paths = RuntimePaths()
    embed_dir = paths.embedding_models_dir
    if not embed_dir.exists():
        return []

    registry = get_local_embedding_registry()
    preset_ids = set(registry.list_ids())
    discovered: list[DiscoveredModel] = []

    for entry in sorted(embed_dir.iterdir()):
        if not entry.is_dir():
            continue
        # Skip preset models (they appear in /models)
        normalized_name = entry.name
        if normalized_name in preset_ids:
            continue

        has_onnx = any(entry.glob("*.onnx")) or any(entry.glob("onnx/*.onnx"))
        has_tokenizer = (entry / "tokenizer.json").exists()
        has_config = (entry / "config.json").exists()
        dimension = None
        if has_config:
            try:
                import json
                cfg = json.loads((entry / "config.json").read_text(encoding="utf-8"))
                dimension = cfg.get("hidden_size")
            except Exception:
                pass

        discovered.append(
            DiscoveredModel(
                dir_name=entry.name,
                path=str(entry),
                has_onnx=has_onnx,
                has_tokenizer=has_tokenizer,
                has_config=has_config,
                dimension=dimension,
            )
        )
    return discovered


# ── Internal helpers ────────────────────────────────────────────────────


def _is_model_downloaded(model_dir: Path) -> bool:
    """Check if a model directory has the required files."""
    if not model_dir.exists():
        return False
    has_onnx = any(model_dir.glob("*.onnx")) or any(model_dir.glob("onnx/*.onnx"))
    has_tokenizer = (model_dir / "tokenizer.json").exists()
    return has_onnx and has_tokenizer


_DOWNLOAD_MAX_RETRIES = 3
_DOWNLOAD_ETAG_TIMEOUT = 30
_DOWNLOAD_READ_TIMEOUT = 60


async def _download_model_task(meta: LocalEmbeddingModelMeta, model_dir: Path) -> None:
    """Background task to download a model from HuggingFace with retry."""
    model_id = meta.id
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        _download_progress[model_id] = {
            "pct": None,
            "error": "huggingface-hub is not installed. Run: pip install huggingface-hub",
        }
        return

    repo_id = meta.onnx_repo or meta.repo
    allow_patterns = [
        "*.onnx",
        "onnx/*.onnx",
        "*.onnx_data",
        "onnx/*.onnx_data",
        "tokenizer.json",
        "tokenizer_config.json",
        "config.json",
        "special_tokens_map.json",
        "vocab.txt",
        "sentencepiece.bpe.model",
    ]

    last_exc: Exception | None = None
    for attempt in range(1, _DOWNLOAD_MAX_RETRIES + 1):
        try:
            _download_progress[model_id] = {"pct": 5.0, "error": None}

            logger.info(
                "Downloading embedding model %s from %s (attempt %d/%d)",
                model_id, repo_id, attempt, _DOWNLOAD_MAX_RETRIES,
            )
            _download_progress[model_id] = {"pct": 10.0, "error": None}

            local_path = await asyncio.to_thread(
                snapshot_download,
                repo_id,
                local_dir=str(model_dir),
                allow_patterns=allow_patterns,
                etag_timeout=_DOWNLOAD_ETAG_TIMEOUT,
            )

            _download_progress[model_id] = {"pct": 90.0, "error": None}

            # Verify essential files
            if not _is_model_downloaded(model_dir):
                _download_progress[model_id] = {
                    "pct": None,
                    "error": f"Download completed but required files missing in {local_path}",
                }
                return

            _download_progress[model_id] = {"pct": 100.0, "error": None}
            logger.info("Embedding model %s downloaded to %s", model_id, model_dir)
            return

        except asyncio.CancelledError:
            _download_progress[model_id] = {"pct": None, "error": "cancelled"}
            if model_dir.exists():
                shutil.rmtree(str(model_dir), ignore_errors=True)
            raise
        except Exception as exc:
            last_exc = exc
            if attempt < _DOWNLOAD_MAX_RETRIES:
                wait = 2 ** attempt
                logger.warning(
                    "Download attempt %d/%d for %s failed: %s — retrying in %ds",
                    attempt, _DOWNLOAD_MAX_RETRIES, model_id, exc, wait,
                )
                _download_progress[model_id] = {
                    "pct": None,
                    "error": f"Retry {attempt}/{_DOWNLOAD_MAX_RETRIES}: {exc}",
                }
                await asyncio.sleep(wait)

    # All retries exhausted
    logger.error("Failed to download embedding model %s after %d attempts: %s", model_id, _DOWNLOAD_MAX_RETRIES, last_exc)
    _download_progress[model_id] = {"pct": None, "error": str(last_exc)}
