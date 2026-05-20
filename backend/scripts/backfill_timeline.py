#!/usr/bin/env python3
"""Manually fire the three non-LLM timeline scheduler handlers once to backfill data.

Useful right after deploying Plan 4: the schedulers won't fire until their
next tick (could be hours away), and existing episodes won't have their
immersive fields populated. This script runs each handler exactly once
against the production memory.db, so the UI starts showing real data
immediately.

Diary narrative (LLM-bearing) is intentionally skipped — it needs the
scenario LLM pool which only exists inside the running app. After the
desktop app starts with the Plan 4 bootstrap module, the diary scheduler
ticks every 6 hours and will populate essence_prose for yesterday.

Usage:
    cd /Users/asuka/code/magi/backend
    python scripts/backfill_timeline.py

With a custom data root:
    MAGI_DATA_ROOT=/path/to/magi-data python scripts/backfill_timeline.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

# Make `magi` importable when running from any cwd
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_SRC = SCRIPT_DIR.parent / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))


def _resolve_memory_db_path() -> Path:
    root = os.environ.get("MAGI_DATA_ROOT")
    if root:
        return Path(root).expanduser() / "memory" / "memory.db"
    return Path.home() / ".magi" / "data" / "memory" / "memory.db"


def _make_context():
    """Build a minimal ScheduledExecutionContext. The contributors only read `triggered_at`."""
    from magi.scheduler.contracts import ScheduledExecutionContext

    return ScheduledExecutionContext(
        schedule=MagicMock(name="manual_schedule"),
        target_state=MagicMock(name="manual_target_state"),
        runtime_dir=Path("/tmp"),
        triggered_at=time.time(),
        manual=True,
    )


async def main() -> None:
    memory_db_path = _resolve_memory_db_path()
    if not memory_db_path.exists():
        print(f"Memory DB not found at {memory_db_path}; aborting.")
        return

    print(f"Using memory DB: {memory_db_path}")

    from magi.memory.l2.store import L2CognitionStore
    from magi.memory.l3.daily_mood.store import DailyMoodAggregateStore
    from magi.media.source_registry import MediaSourceRegistry
    from magi.media.selector import MediaSelector
    from magi.timeline.standout.scheduler_contrib import StandoutScoringSchedulerContrib
    from magi.timeline.mood.scheduler_contrib import MoodAggregateSchedulerContrib
    from magi.timeline.mood.sample_source import L2ValenceSampleSource
    from magi.media.scheduler_contrib import RepresentativeAssetPopulateSchedulerContrib
    from magi.location import LocationSampleStore
    from magi.location.scheduler_contrib import IPGeoPollSchedulerContrib
    from magi.location.sources.ipgeo import IPGeoLocationSource

    l2_store = L2CognitionStore(db_path=str(memory_db_path))
    await l2_store.initialize()

    location_store = LocationSampleStore(db_path=str(memory_db_path))
    ipgeo = IPGeoPollSchedulerContrib(
        ipgeo_source=IPGeoLocationSource(store=location_store),
    )

    mood_store = DailyMoodAggregateStore(db_path=str(memory_db_path))
    await mood_store.initialize()

    # No photo-library adapter here — that's wired by the running app's
    # MediaRegistryModule. The asset populate handler will return None
    # for every episode and that's fine; the next real scheduler tick
    # (with the app running) will fill them in.
    media_registry = MediaSourceRegistry()
    selector = MediaSelector(registry=media_registry)

    sample_source = L2ValenceSampleSource(l2_store=l2_store)

    standout = StandoutScoringSchedulerContrib(
        l2_store=l2_store, media_registry=media_registry,
    )
    mood = MoodAggregateSchedulerContrib(
        sample_source=sample_source, mood_store=mood_store,
    )
    asset_populate = RepresentativeAssetPopulateSchedulerContrib(
        l2_store=l2_store, selector=selector,
    )

    ctx = _make_context()

    print("\n== Running standout rescoring ==")
    result = await standout._handle_rescore(ctx)
    print(f"  success={result.success} message={result.message} stats={result.stats}")

    print("\n== Running mood aggregate ==")
    result = await mood._handle_aggregate(ctx)
    print(f"  success={result.success} message={result.message} stats={result.stats}")

    print("\n== Running representative asset populate ==")
    result = await asset_populate._handle_populate(ctx)
    print(f"  success={result.success} message={result.message} stats={result.stats}")

    print("\n== Running IPGeo poll ==")
    result = await ipgeo._handle_poll(ctx)
    print(f"  success={result.success} message={result.message} stats={result.stats}")

    print("\nBackfill complete. Diary essence will populate on the next scheduler tick of the running app.")


if __name__ == "__main__":
    asyncio.run(main())
