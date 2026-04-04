"""Registry for preset cross-encoder reranker models."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

import yaml

logger = logging.getLogger(__name__)

_REGISTRY_FILENAME = "cross_encoder_models.yaml"


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
    return Path(__file__).resolve().parent.parent.parent.parent / "configs" / _REGISTRY_FILENAME


def get_cross_encoder_registry() -> CrossEncoderModelRegistry:
    """Return the cached preset cross-encoder model registry."""
    return load_cross_encoder_registry(_default_registry_path())
