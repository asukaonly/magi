"""Context routing result models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MemoryGuidance:
    """Memory retrieval guidance from context routing."""

    recommended: bool
    route: str = "none"


__all__ = ["MemoryGuidance"]
