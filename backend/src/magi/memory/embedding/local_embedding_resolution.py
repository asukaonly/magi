"""Local embedding model resolution helpers."""

from __future__ import annotations

import platform
import sys
from pathlib import Path
from typing import Optional

from ...config.local_embedding_registry import (
    LocalEmbeddingModelMeta,
    get_local_embedding_registry,
)
from ...config.models import LocalEmbeddingModelSource


def detect_platform_key() -> str:
    """Return a stable key used to look up `default_variant` in registry YAML.

    Format: f"{sys.platform}_{platform.machine().lower()}"
    Examples: 'darwin_arm64', 'win32_amd64', 'linux_x86_64'.
    """
    return f"{sys.platform}_{platform.machine().lower()}"


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
]
