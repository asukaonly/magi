"""YAML loading helpers for the LLM provider registry."""

from __future__ import annotations

from pathlib import Path

import yaml

from .llm_registry_models import LLMProviderRegistryModel


def load_llm_provider_registry(path: Path, *, fallback: LLMProviderRegistryModel) -> LLMProviderRegistryModel:
    """Load provider registry from YAML, falling back to a default registry on failure."""
    if not path.exists():
        return fallback

    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        return LLMProviderRegistryModel(**data)
    except Exception:
        return fallback


__all__ = ["load_llm_provider_registry"]
