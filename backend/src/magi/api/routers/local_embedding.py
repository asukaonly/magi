"""API endpoints for local embedding model management."""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Any, Optional

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

logger = logging.getLogger(__name__)
local_embedding_router = APIRouter()

# Track in-progress downloads keyed by model_id
_download_tasks: dict[str, asyncio.Task[None]] = {}
_download_progress: dict[str, dict[str, Any]] = {}


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
    download_progress_pct: Optional[float] = None
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
                download_progress_pct=progress.get("pct"),
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
        progress = _download_progress.get(model_id, {})
        return DownloadStatusResponse(
            model_id=model_id,
            status="downloading",
            progress_pct=progress.get("pct"),
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
    _download_progress[model_id] = {"pct": 0.0, "error": None}
    task = asyncio.create_task(_download_model_task(meta, model_dir, variant_override=variant))
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


_DOWNLOAD_MAX_RETRIES = 3
_DOWNLOAD_ETAG_TIMEOUT = 30
_DOWNLOAD_READ_TIMEOUT = 60
_DOWNLOAD_SIDECARS = [
    "tokenizer.json",
    "tokenizer_config.json",
    "config.json",
    "special_tokens_map.json",
    "vocab.txt",
    "sentencepiece.bpe.model",
]


def _snapshot_download_or_error(model_id: str):
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        _download_progress[model_id] = {
            "pct": None,
            "error": "huggingface-hub is not installed. Run: pip install huggingface-hub",
        }
        return None
    return snapshot_download


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
        _download_progress[model_id] = {
            "pct": None,
            "error": f"Could not resolve a variant for {model_id}",
        }
        return None

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


async def _snapshot_to_model_dir(
    *,
    snapshot_download: Any,
    repo_id: str,
    model_dir: Path,
    allow_patterns: list[str],
) -> str:
    return await asyncio.to_thread(
        snapshot_download,
        repo_id,
        local_dir=str(model_dir),
        allow_patterns=allow_patterns,
        etag_timeout=_DOWNLOAD_ETAG_TIMEOUT,
    )


async def _handle_download_cancelled(model_id: str, model_dir: Path) -> None:
    _download_progress[model_id] = {"pct": None, "error": "cancelled"}
    if model_dir.exists():
        shutil.rmtree(str(model_dir), ignore_errors=True)


async def _sleep_before_retry(model_id: str, attempt: int, exc: Exception) -> None:
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


async def _download_with_retries(
    *,
    model_id: str,
    repo_id: str,
    model_dir: Path,
    allow_patterns: list[str],
    snapshot_download: Any,
) -> None:
    last_exc: Exception | None = None
    for attempt in range(1, _DOWNLOAD_MAX_RETRIES + 1):
        try:
            _download_progress[model_id] = {"pct": 5.0, "error": None}
            logger.info(
                "Downloading embedding model %s from %s (attempt %d/%d)",
                model_id,
                repo_id,
                attempt,
                _DOWNLOAD_MAX_RETRIES,
            )
            _download_progress[model_id] = {"pct": 10.0, "error": None}
            local_path = await _snapshot_to_model_dir(
                snapshot_download=snapshot_download,
                repo_id=repo_id,
                model_dir=model_dir,
                allow_patterns=allow_patterns,
            )
            _download_progress[model_id] = {"pct": 90.0, "error": None}
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
            await _handle_download_cancelled(model_id, model_dir)
            raise
        except Exception as exc:
            last_exc = exc
            if attempt < _DOWNLOAD_MAX_RETRIES:
                await _sleep_before_retry(model_id, attempt, exc)

    logger.error(
        "Failed to download embedding model %s after %d attempts: %s",
        model_id,
        _DOWNLOAD_MAX_RETRIES,
        last_exc,
    )
    _download_progress[model_id] = {"pct": None, "error": str(last_exc)}


async def _download_model_task(
    meta: LocalEmbeddingModelMeta,
    model_dir: Path,
    *,
    variant_override: str | None = None,
) -> None:
    """Background task to download a model from HuggingFace with retry.

    If the meta declares a ``variants`` block, only the resolved variant's
    .onnx file (and its optional sidecar weights) is fetched, alongside the
    usual tokenizer/config files. Without a ``variants`` block, falls back to
    the legacy broad allow patterns.
    """
    model_id = meta.id
    snapshot_download = _snapshot_download_or_error(model_id)
    if snapshot_download is None:
        return

    repo_id = meta.onnx_repo or meta.repo
    allow_patterns = _variant_allow_patterns(
        meta,
        model_id=model_id,
        variant_override=variant_override,
    )
    if allow_patterns is None:
        return
    await _download_with_retries(
        model_id=model_id,
        repo_id=repo_id,
        model_dir=model_dir,
        allow_patterns=allow_patterns,
        snapshot_download=snapshot_download,
    )
