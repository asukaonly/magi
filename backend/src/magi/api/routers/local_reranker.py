"""API endpoints for local cross-encoder reranker model management."""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Any, Optional

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

logger = logging.getLogger(__name__)
local_reranker_router = APIRouter()

# Track in-progress downloads keyed by model_id
_download_tasks: dict[str, asyncio.Task[None]] = {}
_download_progress: dict[str, dict[str, Any]] = {}


# ── Response models ─────────────────────────────────────────────────────


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
    download_progress_pct: Optional[float] = None


class DownloadStatusResponse(BaseModel):
    """Download progress response."""

    model_id: str
    status: str  # "downloading", "completed", "failed", "not_found"
    progress_pct: Optional[float] = None
    error: Optional[str] = None


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
        progress = _download_progress.get(model.id, {})
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
                download_progress_pct=progress.get("pct"),
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
        progress = _download_progress.get(model_id, {})
        return DownloadStatusResponse(
            model_id=model_id,
            status="downloading",
            progress_pct=progress.get("pct"),
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
    _download_progress[model_id] = {"pct": 0.0, "error": None}
    task = asyncio.create_task(
        _download_model_task(meta, model_dir, variant_override=variant)
    )
    _download_tasks[model_id] = task

    return DownloadStatusResponse(
        model_id=model_id,
        status="downloading",
        progress_pct=0.0,
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


@local_reranker_router.delete("/models/{model_id}")
async def delete_model(model_id: str) -> dict[str, str]:
    """Delete a downloaded cross-encoder model."""
    paths = RuntimePaths()
    model_dir = Path(paths.managed_reranker_model_dir(model_id))

    # Cancel any in-progress download
    task = _download_tasks.get(model_id)
    if task is not None and not task.done():
        task.cancel()

    if model_dir.exists():
        await asyncio.to_thread(shutil.rmtree, str(model_dir))
        _download_progress.pop(model_id, None)
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


_DOWNLOAD_MAX_RETRIES = 3
_DOWNLOAD_ETAG_TIMEOUT = 30


async def _download_model_task(
    meta: CrossEncoderModelMeta,
    model_dir: Path,
    *,
    variant_override: str | None = None,
) -> None:
    """Background task to download a cross-encoder model from HuggingFace with retry.

    If the meta declares a ``variants`` block, only the resolved variant's
    .onnx file (and its optional .onnx_data sidecar) is fetched, alongside
    the tokenizer/config sidecars. Without a ``variants`` block, falls
    back to the legacy broad allow patterns.
    """
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
    sidecars = [
        "tokenizer.json",
        "tokenizer_config.json",
        "config.json",
        "special_tokens_map.json",
        "vocab.txt",
        "sentencepiece.bpe.model",
    ]

    if meta.variants:
        variant_name = resolve_variant_name(meta, override=variant_override)
        if variant_name is None:
            _download_progress[model_id] = {
                "pct": None,
                "error": f"Could not resolve a variant for {model_id}",
            }
            return
        variant = meta.variants[variant_name]
        # Unconditionally include the .onnx_data sidecar pattern.
        # snapshot_download silently skips patterns that don't match, so
        # this is free for variants without external data.
        allow_patterns = [
            variant.file,
            f"{variant.file}_data",
            *sidecars,
        ]
        logger.info(
            "Resolved reranker variant %r for model %s (platform=%s, override=%r)",
            variant_name, model_id, detect_platform_key(), variant_override,
        )
    else:
        allow_patterns = [
            "*.onnx",
            "onnx/*.onnx",
            "*.onnx_data",
            "onnx/*.onnx_data",
            *sidecars,
        ]

    last_exc: Exception | None = None
    for attempt in range(1, _DOWNLOAD_MAX_RETRIES + 1):
        try:
            _download_progress[model_id] = {"pct": 5.0, "error": None}

            logger.info(
                "Downloading reranker model %s from %s (attempt %d/%d)",
                model_id,
                repo_id,
                attempt,
                _DOWNLOAD_MAX_RETRIES,
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

            if not _is_model_downloaded(model_dir):
                _download_progress[model_id] = {
                    "pct": None,
                    "error": f"Download completed but required files missing in {local_path}",
                }
                return

            _download_progress[model_id] = {"pct": 100.0, "error": None}
            logger.info("Reranker model %s downloaded to %s", model_id, model_dir)
            return

        except asyncio.CancelledError:
            _download_progress[model_id] = {"pct": None, "error": "cancelled"}
            if model_dir.exists():
                shutil.rmtree(str(model_dir), ignore_errors=True)
            raise
        except Exception as exc:
            last_exc = exc
            if attempt < _DOWNLOAD_MAX_RETRIES:
                wait = 2**attempt
                logger.warning(
                    "Download attempt %d/%d for %s failed: %s — retrying in %ds",
                    attempt,
                    _DOWNLOAD_MAX_RETRIES,
                    model_id,
                    exc,
                    wait,
                )
                _download_progress[model_id] = {
                    "pct": None,
                    "error": f"Retry {attempt}/{_DOWNLOAD_MAX_RETRIES}: {exc}",
                }
                await asyncio.sleep(wait)

    logger.error(
        "Failed to download reranker model %s after %d attempts: %s",
        model_id,
        _DOWNLOAD_MAX_RETRIES,
        last_exc,
    )
    _download_progress[model_id] = {"pct": None, "error": str(last_exc)}
