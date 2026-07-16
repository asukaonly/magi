"""Process-local invalidation for stable context resolver caches."""

from __future__ import annotations

import threading
from pathlib import Path

_LOCK = threading.Lock()
_EPOCHS: dict[str, int] = {}


def _database_key(db_path: str) -> str:
    return str(Path(db_path).expanduser().resolve(strict=False))


def context_cache_epoch(db_path: str) -> int:
    """Return the current in-process cache epoch for one database."""
    with _LOCK:
        return _EPOCHS.get(_database_key(db_path), 0)


def invalidate_context_caches(db_path: str) -> int:
    """Advance the in-process cache epoch after a committed clear."""
    key = _database_key(db_path)
    with _LOCK:
        next_epoch = _EPOCHS.get(key, 0) + 1
        _EPOCHS[key] = next_epoch
        return next_epoch


__all__ = ["context_cache_epoch", "invalidate_context_caches"]
