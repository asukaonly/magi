"""Embedding-specific resolution helpers (mixin for LocalEmbeddingManager)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ...config.local_embedding_registry import (
    LocalEmbeddingModelMeta,
    get_local_embedding_registry,
)
from ...config.models import LocalEmbeddingModelSource


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


__all__ = ["LocalEmbeddingModelResolutionMixin"]
