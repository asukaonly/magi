"""Process-local serialization for manual-entry mutation workflows."""

from __future__ import annotations

import asyncio
import threading
from weakref import WeakValueDictionary

_ENTRY_MUTATION_LOCKS: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
_ENTRY_MUTATION_LOCKS_GUARD = threading.Lock()


def entry_mutation_lock(entry_id: str) -> asyncio.Lock:
    """Return the shared process-local lock for one manual entry."""
    normalized = str(entry_id).strip()
    if not normalized:
        raise ValueError("entry_id must not be empty")
    with _ENTRY_MUTATION_LOCKS_GUARD:
        lock = _ENTRY_MUTATION_LOCKS.get(normalized)
        if lock is None:
            lock = asyncio.Lock()
            _ENTRY_MUTATION_LOCKS[normalized] = lock
        return lock


__all__ = ["entry_mutation_lock"]
