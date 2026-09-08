"""Content revisions for optimistic writes against authoritative snapshots."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from fastapi import HTTPException


def snapshot_revision(value: Any) -> str:
    """Return a stable opaque revision without exposing the snapshot contents."""
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def require_snapshot_revision(expected: str | None, current: str | None) -> None:
    """Validate while the resource's persistence lock is held, before side effects."""
    if not expected:
        raise HTTPException(status_code=428, detail="A current snapshot revision is required")
    if not current or not hmac.compare_digest(expected.encode("utf-8"), current.encode("utf-8")):
        raise HTTPException(status_code=409, detail="The resource changed on the center. Reload it before saving again")
