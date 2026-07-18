"""Canonical request identity checks for idempotent memory corrections."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .fingerprints import canonical_scope_json
from .models import CorrectionKind, CorrectionTargetKind


def correction_request_fingerprint(
    *,
    actor_id: str,
    target_kind: CorrectionTargetKind,
    target_id: str,
    correction_kind: CorrectionKind,
    reason: str | None,
    replacement: Mapping[str, Any] | None,
    effective_at: float | None,
    scope: Mapping[str, Any] | None,
    source_event_id: str | None,
) -> str:
    """Fingerprint only immutable caller intent, never mutable claim identities."""
    payload = {
        "actor_id": str(actor_id).strip(),
        "target_kind": target_kind.value,
        "target_id": str(target_id).strip(),
        "correction_kind": correction_kind.value,
        "reason": normalized_optional_text(reason),
        "replacement": _canonical_request_value(replacement),
        "effective_at": float(effective_at) if effective_at is not None else None,
        "scope": json.loads(canonical_scope_json(scope)),
        "source_event_id": normalized_optional_text(source_event_id),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return f"v1:{digest}"


def normalized_optional_text(value: Any) -> str | None:
    """Normalize optional request text without changing its meaning."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _canonical_request_value(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        str(key): _canonical_scalar(item)
        for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
    }


def _canonical_scalar(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_scalar(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list):
        return [_canonical_scalar(item) for item in value]
    if isinstance(value, tuple):
        return [_canonical_scalar(item) for item in value]
    if isinstance(value, str):
        return value.strip()
    return value


__all__ = [
    "correction_request_fingerprint",
    "normalized_optional_text",
]
