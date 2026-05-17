import time

import pytest

from magi.memory.portrait.cache import PortraitCache
from magi.memory.portrait.contracts import PortraitPayload


def _payload(session: str, persona: str) -> PortraitPayload:
    return PortraitPayload(
        session_id=session,
        persona_id=persona,
        topic="t",
        generated_at=int(time.time()),
    )


def test_set_then_get_returns_payload():
    cache = PortraitCache(ttl_seconds=300, max_entries=100)
    key = ("s1", "topic_hash", "p1")
    payload = _payload("s1", "p1")
    cache.set(key, payload)
    assert cache.get(key) is payload


def test_get_expired_entry_returns_none(monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr("magi.memory.portrait.cache.time.monotonic", lambda: now[0])
    cache = PortraitCache(ttl_seconds=300, max_entries=100)
    key = ("s1", "h", "p1")
    cache.set(key, _payload("s1", "p1"))
    now[0] += 301
    assert cache.get(key) is None


def test_invalidate_by_persona():
    cache = PortraitCache(ttl_seconds=300, max_entries=100)
    cache.set(("s1", "h", "p1"), _payload("s1", "p1"))
    cache.set(("s1", "h", "p2"), _payload("s1", "p2"))
    cache.invalidate_persona("p1")
    assert cache.get(("s1", "h", "p1")) is None
    assert cache.get(("s1", "h", "p2")) is not None


def test_lru_eviction_when_over_capacity():
    cache = PortraitCache(ttl_seconds=300, max_entries=2)
    cache.set(("s1", "h", "p1"), _payload("s1", "p1"))
    cache.set(("s2", "h", "p1"), _payload("s2", "p1"))
    # Access s1 → makes s2 the LRU
    cache.get(("s1", "h", "p1"))
    cache.set(("s3", "h", "p1"), _payload("s3", "p1"))
    assert cache.get(("s2", "h", "p1")) is None
    assert cache.get(("s1", "h", "p1")) is not None
    assert cache.get(("s3", "h", "p1")) is not None
