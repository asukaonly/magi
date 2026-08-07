"""Assertion memory-subdomain classification."""

from __future__ import annotations


def classify_memory_subdomain(temporal_scope: str, decay_policy: str) -> str:
    """Classify an assertion as semantic memory or short-lived state."""
    normalized_scope = str(temporal_scope or "").strip().casefold()
    normalized_policy = str(decay_policy or "").strip().casefold()
    if normalized_scope in {"persistent", "stable", ""} and normalized_policy in {
        "none",
        "evidence_only",
        "",
    }:
        return "semantic"
    return "state"


__all__ = ["classify_memory_subdomain"]
