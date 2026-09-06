"""Frequency accumulator for L2 promotion (RFC #56 P2)."""
from __future__ import annotations

import asyncio

from magi.memory.l2.promotion_counter import L2PromotionCounter


def _counter(tmp_path):
    c = L2PromotionCounter(str(tmp_path / "promo.db"))
    asyncio.run(c.initialize())
    return c


def _capped_counter(tmp_path, *, cap, window=60.0):
    c = L2PromotionCounter(
        str(tmp_path / "promo.db"), promote_cap=cap, promote_window_seconds=window
    )
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


def test_flood_cap_limits_new_promotions_per_window(tmp_path):
    # Backfill flood: many distinct keys cross threshold in the same instant. With cap=3,
    # at most 3 may newly promote this window; the rest stay structured-only (not promoted).
    c = _capped_counter(tmp_path, cap=3, window=60.0)

    async def run():
        now = 1000.0
        results = [
            await c.bump("chrome", f"site{i}.com", f"e{i}", threshold=1, now=now)
            for i in range(10)
        ]
        promoted_flags = [promoted for _count, promoted in results]
        assert sum(promoted_flags) == 3  # exactly cap keys promoted
        assert promoted_flags[:3] == [True, True, True]  # first cap admitted
        assert all(p is False for p in promoted_flags[3:])  # rest deferred this window

    asyncio.run(run())


def test_flood_capped_key_promotes_on_a_later_event(tmp_path):
    # A key deferred by the flood cap re-promotes on its next event once the window's earlier
    # promotions have aged out — "structured-only this round, promote next round".
    c = _capped_counter(tmp_path, cap=2, window=60.0)

    async def run():
        now = 1000.0
        # Fill the window: 2 keys promote, the 3rd is deferred.
        assert (await c.bump("chrome", "a.com", "a1", threshold=1, now=now))[1] is True
        assert (await c.bump("chrome", "b.com", "b1", threshold=1, now=now))[1] is True
        assert (await c.bump("chrome", "c.com", "c1", threshold=1, now=now))[1] is False

        # A new event for the deferred key, after the window (the earlier promotions aged
        # out) -> it now promotes.
        count, promoted = await c.bump("chrome", "c.com", "c2", threshold=1, now=now + 61.0)
        assert (count, promoted) == (2, True)

    asyncio.run(run())


def test_window_boundary_is_inclusive_at_the_edge(tmp_path):
    # A promotion exactly `window` seconds old still counts toward the cap; one tick past ages out.
    c = _capped_counter(tmp_path, cap=1, window=60.0)

    async def run():
        assert (await c.bump("chrome", "a.com", "a1", threshold=1, now=1000.0))[1] is True
        # exactly at the window edge (1060 - 60 == 1000): earlier promotion still counts -> denied
        assert (await c.bump("chrome", "b.com", "b1", threshold=1, now=1060.0))[1] is False
        # one tick past the edge: earlier promotion has aged out -> admitted
        assert (await c.bump("chrome", "d.com", "d1", threshold=1, now=1060.001))[1] is True

    asyncio.run(run())


def test_legacy_rows_without_promoted_at_are_migrated_and_do_not_consume_budget(tmp_path):
    # A DB created before promoted_at existed: _ensure() must ALTER-add the column, and a
    # pre-existing promoted row (promoted_at=NULL) must stay promoted on re-bump without
    # consuming the new window budget (NULL is never counted by the cap query).
    import aiosqlite

    db_path = str(tmp_path / "legacy.db")

    async def run():
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                """
                CREATE TABLE l2_promotion_counter (
                    source_type TEXT NOT NULL, key TEXT NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0, promoted INTEGER NOT NULL DEFAULT 0,
                    first_seen REAL NOT NULL, last_seen REAL NOT NULL,
                    PRIMARY KEY (source_type, key)
                )
                """
            )
            await db.execute(
                "CREATE TABLE l2_promotion_seen (event_id TEXT PRIMARY KEY, seen_at REAL NOT NULL)"
            )
            await db.execute(
                "INSERT INTO l2_promotion_counter VALUES ('chrome','old.com',5,1,100.0,100.0)"
            )
            await db.commit()

        c = L2PromotionCounter(db_path, promote_cap=1, promote_window_seconds=60.0)
        # legacy promoted row stays promoted on re-bump (count advances, promoted preserved)
        assert await c.bump("chrome", "old.com", "x1", threshold=1, now=200.0) == (6, True)
        # its NULL promoted_at does not occupy the window -> a fresh key can still take the slot
        assert (await c.bump("chrome", "new.com", "n1", threshold=1, now=200.0))[1] is True

    asyncio.run(run())


def test_promote_cap_none_disables_the_cap(tmp_path):
    # Opt-out: with cap disabled, a flood promotes every key immediately (legacy behaviour).
    c = _capped_counter(tmp_path, cap=None)

    async def run():
        now = 1000.0
        results = [
            await c.bump("chrome", f"site{i}.com", f"e{i}", threshold=1, now=now)
            for i in range(20)
        ]
        assert all(promoted for _count, promoted in results)

    asyncio.run(run())


def test_already_promoted_key_bypasses_the_cap(tmp_path):
    # An established (already-promoted) key keeps running full L2 even when the window's new
    # promotions are saturated — the cap gates only the first crossing, not re-bumps.
    c = _capped_counter(tmp_path, cap=1, window=60.0)

    async def run():
        now = 1000.0
        # Establish one promoted key (consumes the only cap slot for this window).
        assert (await c.bump("chrome", "established.com", "e1", threshold=1, now=now))[1] is True
        # A different key cannot promote now (cap saturated).
        assert (await c.bump("chrome", "other.com", "o1", threshold=1, now=now))[1] is False
        # But the established key's re-bump stays promoted (bypasses the cap).
        assert (await c.bump("chrome", "established.com", "e2", threshold=1, now=now))[1] is True

    asyncio.run(run())


def test_concurrent_replays_count_one_event_once(tmp_path):
    c = _counter(tmp_path)
    async def run():
        results = await asyncio.gather(*[
            c.bump("browser", "same", "event:one", threshold=2) for _ in range(10)
        ])
        assert all(result == (1, False) for result in results)
        assert await c.bump("browser", "same", "event:two", threshold=2) == (2, True)
    asyncio.run(run())
