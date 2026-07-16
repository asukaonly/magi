"""Stable context scope fixtures shared by backend tests."""

from __future__ import annotations

import hashlib


def context_scope(**dimensions: str) -> dict[str, list[dict[str, str]]]:
    """Build a deterministic stable scope from human-readable test labels."""
    return {
        "all_of": [
            {
                "dimension": dimension,
                "context_id": (
                    f"ctx_{dimension}_"
                    f"{hashlib.sha256(f'{dimension}:{label}'.encode()).hexdigest()}"
                ),
            }
            for dimension, label in sorted(dimensions.items())
        ]
    }


__all__ = ["context_scope"]
