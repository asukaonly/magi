"""Registry for preset cross-encoder reranker models."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

import yaml

from ..utils.packaged_paths import get_backend_root

logger = logging.getLogger(__name__)

_REGISTRY_FILENAME = "cross_encoder_models.yaml"


@dataclass(slots=True, frozen=True)
class CrossEncoderVariantMeta:
    """One quantization/architecture variant of a cross-encoder model.

    ``file`` is the path inside the upstream HuggingFace repo (e.g.
    "onnx/model_qint8_arm64.onnx"). ``size_mb`` is the on-disk total —
    including any accompanying .onnx_data sidecar — for UI display.
    """

    file: str
    size_mb: int = 0


@dataclass(slots=True)
class CrossEncoderModelMeta:
    """Metadata for one preset cross-encoder model."""

    id: str
    label: str
    repo: str
    onnx_repo: str
    max_tokens: int = 512
    size_mb: int = 0
    languages: list[str] = field(default_factory=list)
    recommended: bool = False
    description: str = ""
    variants: dict[str, CrossEncoderVariantMeta] = field(default_factory=dict)
    default_variant: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class CrossEncoderModelRegistry:
    """Collection of preset cross-encoder models."""

    models: list[CrossEncoderModelMeta] = field(default_factory=list)

    def get(self, model_id: str) -> Optional[CrossEncoderModelMeta]:
        for model in self.models:
            if model.id == model_id:
                return model
        return None

    def list_ids(self) -> list[str]:
        return [m.id for m in self.models]


def load_cross_encoder_registry(config_path: Path) -> CrossEncoderModelRegistry:
    """Load the cross-encoder model registry from YAML."""
    if not config_path.exists():
        logger.warning("Cross-encoder model registry not found: %s", config_path)
        return CrossEncoderModelRegistry()

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.error("Failed to parse cross-encoder registry: %s", exc)
        return CrossEncoderModelRegistry()

    models: List[CrossEncoderModelMeta] = []
    for entry in raw.get("models") or []:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        try:
            # Parse variants block
            raw_variants = entry.get("variants") or {}
            variants: dict[str, CrossEncoderVariantMeta] = {}
            if isinstance(raw_variants, dict):
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
                    variants[str(name)] = CrossEncoderVariantMeta(
                        file=file_path,
                        size_mb=int(payload.get("size_mb") or 0),
                    )

            raw_default = entry.get("default_variant") or {}
            default_variant: dict[str, str] = {}
            if isinstance(raw_default, dict):
                for plat, vname in raw_default.items():
                    if isinstance(plat, str) and isinstance(vname, str):
                        default_variant[plat] = vname

            models.append(
                CrossEncoderModelMeta(
                    id=str(entry["id"]),
                    label=str(entry.get("label") or entry["id"]),
                    repo=str(entry.get("repo") or ""),
                    onnx_repo=str(entry.get("onnx_repo") or entry.get("repo") or ""),
                    max_tokens=int(entry.get("max_tokens") or 512),
                    size_mb=int(entry.get("size_mb") or 0),
                    languages=list(entry.get("languages") or []),
                    recommended=bool(entry.get("recommended", False)),
                    description=str(entry.get("description") or ""),
                    variants=variants,
                    default_variant=default_variant,
                )
            )
        except (ValueError, TypeError) as exc:
            logger.warning(
                "Skipping malformed cross-encoder model entry %r: %s",
                entry.get("id"),
                exc,
            )
    return CrossEncoderModelRegistry(models=models)


@lru_cache(maxsize=1)
def _default_registry_path() -> Path:
    return get_backend_root() / "configs" / _REGISTRY_FILENAME


def get_cross_encoder_registry() -> CrossEncoderModelRegistry:
    """Return the cached preset cross-encoder model registry."""
    return load_cross_encoder_registry(_default_registry_path())
