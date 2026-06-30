"""Registry for preset local embedding models."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, List, Optional

import yaml

from ..utils.packaged_paths import get_backend_root

logger = logging.getLogger(__name__)

_REGISTRY_FILENAME = "local_embedding_models.yaml"


@dataclass(slots=True, frozen=True)
class LocalEmbeddingVariantMeta:
    """One quantization variant of a local embedding model.

    `file` is the path inside the upstream HuggingFace repo (e.g.
    "onnx/model_fp16.onnx"). `size_mb` is the on-disk total — including any
    accompanying .onnx_data sidecar — for UI download-size display.
    """

    file: str
    size_mb: int = 0


@dataclass(slots=True)
class LocalEmbeddingModelMeta:
    """Metadata for one preset local embedding model."""

    id: str
    label: str
    repo: str
    onnx_repo: str
    dimension: int
    max_tokens: int
    pooling: str = "cls"
    normalize: bool = True
    size_mb: int = 0
    size_fp32_mb: int = 0
    quantized: bool = True
    languages: list[str] = field(default_factory=list)
    recommended: bool = False
    description: str = ""
    variants: dict[str, LocalEmbeddingVariantMeta] = field(default_factory=dict)
    default_variant: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class LocalEmbeddingModelRegistry:
    """Collection of preset local embedding models."""

    models: list[LocalEmbeddingModelMeta] = field(default_factory=list)

    def get(self, model_id: str) -> Optional[LocalEmbeddingModelMeta]:
        """Find a preset model by ID."""
        for model in self.models:
            if model.id == model_id:
                return model
        return None

    def list_ids(self) -> list[str]:
        """Return all preset model IDs."""
        return [m.id for m in self.models]


def load_local_embedding_registry(config_path: Path) -> LocalEmbeddingModelRegistry:
    """Load the local embedding model registry from YAML."""
    if not config_path.exists():
        logger.warning("Local embedding model registry not found: %s", config_path)
        return LocalEmbeddingModelRegistry()

    raw = _read_registry_yaml(config_path)
    return LocalEmbeddingModelRegistry(models=_parse_model_entries(raw.get("models")))


def _read_registry_yaml(config_path: Path) -> dict[str, Any]:
    try:
        return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.error("Failed to parse local embedding registry: %s", exc)
        return {}


def _parse_model_entries(raw_models: Any) -> List[LocalEmbeddingModelMeta]:
    models: List[LocalEmbeddingModelMeta] = []
    for entry in raw_models or []:
        model = _parse_model_entry(entry)
        if model is not None:
            models.append(model)
    return models


def _parse_model_entry(entry: Any) -> LocalEmbeddingModelMeta | None:
    if not isinstance(entry, dict) or not entry.get("id"):
        return None
    try:
        return LocalEmbeddingModelMeta(
            id=str(entry["id"]),
            label=str(entry.get("label") or entry["id"]),
            repo=str(entry.get("repo") or ""),
            onnx_repo=str(entry.get("onnx_repo") or entry.get("repo") or ""),
            dimension=int(entry.get("dimension") or 384),
            max_tokens=int(entry.get("max_tokens") or 512),
            pooling=str(entry.get("pooling") or "cls"),
            normalize=bool(entry.get("normalize", True)),
            size_mb=int(entry.get("size_mb") or 0),
            size_fp32_mb=int(entry.get("size_fp32_mb") or 0),
            quantized=bool(entry.get("quantized", True)),
            languages=list(entry.get("languages") or []),
            recommended=bool(entry.get("recommended", False)),
            description=str(entry.get("description") or ""),
            variants=_parse_variants(entry),
            default_variant=_parse_default_variant(entry),
        )
    except (ValueError, TypeError) as exc:
        logger.warning(
            "Skipping malformed local embedding model entry %r: %s",
            entry.get("id"), exc,
        )
        return None


def _parse_variants(entry: dict[str, Any]) -> dict[str, LocalEmbeddingVariantMeta]:
    raw_variants = entry.get("variants") or {}
    variants: dict[str, LocalEmbeddingVariantMeta] = {}
    if not isinstance(raw_variants, dict):
        return variants
    for name, payload in raw_variants.items():
        if not isinstance(payload, dict):
            logger.warning(
                "Skipping malformed variant %r in model %r",
                name, entry.get("id"),
            )
            continue
        file_path = payload.get("file")
        if not file_path or not isinstance(file_path, str):
            logger.warning(
                "Variant %r in model %r missing 'file'; skipped",
                name, entry.get("id"),
            )
            continue
        variants[str(name)] = LocalEmbeddingVariantMeta(
            file=file_path,
            size_mb=int(payload.get("size_mb") or 0),
        )
    return variants


def _parse_default_variant(entry: dict[str, Any]) -> dict[str, str]:
    raw_default = entry.get("default_variant") or {}
    default_variant: dict[str, str] = {}
    if not isinstance(raw_default, dict):
        return default_variant
    for platform_key, variant_name in raw_default.items():
        if isinstance(platform_key, str) and isinstance(variant_name, str):
            default_variant[platform_key] = variant_name
    return default_variant


@lru_cache(maxsize=1)
def _default_registry_path() -> Path:
    """Resolve the default registry YAML path relative to configs/."""
    return get_backend_root() / "configs" / _REGISTRY_FILENAME


def get_local_embedding_registry() -> LocalEmbeddingModelRegistry:
    """Return the cached preset local embedding model registry."""
    return load_local_embedding_registry(_default_registry_path())
