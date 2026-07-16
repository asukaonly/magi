"""Canonical request identity checks for idempotent memory corrections."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

from .fingerprints import canonical_scope_json
from .models import CorrectionKind, CorrectionTargetKind, MemoryCorrection


def correction_request_matches(
    existing: MemoryCorrection,
    *,
    actor_id: str,
    target_kind: CorrectionTargetKind,
    target_id: str,
    correction_kind: CorrectionKind,
    reason: str | None,
    replacement: Mapping[str, Any] | None,
    stored_replacement: Mapping[str, Any] | None = None,
    effective_at: float | None,
    scope: Mapping[str, Any] | None,
    source_event_id: str | None,
) -> bool:
    """Return whether a retry represents the same durable user intent."""
    return (
        existing.actor_id == actor_id
        and existing.target_kind == target_kind
        and existing.target_id == target_id
        and existing.correction_kind == correction_kind
        and normalized_optional_text(existing.reason) == normalized_optional_text(reason)
        and canonical_scope_json(existing.scope) == canonical_scope_json(scope)
        and normalized_optional_text(existing.source_event_id)
        == normalized_optional_text(source_event_id)
        and optional_float_matches(existing.effective_at, effective_at)
        and _canonical_optional_mapping(
            existing.replacement if stored_replacement is None else stored_replacement
        )
        == _canonical_optional_mapping(replacement)
    )


def normalized_optional_text(value: Any) -> str | None:
    """Normalize optional request text without changing its meaning."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def optional_float_matches(left: float | None, right: float | None) -> bool:
    """Compare optional timestamps using the SQLite write precision."""
    if left is None or right is None:
        return left is None and right is None
    return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-6)


def _canonical_optional_mapping(value: Mapping[str, Any] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = [
    "correction_request_matches",
    "normalized_optional_text",
    "optional_float_matches",
]
