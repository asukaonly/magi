"""Typed contracts for durable L2 projection attempt transitions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TerminalClaimFailureContext:
    """Metadata for atomically closing Claims with a terminal job failure."""

    error_type: str
    reason_code: str
    attempt_key: str | None = None
    target_id: str | None = None


__all__ = ["TerminalClaimFailureContext"]
