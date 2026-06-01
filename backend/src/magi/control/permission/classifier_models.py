"""Risk classifier result models.

RiskSignal, ClassificationResult, and RiskLevel are promoted to the SDK layer
so plugin tools can depend on them without importing host internals.
These re-exports preserve identity with the SDK types.
"""

from __future__ import annotations

from magi_plugin_sdk.permissions import (  # noqa: F401 (re-export)
    ClassificationResult,
    RiskLevel,
    RiskSignal,
)

__all__ = ["ClassificationResult", "RiskLevel", "RiskSignal"]
