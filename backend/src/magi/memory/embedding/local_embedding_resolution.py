"""Local embedding model resolution helpers."""

from __future__ import annotations

import logging
import platform
import sys
from pathlib import Path
from typing import Optional

from ...config.local_embedding_registry import (
    LocalEmbeddingModelMeta,
    get_local_embedding_registry,
)
from ...config.models import LocalEmbeddingModelSource

logger = logging.getLogger(__name__)


def detect_platform_key() -> str:
    """Return a stable key used to look up `default_variant` in registry YAML.

    Format: f"{sys.platform}_{platform.machine().lower()}"
    Examples: 'darwin_arm64', 'win32_amd64', 'linux_x86_64'.
    """
    return f"{sys.platform}_{platform.machine().lower()}"


_EMERGENCY_FALLBACK_CHAIN = ("quantized", "int8", "fp16", "fp32")


def resolve_variant_name(
    meta: "LocalEmbeddingModelMeta | None",
    *,
    override: str | None = None,
    platform_key: str | None = None,
) -> str | None:
    """Pick a variant name from a model's ``variants`` block.

    Priority:
      1. ``override`` if set AND present in ``meta.variants``.
      2. ``meta.default_variant[platform_key]`` if valid.
      3. ``meta.default_variant['_fallback']`` if valid.
      4. First entry in ``_EMERGENCY_FALLBACK_CHAIN`` that exists in
         ``meta.variants``.
      5. Last resort: first variant in iteration order.

    Returns ``None`` if ``meta`` is ``None`` or has no ``variants`` — the
    caller should fall back to a legacy scan (``_find_onnx_model``) in that
    case.
    """
    if meta is None or not meta.variants:
        return None

    if override:
        if override in meta.variants:
            return override
        logger.warning(
            "Embedding variant override %r not in model %r variants %s; "
            "using platform default",
            override,
            meta.id,
            sorted(meta.variants.keys()),
        )

    key = platform_key or detect_platform_key()
    candidate = meta.default_variant.get(key) or meta.default_variant.get("_fallback")
    if candidate and candidate in meta.variants:
        return candidate

    for name in _EMERGENCY_FALLBACK_CHAIN:
        if name in meta.variants:
            return name

    # Last-ditch: any variant
    return next(iter(meta.variants))


def _find_onnx_model(model_dir: Path) -> Path | None:
    """Find the best ONNX model file, checking root and onnx/ subdirectory.

    Priority: model_quantized.onnx > model_int8.onnx > model.onnx > first *.onnx
    """
    for base in [model_dir, model_dir / "onnx"]:
        if not base.is_dir():
            continue
        for name in ["model_quantized.onnx", "model_int8.onnx", "model.onnx"]:
            candidate = base / name
            if candidate.exists():
                return candidate
        fallback = sorted(base.glob("*.onnx"))
        if fallback:
            return fallback[0]
    return None


class LocalEmbeddingModelResolutionMixin:
    """Resolve local embedding model directories and preset metadata."""

    def _resolve_model_dir(self) -> Optional[Path]:
        """Resolve the model directory based on config."""
        if self._config.model_source == LocalEmbeddingModelSource.EXTERNAL:
            path_str = (self._config.model_dir_path or "").strip()
            if not path_str:
                return None
            return Path(path_str).expanduser()

        model_id = (self._config.managed_model_id or "").strip()
        if not model_id:
            return None
        return Path(self._runtime_paths.managed_embedding_model_dir(model_id))

    def _get_preset_meta(self) -> Optional[LocalEmbeddingModelMeta]:
        """Look up preset metadata for the current model."""
        if self._config.model_source != LocalEmbeddingModelSource.MANAGED:
            return None
        model_id = (self._config.managed_model_id or "").strip()
        if not model_id:
            return None
        return get_local_embedding_registry().get(model_id)


__all__ = [
    "LocalEmbeddingModelResolutionMixin",
    "_find_onnx_model",
    "detect_platform_key",
    "resolve_variant_name",
]
