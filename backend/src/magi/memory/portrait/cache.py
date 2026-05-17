"""In-memory LRU cache for persona portraits with TTL eviction.

Keyed by (session_id, topic_hash, persona_id). Topic hash is opaque to this
module — callers compute it (typically sha1 of normalized topic + entities).
"""

from __future__ import annotations

import time
from collections import OrderedDict
from threading import RLock
from typing import Tuple

from .contracts import PortraitPayload


CacheKey = Tuple[str, str, str]


class PortraitCache:
    """Thread-safe LRU + TTL cache for portraits."""

    def __init__(self, *, ttl_seconds: float = 300.0, max_entries: int = 256) -> None:
        self._ttl = float(ttl_seconds)
        self._max = int(max_entries)
        self._data: OrderedDict[CacheKey, tuple[float, PortraitPayload]] = OrderedDict()
        self._lock = RLock()

    def get(self, key: CacheKey) -> PortraitPayload | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            ts, payload = entry
            if time.monotonic() - ts > self._ttl:
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)
            return payload

    def set(self, key: CacheKey, payload: PortraitPayload) -> None:
        with self._lock:
            self._data[key] = (time.monotonic(), payload)
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def invalidate_persona(self, persona_id: str) -> None:
        with self._lock:
            stale = [k for k in self._data if k[2] == persona_id]
            for k in stale:
                self._data.pop(k, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
