"""Frequency accumulator for L2 promotion (RFC #56 P2)."""
from __future__ import annotations

import asyncio

from magi.memory.l2.promotion_counter import L2PromotionCounter


def _counter(tmp_path):
    c = L2PromotionCounter(str(tmp_path / "promo.db"))
    asyncio.run(c.initialize())
    return c


def test_bump_accumulates_and_promotes_at_threshold(tmp_path):
    c = _counter(tmp_path)

    async def run():
        # threshold 3: not promoted until the 3rd distinct event for the same key
        assert await c.bump("chrome", "github.com", "e1", threshold=3) == (1, False)
        assert await c.bump("chrome", "github.com", "e2", threshold=3) == (2, False)
        assert await c.bump("chrome", "github.com", "e3", threshold=3) == (3, True)
        # stays promoted afterwards
        assert await c.bump("chrome", "github.com", "e4", threshold=3) == (4, True)

    asyncio.run(run())


def test_bump_is_idempotent_per_event(tmp_path):
    c = _counter(tmp_path)

    async def run():
        assert await c.bump("chrome", "x.com", "e1", threshold=5) == (1, False)
        # same event id replayed -> no double count
        assert await c.bump("chrome", "x.com", "e1", threshold=5) == (1, False)
        assert await c.bump("chrome", "x.com", "e2", threshold=5) == (2, False)

    asyncio.run(run())


def test_keys_and_sources_are_independent(tmp_path):
    c = _counter(tmp_path)

    async def run():
        assert await c.bump("chrome", "a.com", "e1", threshold=2) == (1, False)
        assert await c.bump("chrome", "b.com", "e2", threshold=2) == (1, False)
        assert await c.bump("git", "a.com", "e3", threshold=2) == (1, False)  # different source

    asyncio.run(run())


def test_prune_removes_stale_unpromoted_keeps_promoted(tmp_path):
    c = _counter(tmp_path)

    async def run():
        now = 1000.0
        # one-off noise (never promoted), seen long ago
        await c.bump("chrome", "noise.com", "e1", threshold=3, now=now)
        # promoted key, also seen long ago
        await c.bump("chrome", "kept.com", "e2", threshold=1, now=now)  # threshold 1 -> promoted
        # prune with retention 100s, "now" much later -> noise is stale, kept is promoted
        deleted = await c.prune_stale(retention_seconds=100.0, now=now + 10_000.0)
        assert deleted == 1
        # noise gone -> counting it again starts fresh at 1
        assert await c.bump("chrome", "noise.com", "e9", threshold=3, now=now + 10_000.0) == (1, False)
        # promoted key survived -> still promoted
        assert await c.bump("chrome", "kept.com", "e10", threshold=1, now=now + 10_000.0) == (2, True)

    asyncio.run(run())
