"""API endpoints for local cross-encoder reranker model management."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ... import i18n as core_i18n
from ...config.cross_encoder_registry import (
    CrossEncoderModelMeta,
    get_cross_encoder_registry,
)
from ...memory.onnx_variants import (
    detect_platform_key,
    resolve_variant_name,
)
from ...utils.runtime import RuntimePaths
from ...config import get_config
from ...utils.model_download import DownloadProgress, DownloadTracker, ModelDownloadStatus, remove_directory, safe_path
from ...utils.hub_model_download import download_hub_model

logger = logging.getLogger(__name__)
local_reranker_router = APIRouter()

# Track in-progress downloads keyed by model_id
_download_tasks: dict[str, asyncio.Task[None]] = {}
_download_progress: dict[str, DownloadTracker] = {}
_download_errors: dict[str, str] = {}
_download_locks: dict[str, asyncio.Lock] = {}


# ── Response models ─────────────────────────────────────────────────────


class LocalRerankerVariantInfo(BaseModel):
    """One quantization/architecture variant of a cross-encoder model."""

    name: str
    file: str
    size_mb: int
    downloaded: bool


class LocalRerankerModelInfo(BaseModel):
    """Preset cross-encoder model info with download status."""

    id: str
    label: str
    repo: str
    max_tokens: int
    size_mb: int
    languages: list[str]
    recommended: bool
    description: str
    downloaded: bool
    download_in_progress: bool
    download: DownloadProgress | None = None
    variants: list[LocalRerankerVariantInfo] = []
    default_variant: Optional[str] = None


class DownloadStatusResponse(ModelDownloadStatus):
    """Shared byte-based model transfer status."""


# ── Endpoints ───────────────────────────────────────────────────────────


@local_reranker_router.get("/models")
async def list_models() -> list[LocalRerankerModelInfo]:
    """List all preset cross-encoder reranker models with download status."""
    registry = get_cross_encoder_registry()
    paths = RuntimePaths()
    result = []
    for model in registry.models:
        model_dir = Path(paths.managed_reranker_model_dir(model.id))
        downloaded = _is_model_downloaded(model_dir)
        in_progress = model.id in _download_tasks and not _download_tasks[model.id].done()
        progress = _download_progress.get(model.id)
        variants_info: list[LocalRerankerVariantInfo] = []
        for vname, vmeta in model.variants.items():
            candidate = model_dir / vmeta.file
            bare = model_dir / Path(vmeta.file).name
            variants_info.append(
                LocalRerankerVariantInfo(
                    name=vname,
                    file=vmeta.file,
                    size_mb=vmeta.size_mb,
                    downloaded=candidate.exists() or bare.exists(),
                )
            )

        default_variant_name = resolve_variant_name(model) if model.variants else None

        result.append(
            LocalRerankerModelInfo(
                id=model.id,
                label=model.label,
                repo=model.repo,
                max_tokens=model.max_tokens,
                size_mb=model.size_mb,
                languages=model.languages,
                recommended=model.recommended,
                description=model.description,
                downloaded=downloaded,
                download_in_progress=in_progress,
                download=progress.snapshot() if progress else None,
                variants=variants_info,
                default_variant=default_variant_name,
            )
        )
    return result


@local_reranker_router.post("/models/{model_id}/download")
async def download_model(
    model_id: str,
    variant: Optional[str] = None,
) -> DownloadStatusResponse:
    """Trigger download of a preset cross-encoder model.

    Optional ``variant`` query parameter selects a specific ONNX variant;
    defaults to the platform's preferred variant from the registry.
    """
    async with _download_locks.setdefault(model_id, asyncio.Lock()):
        registry = get_cross_encoder_registry()
        meta = registry.get(model_id)
        if meta is None:
            raise HTTPException(
                status_code=404,
                detail=core_i18n.t(
                    "local_models.errors.unknown_model",
                    fallback="Unknown model: {model_id}",
                    model_id=model_id,
                ),
            )

        # Check if already downloading
        existing_task = _download_tasks.get(model_id)
        if existing_task is not None and not existing_task.done():
            progress = _download_progress.get(model_id)
            return DownloadStatusResponse(
                model_id=model_id,
                status="downloading",
                download=progress.snapshot() if progress else None,
            )

        # Check if the *specific* variant requested is already downloaded.
        # Falls back to the model-level check for legacy YAML (no variants block).
        paths = RuntimePaths()
        model_dir = Path(paths.managed_reranker_model_dir(model_id))
        if meta.variants:
            variant_name = resolve_variant_name(meta, override=variant)
            if variant_name is not None:
                variant_file = meta.variants[variant_name].file
                candidate = model_dir / variant_file
                bare = model_dir / Path(variant_file).name
                if candidate.exists() or bare.exists():
                    return DownloadStatusResponse(model_id=model_id, status="completed")
        else:
            if _is_model_downloaded(model_dir):
                return DownloadStatusResponse(model_id=model_id, status="completed")

        # Start download task
        _download_progress[model_id] = DownloadTracker()
        _download_errors.pop(model_id, None)
        task = asyncio.create_task(_download_model_task(meta, model_dir, variant_override=variant))
        _download_tasks[model_id] = task

        return DownloadStatusResponse(
            model_id=model_id,
            status="downloading",
            download=_download_progress[model_id].snapshot(),
        )


@local_reranker_router.get("/models/{model_id}/status")
async def get_download_status(model_id: str) -> DownloadStatusResponse:
    """Get download progress for a cross-encoder model."""
    progress = _download_progress.get(model_id)
    task = _download_tasks.get(model_id)

    if progress is None and task is None:
        paths = RuntimePaths()
        registry = get_cross_encoder_registry()
        meta = registry.get(model_id)
        if meta is None:
            raise HTTPException(
                status_code=404,
                detail=core_i18n.t(
                    "local_models.errors.unknown_model",
                    fallback="Unknown model: {model_id}",
                    model_id=model_id,
                ),
            )
        model_dir = Path(paths.managed_reranker_model_dir(model_id))
        if _is_model_downloaded(model_dir):
            return DownloadStatusResponse(model_id=model_id, status="completed")
        return DownloadStatusResponse(model_id=model_id, status="not_found")

    snapshot = progress.snapshot() if progress else None
    error = _download_errors.get(model_id)
    state = "failed" if error else "cancelled" if snapshot and snapshot.phase == "cancelled" else "completed" if task and task.done() else "downloading"
    return DownloadStatusResponse(model_id=model_id, status=state, download=snapshot, error=error)


@local_reranker_router.post("/models/{model_id}/download/cancel")
async def cancel_download(model_id: str) -> DownloadStatusResponse:
    """Stop all writers before acknowledging cancellation; retain partial files."""
    async with _download_locks.setdefault(model_id, asyncio.Lock()):
        return await _cancel_download(model_id)


async def _cancel_download(model_id: str) -> DownloadStatusResponse:
    task = _download_tasks.get(model_id)
    if task and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if _download_progress[model_id].phase != "completed":
            _download_progress[model_id].phase = "cancelled"
    return await get_download_status(model_id)


@local_reranker_router.delete("/models/{model_id}")
async def delete_model(model_id: str) -> dict[str, str]:
    """Delete a downloaded cross-encoder model."""
    async with _download_locks.setdefault(model_id, asyncio.Lock()):
        paths = RuntimePaths()
        model_dir = Path(paths.managed_reranker_model_dir(model_id))

        # Cancel any in-progress download
        await _cancel_download(model_id)
        staging = model_dir.parent / f".{model_dir.name}.partial"
        safe_path(model_dir, ".download.json")
        safe_path(staging, ".download.json")
        if model_dir.exists() or staging.exists():
            for target in (model_dir, staging):
                if target.exists():
                    await remove_directory(target)
            _download_progress.pop(model_id, None)
            _download_errors.pop(model_id, None)
            _download_tasks.pop(model_id, None)
            return {"status": "deleted"}

        raise HTTPException(
            status_code=404,
            detail=core_i18n.t(
                "local_models.errors.not_found_on_disk", fallback="Model not found on disk"
            ),
        )


# ── Internal helpers ────────────────────────────────────────────────────


def _is_model_downloaded(model_dir: Path) -> bool:
    """Check if a model directory has the required files."""
    if not model_dir.exists():
        return False
    has_onnx = any(model_dir.glob("*.onnx")) or any(model_dir.glob("onnx/*.onnx"))
    has_tokenizer = (model_dir / "tokenizer.json").exists()
    return has_onnx and has_tokenizer


_DOWNLOAD_SIDECARS = [
    "tokenizer.json",
    "tokenizer_config.json",
    "config.json",
    "special_tokens_map.json",
    "vocab.txt",
    "sentencepiece.bpe.model",
]


def _legacy_allow_patterns() -> list[str]:
    return [
        "*.onnx",
        "onnx/*.onnx",
        "*.onnx_data",
        "onnx/*.onnx_data",
        *_DOWNLOAD_SIDECARS,
    ]


def _variant_allow_patterns(
    meta: CrossEncoderModelMeta,
    *,
    model_id: str,
    variant_override: str | None,
) -> list[str] | None:
    if not meta.variants:
        return _legacy_allow_patterns()

    variant_name = resolve_variant_name(meta, override=variant_override)
    if variant_name is None:
        raise ValueError("model_variant_unavailable")

    variant = meta.variants[variant_name]
    logger.info(
        "Resolved reranker variant %r for model %s (platform=%s, override=%r)",
        variant_name,
        model_id,
        detect_platform_key(),
        variant_override,
    )
    return [
        variant.file,
        f"{variant.file}_data",
        *_DOWNLOAD_SIDECARS,
    ]


async def _download_model_task(
    meta: CrossEncoderModelMeta, model_dir: Path, *, variant_override: str | None = None,
) -> None:
    """Resolve the selected variant, then download with shared transfer semantics."""
    tracker = _download_progress.setdefault(meta.id, DownloadTracker())
    try:
        patterns = _variant_allow_patterns(meta, model_id=meta.id, variant_override=variant_override)
        if not patterns:
            raise ValueError("model_variant_unavailable")
        await download_hub_model(meta.onnx_repo or meta.repo, patterns, model_dir, tracker, get_config().network.proxy_url())
    except asyncio.CancelledError:
        tracker.phase = "cancelled"
        raise
    except Exception:
        tracker.phase = "failed"
        _download_errors[meta.id] = "model_download_failed"
        logger.exception("Model download failed", extra={"model_id": meta.id})
