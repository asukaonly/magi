"""API endpoints for local embedding model management."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ... import i18n as core_i18n
from ...config.local_embedding_registry import (
    LocalEmbeddingModelMeta,
    get_local_embedding_registry,
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
local_embedding_router = APIRouter()

# Track in-progress downloads keyed by model_id
_download_tasks: dict[str, asyncio.Task[None]] = {}
_download_progress: dict[str, DownloadTracker] = {}
_download_errors: dict[str, str] = {}
_download_locks: dict[str, asyncio.Lock] = {}


# ── Response models ─────────────────────────────────────────────────────


class LocalEmbeddingVariantInfo(BaseModel):
    """One quantization variant of a local embedding model."""

    name: str
    file: str
    size_mb: int
    downloaded: bool


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
    download: DownloadProgress | None = None
    variants: list[LocalEmbeddingVariantInfo] = []
    default_variant: Optional[str] = None


class DiscoveredModel(BaseModel):
    """A model discovered in the external model directory."""

    dir_name: str
    path: str
    has_onnx: bool
    has_tokenizer: bool
    has_config: bool
    dimension: Optional[int] = None


class DownloadStatusResponse(ModelDownloadStatus):
    """Shared byte-based model transfer status."""


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
        progress = _download_progress.get(model.id)

        variants_info: list[LocalEmbeddingVariantInfo] = []
        for vname, vmeta in model.variants.items():
            candidate = model_dir / vmeta.file
            bare = model_dir / Path(vmeta.file).name
            variants_info.append(
                LocalEmbeddingVariantInfo(
                    name=vname,
                    file=vmeta.file,
                    size_mb=vmeta.size_mb,
                    downloaded=candidate.exists() or bare.exists(),
                )
            )

        default_variant_name = resolve_variant_name(model) if model.variants else None

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
                download=progress.snapshot() if progress else None,
                variants=variants_info,
                default_variant=default_variant_name,
            )
        )
    return result


@local_embedding_router.post("/models/{model_id}/download")
async def download_model(
    model_id: str,
    variant: Optional[str] = None,
) -> DownloadStatusResponse:
    """Trigger download of a preset model.

    Optional ``variant`` query parameter selects a specific ONNX quantization
    variant (e.g. ``fp32``, ``fp16``, ``quantized``). When omitted, the
    platform-preferred default from the registry is used.
    """
    async with _download_locks.setdefault(model_id, asyncio.Lock()):
        registry = get_local_embedding_registry()
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

        # Check if already downloaded
        paths = RuntimePaths()
        model_dir = Path(paths.managed_embedding_model_dir(model_id))
        # Check if the *specific* variant requested is already downloaded.
        # Falls back to the model-level check for legacy YAML (no variants block).
        if meta.variants:
            variant_name = resolve_variant_name(meta, override=variant)
            if variant_name is not None:
                variant_file = meta.variants[variant_name].file
                candidate = model_dir / variant_file
                bare = model_dir / Path(variant_file).name
                if candidate.exists() or bare.exists():
                    return DownloadStatusResponse(model_id=model_id, status="completed")
            # else: emergency-chain returned no variant; let the task try anyway
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
            raise HTTPException(
                status_code=404,
                detail=core_i18n.t(
                    "local_models.errors.unknown_model",
                    fallback="Unknown model: {model_id}",
                    model_id=model_id,
                ),
            )
        model_dir = Path(paths.managed_embedding_model_dir(model_id))
        if _is_model_downloaded(model_dir):
            return DownloadStatusResponse(model_id=model_id, status="completed")
        return DownloadStatusResponse(model_id=model_id, status="not_found")

    snapshot = progress.snapshot() if progress else None
    error = _download_errors.get(model_id)
    state = "failed" if error else "cancelled" if snapshot and snapshot.phase == "cancelled" else "completed" if task and task.done() else "downloading"
    return DownloadStatusResponse(model_id=model_id, status=state, download=snapshot, error=error)


@local_embedding_router.post("/models/{model_id}/download/cancel")
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


@local_embedding_router.delete("/models/{model_id}")
async def delete_model(model_id: str) -> dict[str, str]:
    """Delete a downloaded model."""
    async with _download_locks.setdefault(model_id, asyncio.Lock()):
        paths = RuntimePaths()
        model_dir = Path(paths.managed_embedding_model_dir(model_id))

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
    meta: LocalEmbeddingModelMeta,
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
        "Resolved variant %r for model %s (platform=%s, override=%r)",
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
    meta: LocalEmbeddingModelMeta, model_dir: Path, *, variant_override: str | None = None,
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
