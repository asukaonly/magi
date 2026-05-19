# Timeline Immersive Redesign — Plan 4: Scheduler Wiring + Backfill

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the four scheduler contributors from Plan 2 (Diary, Standout, Mood, RepresentativeAsset) actually fire. After Plan 4: the running app schedules them at sensible intervals, the next scheduler tick populates `slice_narrative` / `essence_prose` / `magi_standout` / `representative_asset_ref` / `daily_mood_aggregate`, and the immersive frontend from Plan 3 starts showing real content.

**Architecture:** Each Plan-2 `*SchedulerContrib` class currently registers its handler only — it never writes a `ScheduleDefinition` row, so the scheduler service has no trigger to fire it. Plan 4 (a) extends each contributor's `register_schedules` to also call `scheduler.schedule_interval(...)` (mirroring `L2MaintenanceScheduleContrib`'s pattern), (b) writes a concrete `L2ValenceSampleSource` so the mood contributor has a real data feed (Plan 2 left it as a Protocol stub), and (c) adds a `TimelineSchedulersModule` lifecycle module that constructs the dependencies and runs all four registrations at bootstrap. A one-shot CLI helper triggers backfill across existing episodes so the UI gets data without waiting hours for the first tick.

**Tech Stack:** Python 3.13, existing `SchedulerService.schedule_interval`, existing `LifecycleModule` pattern from `backend/src/magi/memory/lifecycle.py:178+`, pytest-asyncio.

---

## Reference docs

- Spec: [docs/superpowers/specs/2026-05-19-timeline-immersive-redesign-design.md](../specs/2026-05-19-timeline-immersive-redesign-design.md)
- Plan 2: [2026-05-19-timeline-immersive-plan-2-generation-pipeline.md](./2026-05-19-timeline-immersive-plan-2-generation-pipeline.md)
- Existing pattern (the one we copy): [backend/src/magi/memory/l2/maintenance_schedule.py](../../../backend/src/magi/memory/l2/maintenance_schedule.py) + [backend/src/magi/memory/lifecycle.py:178](../../../backend/src/magi/memory/lifecycle.py#L178)

## What's NOT in Plan 4

- No new product features. Only wiring + backfill.
- No model config or prompt tuning — the diary narrative scenario falls back to `CORE` per Plan 2 T1; that's good enough for first runs.
- No retry/backoff beyond what's already in `L2LLMJsonClientMixin`.
- No UI changes (Plan 3 is done; once data flows in, the page renders it automatically).

## Default intervals (initial — tune later by editing constants)

| Target | Interval | Rationale |
|---|---|---|
| `TIMELINE_MOOD_AGGREGATE` | 1 hour | End-of-day handler is idempotent; running hourly catches "yesterday" once the new day begins; cheap |
| `TIMELINE_STANDOUT_RESCORE` | 2 hours | Pure compute, no LLM cost; reasonable to re-rank fairly often |
| `TIMELINE_REPRESENTATIVE_ASSET` | 4 hours | Walks episodes, calls MediaSelector; no LLM; relatively cheap |
| `TIMELINE_DIARY_NARRATIVE` | 6 hours | LLM-bearing; per Plan 2 the handler only generates yesterday once per day; running every 6h is overkill but harmless (idempotent via insight_key upsert) — actually most days the call is a no-op after the first hit |

Constants live in module scope so a maintainer can tune them in one place.

## File structure (created or modified)

**Created:**
- `backend/src/magi/timeline/mood/sample_source.py` — `L2ValenceSampleSource` concrete impl
- `backend/src/magi/timeline/lifecycle.py` — `TimelineSchedulersModule` lifecycle module
- `backend/scripts/backfill_timeline.py` — one-shot CLI to manually fire all four jobs
- `backend/tests/timeline/mood/test_sample_source.py`
- `backend/tests/timeline/test_lifecycle.py`

**Modified:**
- `backend/src/magi/timeline/narrative/scheduler_contrib.py` — add `schedule_interval` + `unregister_schedules` body
- `backend/src/magi/timeline/standout/scheduler_contrib.py` — same
- `backend/src/magi/timeline/mood/scheduler_contrib.py` — same
- `backend/src/magi/media/scheduler_contrib.py` — same
- `backend/src/magi/bootstrap/runtime_worker_builder.py` — add `TimelineSchedulersModule` to `_build_exports_and_maintenance_modules`

---

## Task 1: Extend the four scheduler contributors with `schedule_interval` calls

Each contributor's `register_schedules` currently only calls `scheduler.register_handler(...)`. Add `scheduler.schedule_interval(...)` so the SchedulerService gets a trigger to actually fire the handler. Add a matching `unregister_schedules` body that calls `scheduler.unschedule(...)`.

**Files (all modify):**
- `backend/src/magi/timeline/narrative/scheduler_contrib.py`
- `backend/src/magi/timeline/standout/scheduler_contrib.py`
- `backend/src/magi/timeline/mood/scheduler_contrib.py`
- `backend/src/magi/media/scheduler_contrib.py`

Existing tests for the 4 contributors only assert that `register_handler` was called. After this change they'd need to also expect `schedule_interval` and `unschedule` calls — UPDATE those tests too.

#### Step 1: Add constants + extend each contributor

For each file, add module-level constants and update `register_schedules` / `unregister_schedules`. Concrete pattern (apply to all four with their own names):

**For `narrative/scheduler_contrib.py`:**

```python
# Add at module top after existing imports
SCHEDULE_ID_TIMELINE_DIARY_NARRATIVE = "timeline_diary_narrative"
TARGET_KEY_TIMELINE_DIARY_NARRATIVE = "timeline_diary_narrative"
INTERVAL_SECONDS_TIMELINE_DIARY_NARRATIVE = 6 * 60 * 60  # 6 hours
```

Update `register_schedules`:

```python
    async def register_schedules(self, scheduler) -> None:
        await scheduler.register_handler(
            ScheduledTargetType.TIMELINE_DIARY_NARRATIVE,
            self._handle_diary_narrative,
        )
        await scheduler.schedule_interval(
            schedule_id=SCHEDULE_ID_TIMELINE_DIARY_NARRATIVE,
            target_type=ScheduledTargetType.TIMELINE_DIARY_NARRATIVE,
            target_key=TARGET_KEY_TIMELINE_DIARY_NARRATIVE,
            seconds=float(INTERVAL_SECONDS_TIMELINE_DIARY_NARRATIVE),
            target_payload={},
        )
```

Update `unregister_schedules`:

```python
    async def unregister_schedules(self, scheduler) -> None:
        await scheduler.unschedule(
            SCHEDULE_ID_TIMELINE_DIARY_NARRATIVE,
            target_type=ScheduledTargetType.TIMELINE_DIARY_NARRATIVE,
            target_key=TARGET_KEY_TIMELINE_DIARY_NARRATIVE,
        )
```

> Note: `register_handler` is called via `await scheduler.register_handler(...)` in the existing test fixtures (using `AsyncMock`). The real `SchedulerService.register_handler` may be sync — check by grepping the service. If it's sync, drop the `await`. Look at `backend/src/magi/memory/l2/maintenance_schedule.py:77` for the canonical pattern (it does `scheduler.register_handler(...)` without `await`).

**For `standout/scheduler_contrib.py`:**

```python
SCHEDULE_ID_TIMELINE_STANDOUT_RESCORE = "timeline_standout_rescore"
TARGET_KEY_TIMELINE_STANDOUT_RESCORE = "timeline_standout_rescore"
INTERVAL_SECONDS_TIMELINE_STANDOUT_RESCORE = 2 * 60 * 60  # 2 hours
```

Same shape — substitute names + interval.

**For `mood/scheduler_contrib.py`:**

```python
SCHEDULE_ID_TIMELINE_MOOD_AGGREGATE = "timeline_mood_aggregate"
TARGET_KEY_TIMELINE_MOOD_AGGREGATE = "timeline_mood_aggregate"
INTERVAL_SECONDS_TIMELINE_MOOD_AGGREGATE = 60 * 60  # 1 hour
```

**For `media/scheduler_contrib.py`:**

```python
SCHEDULE_ID_TIMELINE_REPRESENTATIVE_ASSET = "timeline_representative_asset"
TARGET_KEY_TIMELINE_REPRESENTATIVE_ASSET = "timeline_representative_asset"
INTERVAL_SECONDS_TIMELINE_REPRESENTATIVE_ASSET = 4 * 60 * 60  # 4 hours
```

#### Step 2: Update the existing tests to expect the new calls

The existing tests use `AsyncMock` for `scheduler`, then assert `scheduler.register_handler.assert_awaited_once()`. After this change, `scheduler.schedule_interval(...)` and (for the unregister test) `scheduler.unschedule(...)` are also called. Update each `test_*_registers_handler` test:

```python
@pytest.mark.asyncio
async def test_scheduler_contrib_registers_handler():
    from magi.timeline.narrative.scheduler_contrib import DiaryNarrativeSchedulerContrib

    contrib = DiaryNarrativeSchedulerContrib(orchestrator=AsyncMock())
    scheduler = MagicMock()
    scheduler.register_handler = AsyncMock()  # or sync — match the real signature
    scheduler.schedule_interval = AsyncMock()
    await contrib.register_schedules(scheduler)

    scheduler.register_handler.assert_called_once()  # or assert_awaited_once
    handler_args = scheduler.register_handler.call_args.args
    assert handler_args[0] == ScheduledTargetType.TIMELINE_DIARY_NARRATIVE

    scheduler.schedule_interval.assert_awaited_once()
    interval_kwargs = scheduler.schedule_interval.call_args.kwargs
    assert interval_kwargs["target_type"] == ScheduledTargetType.TIMELINE_DIARY_NARRATIVE
    assert interval_kwargs["seconds"] > 0
```

(Apply analogous updates to the other three contributor tests.)

#### Step 3: Run, expect pass

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest \
  tests/timeline/narrative/test_scheduler_contrib.py \
  tests/timeline/standout/test_scheduler_contrib.py \
  tests/timeline/mood/test_scheduler_contrib.py \
  tests/media/test_scheduler_contrib.py \
  -v
```

Expected: all existing contributor tests pass (with updated assertions).

#### Step 4: Commit

```bash
cd /Users/asuka/code/magi && git add backend/src/magi/timeline/narrative/scheduler_contrib.py backend/src/magi/timeline/standout/scheduler_contrib.py backend/src/magi/timeline/mood/scheduler_contrib.py backend/src/magi/media/scheduler_contrib.py backend/tests/timeline/narrative/test_scheduler_contrib.py backend/tests/timeline/standout/test_scheduler_contrib.py backend/tests/timeline/mood/test_scheduler_contrib.py backend/tests/media/test_scheduler_contrib.py && git commit -m "feat(timeline/scheduler): contributors write ScheduleDefinition rows via schedule_interval"
```

---

## Task 2: Concrete `L2ValenceSampleSource`

Plan 2 left `MoodAggregateSchedulerContrib`'s `sample_source` as a Protocol — no implementation existed, so nothing could be wired. This task adds a real source that pulls valence-bearing assertions from L2.

**Files:**
- Create: `backend/src/magi/timeline/mood/sample_source.py`
- Test: `backend/tests/timeline/mood/test_sample_source.py`

The source queries `L2CognitionStore.list_tom_assertions(trait_families=["mood", "valence"], temporal_clause=...)` (this method already exists per the Plan 2 survey at `backend/src/magi/memory/l2/retrieval/assertions.py:26-78`) and maps each assertion to a `(timestamp, valence_value)` pair.

For each assertion: the timestamp comes from the assertion's `observed_at` (or `created_at` if absent); the valence value comes from the assertion's `trait_value` (must be coerced to a float in `[-1, 1]`).

#### Step 1: Write failing test

Create `backend/tests/timeline/mood/test_sample_source.py`:

```python
"""Tests for L2ValenceSampleSource."""

from __future__ import annotations

import pytest


class _FakeL2Store:
    def __init__(self, assertions: list[dict]) -> None:
        self._assertions = assertions
        self.last_call: dict | None = None

    async def list_tom_assertions(self, **kwargs) -> list[dict]:
        self.last_call = kwargs
        return self._assertions


@pytest.mark.asyncio
async def test_returns_empty_when_no_assertions():
    from magi.timeline.mood.sample_source import L2ValenceSampleSource

    src = L2ValenceSampleSource(l2_store=_FakeL2Store([]))
    out = await src.list_valence_samples(start=0.0, end=1000.0)
    assert out == []


@pytest.mark.asyncio
async def test_maps_assertions_to_timestamp_valence_pairs():
    from magi.timeline.mood.sample_source import L2ValenceSampleSource

    assertions = [
        {"observed_at": 100.0, "trait_value": "0.5"},
        {"observed_at": 200.0, "trait_value": -0.3},
        {"created_at": 300.0, "trait_value": 0.0},  # falls back to created_at
    ]
    src = L2ValenceSampleSource(l2_store=_FakeL2Store(assertions))
    out = await src.list_valence_samples(start=0.0, end=500.0)
    out_sorted = sorted(out, key=lambda p: p[0])
    assert out_sorted == [(100.0, 0.5), (200.0, -0.3), (300.0, 0.0)]


@pytest.mark.asyncio
async def test_clamps_valence_to_range():
    from magi.timeline.mood.sample_source import L2ValenceSampleSource

    assertions = [
        {"observed_at": 100.0, "trait_value": 2.5},   # clamp to 1.0
        {"observed_at": 200.0, "trait_value": -5.0},  # clamp to -1.0
    ]
    src = L2ValenceSampleSource(l2_store=_FakeL2Store(assertions))
    out = await src.list_valence_samples(start=0.0, end=500.0)
    values = sorted(v for _, v in out)
    assert values == [-1.0, 1.0]


@pytest.mark.asyncio
async def test_skips_assertions_with_unparseable_trait_value():
    from magi.timeline.mood.sample_source import L2ValenceSampleSource

    assertions = [
        {"observed_at": 100.0, "trait_value": "calm"},  # non-numeric -> skip
        {"observed_at": 200.0, "trait_value": 0.5},
    ]
    src = L2ValenceSampleSource(l2_store=_FakeL2Store(assertions))
    out = await src.list_valence_samples(start=0.0, end=500.0)
    assert len(out) == 1
    assert out[0] == (200.0, 0.5)


@pytest.mark.asyncio
async def test_passes_window_to_temporal_clause():
    from magi.timeline.mood.sample_source import L2ValenceSampleSource

    store = _FakeL2Store([])
    src = L2ValenceSampleSource(l2_store=store)
    await src.list_valence_samples(start=100.0, end=200.0)
    assert store.last_call is not None
    # Trait families should be the mood/valence subset
    assert "mood" in store.last_call.get("trait_families", [])
    # Temporal clause should constrain to the window
    clause = store.last_call.get("temporal_clause")
    assert clause is not None  # exact shape verified by inspecting the real list_tom_assertions API
```

#### Step 2: Run, expect failure (module missing)

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest tests/timeline/mood/test_sample_source.py -v
```

#### Step 3: Create the implementation

Create `backend/src/magi/timeline/mood/sample_source.py`:

```python
"""Concrete sample source for MoodAggregateSchedulerContrib.

Queries L2 tom_trait_assertions filtered to mood/valence trait families
within a time window, normalizes each into a (timestamp, valence) pair
clamped to [-1.0, 1.0]. Plan 4 wiring; Plan 2 left this as a Protocol stub.
"""

from __future__ import annotations

from typing import Any, Protocol


class _L2StoreProtocol(Protocol):
    async def list_tom_assertions(self, **kwargs) -> list[dict[str, Any]]: ...


# Trait families that count as valence-bearing for the mood aggregate.
# Keep narrow — Plan 4 ships with just "mood" and "valence"; expansion is a
# tuning decision that lives in this constant.
MOOD_TRAIT_FAMILIES = ["mood", "valence"]


class L2ValenceSampleSource:
    """Concrete `_SampleSourceProtocol` implementation backed by L2 assertions."""

    def __init__(self, *, l2_store: _L2StoreProtocol) -> None:
        self._l2_store = l2_store

    async def list_valence_samples(
        self, *, start: float, end: float,
    ) -> list[tuple[float, float]]:
        try:
            assertions = await self._l2_store.list_tom_assertions(
                trait_families=MOOD_TRAIT_FAMILIES,
                temporal_clause=("observed_at >= ? AND observed_at <= ?", [start, end]),
                limit=10000,
            )
        except Exception:
            return []

        samples: list[tuple[float, float]] = []
        for assertion in assertions or []:
            ts = assertion.get("observed_at")
            if ts is None:
                ts = assertion.get("created_at")
            if ts is None:
                continue
            try:
                timestamp = float(ts)
            except (TypeError, ValueError):
                continue

            raw_value = assertion.get("trait_value")
            try:
                valence = float(raw_value)
            except (TypeError, ValueError):
                continue
            # Clamp to [-1.0, 1.0]
            valence = max(-1.0, min(1.0, valence))

            samples.append((timestamp, valence))

        return samples
```

> **Implementer adaptation:** the `temporal_clause` argument shape — `(sql_fragment, params_list)` — is my best guess based on the Plan-2 survey note ("Pass `trait_families=[...]` and `temporal_clause` lets time-range filtering"). Inspect `backend/src/magi/memory/l2/retrieval/assertions.py:26-78` for the exact format. If it's a different shape (e.g., a dict or two separate `time_start`/`time_end` kwargs), adapt the call here. Don't change the test's assertion about `temporal_clause` if the shape differs — instead update the test to assert what the real API accepts.

#### Step 4: Run, expect pass

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest tests/timeline/mood/test_sample_source.py -v
```

Expected: 5 passed.

#### Step 5: Commit

```bash
cd /Users/asuka/code/magi && git add backend/src/magi/timeline/mood/sample_source.py backend/tests/timeline/mood/test_sample_source.py && git commit -m "feat(timeline/mood): L2ValenceSampleSource concrete implementation"
```

---

## Task 3: `TimelineSchedulersModule` lifecycle wrapper

A single bootstrap module that constructs all dependencies and registers all four contributors. Mirrors the pattern in `backend/src/magi/memory/lifecycle.py:178` (`L2MaintenanceScheduleRegistrationModule`).

**Files:**
- Create: `backend/src/magi/timeline/lifecycle.py`
- Test: `backend/tests/timeline/test_lifecycle.py`

This module runs in the runtime-worker exports/maintenance phase so it can depend on `unified_memory`, `media_source_registry`, `scenario_llm_pool`, and `scheduler_service` all being initialized.

#### Step 1: Inspect the bootstrap context surface for the deps we need

```bash
cd /Users/asuka/code/magi/backend && grep -n "scenario_llm_pool\|scheduler_service\|media_source_registry\|unified_memory" src/magi/bootstrap/context.py | head -15
```

Confirm where each lives on the context object. Expected (per Plan 2 + 3 wiring):
- `context.memory.unified_memory` — provides `.l2` (L2CognitionStore) and `.l3` (L3SummaryStore)
- `context.memory.media_source_registry` — set by `MediaRegistryModule`
- `context.scheduler.scheduler_service` — set by `SchedulerModule`
- `context.llm.scenario_llm_pool` (or similar) — set by `LLMRuntime` module

If any path is non-obvious, adapt the imports below to match the real attribute names.

#### Step 2: Write the failing test

Create `backend/tests/timeline/test_lifecycle.py`:

```python
"""Tests for TimelineSchedulersModule."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_init_registers_all_four_contributors_when_deps_present():
    from magi.timeline.lifecycle import TimelineSchedulersModule
    from magi.scheduler.contracts import ScheduledTargetType

    # Mock context with all required deps
    context = MagicMock()
    context.memory.unified_memory.l2 = MagicMock()
    context.memory.unified_memory.memory_db_path = "/tmp/fake/memory.db"
    context.memory.media_source_registry = MagicMock()

    scheduler = MagicMock()
    scheduler.register_handler = AsyncMock()
    scheduler.schedule_interval = AsyncMock()
    context.scheduler.scheduler_service = scheduler

    # Mock LLM pool (may live at context.llm or similar — adapt as needed)
    context.llm.scenario_llm_pool = MagicMock()

    module = TimelineSchedulersModule(context)
    await module.init()

    # All four target types should have been registered with the scheduler
    registered_targets = {
        call.args[0] for call in scheduler.register_handler.call_args_list
    }
    assert ScheduledTargetType.TIMELINE_DIARY_NARRATIVE in registered_targets
    assert ScheduledTargetType.TIMELINE_STANDOUT_RESCORE in registered_targets
    assert ScheduledTargetType.TIMELINE_MOOD_AGGREGATE in registered_targets
    assert ScheduledTargetType.TIMELINE_REPRESENTATIVE_ASSET in registered_targets

    # And all four should have written a schedule_interval row
    assert scheduler.schedule_interval.await_count == 4


@pytest.mark.asyncio
async def test_init_is_noop_when_scheduler_missing():
    """If scheduler isn't initialized, the module logs and exits cleanly."""
    from magi.timeline.lifecycle import TimelineSchedulersModule

    context = MagicMock()
    context.scheduler.scheduler_service = None

    module = TimelineSchedulersModule(context)
    # Should not raise
    await module.init()


@pytest.mark.asyncio
async def test_shutdown_unregisters_all_four_contributors():
    from magi.timeline.lifecycle import TimelineSchedulersModule

    context = MagicMock()
    context.memory.unified_memory.l2 = MagicMock()
    context.memory.unified_memory.memory_db_path = "/tmp/fake/memory.db"
    context.memory.media_source_registry = MagicMock()
    scheduler = MagicMock()
    scheduler.register_handler = AsyncMock()
    scheduler.schedule_interval = AsyncMock()
    scheduler.unschedule = AsyncMock()
    context.scheduler.scheduler_service = scheduler
    context.llm.scenario_llm_pool = MagicMock()

    module = TimelineSchedulersModule(context)
    await module.init()
    await module.shutdown()

    # Four unschedule calls
    assert scheduler.unschedule.await_count == 4
```

#### Step 3: Run, expect failure (module missing)

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest tests/timeline/test_lifecycle.py -v
```

#### Step 4: Create the lifecycle module

Create `backend/src/magi/timeline/lifecycle.py`:

```python
"""Bootstrap module that wires the four Plan 2 schedulers."""

from __future__ import annotations

from typing import Any

from ..bootstrap.lifecycle import LifecycleModule
from ..core.logger import get_logger

logger = get_logger("magi.timeline.lifecycle")


class TimelineSchedulersModule(LifecycleModule):
    """Construct and register the four timeline scheduler contributors.

    Depends on:
      - context.scheduler.scheduler_service (SchedulerModule)
      - context.memory.unified_memory (MemoryStoreModule) — provides .l2, .memory_db_path
      - context.memory.media_source_registry (MediaRegistryModule)
      - context.llm.scenario_llm_pool (LLMRuntime) — for diary narrative client

    If any required dep is missing, the affected contributors are silently
    skipped (with a warning) rather than crashing bootstrap.
    """

    def __init__(self, context) -> None:
        super().__init__(
            name="runtime_timeline_schedulers",
            dependencies=(
                "runtime_scheduler",
                "runtime_configuration",
                "runtime_memory",
                "runtime_exports",
            ),
        )
        self._context = context
        self._contribs: list[Any] = []

    async def init(self) -> None:
        scheduler_service = getattr(self._context.scheduler, "scheduler_service", None)
        if scheduler_service is None:
            logger.warning("TimelineSchedulersModule skipped: scheduler_service unavailable")
            return

        # Lazy imports so module construction stays cheap and so circular-import
        # risk is contained to the init phase
        from .narrative.scheduler_contrib import DiaryNarrativeSchedulerContrib
        from .narrative.orchestrator import DiaryNarrativeOrchestrator
        from .narrative.llm_client import DiaryNarrativeLLMClient
        from .standout.scheduler_contrib import StandoutScoringSchedulerContrib
        from .mood.scheduler_contrib import MoodAggregateSchedulerContrib
        from .mood.sample_source import L2ValenceSampleSource
        from ..media.scheduler_contrib import RepresentativeAssetPopulateSchedulerContrib
        from ..media.selector import MediaSelector
        from ..memory.l3.daily_mood.store import DailyMoodAggregateStore

        unified = getattr(self._context.memory, "unified_memory", None)
        l2_store = getattr(unified, "l2", None) if unified else None
        l3_store = getattr(unified, "l3", None) if unified else None
        memory_db_path = getattr(unified, "memory_db_path", None) if unified else None
        media_registry = getattr(self._context.memory, "media_source_registry", None)
        scenario_pool = getattr(getattr(self._context, "llm", None), "scenario_llm_pool", None)

        # 1. Diary narrative (depends on: l2_store, l3_store, scenario_pool)
        if l2_store is not None and l3_store is not None:
            llm_client = DiaryNarrativeLLMClient(scenario_llm_pool=scenario_pool)
            orchestrator = DiaryNarrativeOrchestrator(
                l2_store=l2_store, l3_store=l3_store, llm_client=llm_client,
            )
            contrib = DiaryNarrativeSchedulerContrib(orchestrator=orchestrator)
            await contrib.register_schedules(scheduler_service)
            self._contribs.append(contrib)
            logger.info("Registered TIMELINE_DIARY_NARRATIVE scheduler")
        else:
            logger.warning(
                "Skipping diary narrative scheduler: l2_store=%s l3_store=%s",
                l2_store, l3_store,
            )

        # 2. Standout rescoring (depends on: l2_store, media_registry)
        if l2_store is not None and media_registry is not None:
            contrib = StandoutScoringSchedulerContrib(
                l2_store=l2_store, media_registry=media_registry,
            )
            await contrib.register_schedules(scheduler_service)
            self._contribs.append(contrib)
            logger.info("Registered TIMELINE_STANDOUT_RESCORE scheduler")
        else:
            logger.warning("Skipping standout scheduler: missing deps")

        # 3. Mood aggregate (depends on: l2_store for sample source, memory_db_path for store)
        if l2_store is not None and memory_db_path is not None:
            sample_source = L2ValenceSampleSource(l2_store=l2_store)
            mood_store = DailyMoodAggregateStore(db_path=str(memory_db_path))
            await mood_store.initialize()
            contrib = MoodAggregateSchedulerContrib(
                sample_source=sample_source, mood_store=mood_store,
            )
            await contrib.register_schedules(scheduler_service)
            self._contribs.append(contrib)
            logger.info("Registered TIMELINE_MOOD_AGGREGATE scheduler")
        else:
            logger.warning("Skipping mood aggregate scheduler: missing deps")

        # 4. Representative asset populate (depends on: l2_store, media_registry)
        if l2_store is not None and media_registry is not None:
            selector = MediaSelector(registry=media_registry)
            contrib = RepresentativeAssetPopulateSchedulerContrib(
                l2_store=l2_store, selector=selector,
            )
            await contrib.register_schedules(scheduler_service)
            self._contribs.append(contrib)
            logger.info("Registered TIMELINE_REPRESENTATIVE_ASSET scheduler")
        else:
            logger.warning("Skipping representative-asset scheduler: missing deps")

    async def shutdown(self) -> None:
        scheduler_service = getattr(self._context.scheduler, "scheduler_service", None)
        if scheduler_service is None:
            self._contribs = []
            return
        for contrib in self._contribs:
            try:
                await contrib.unregister_schedules(scheduler_service)
            except Exception as exc:
                logger.warning("Failed to unregister contrib %s: %s", type(contrib).__name__, exc)
        self._contribs = []
```

> **Adaptation note:** the `LifecycleModule` base class import (`from ..bootstrap.lifecycle import LifecycleModule`) is a guess. The MediaRegistryModule from Plan 2 T11 already imports it — copy its actual import path. The Plan 2 T11 implementer's report mentioned the base class uses `init()` / `shutdown()` (not `_setup` / `_teardown`), which matches what's used here.

#### Step 5: Run, expect pass

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest tests/timeline/test_lifecycle.py -v
```

Expected: 3 passed.

#### Step 6: Commit

```bash
cd /Users/asuka/code/magi && git add backend/src/magi/timeline/lifecycle.py backend/tests/timeline/test_lifecycle.py && git commit -m "feat(timeline): TimelineSchedulersModule wires all 4 Plan-2 contributors at bootstrap"
```

---

## Task 4: Wire `TimelineSchedulersModule` into the bootstrap

**Files:**
- Modify: `backend/src/magi/bootstrap/runtime_worker_builder.py`

#### Step 1: Add the import and module instantiation

In `backend/src/magi/bootstrap/runtime_worker_builder.py`, locate the import block that brings in the L2/L3/L4 schedule registration modules (lines 38-40 area). Add the new import. Find a line like:

```python
from ..memory.lifecycle import (
    L2MaintenanceScheduleRegistrationModule,
    L3SummaryScheduleRegistrationModule,
    L4MaintenanceScheduleRegistrationModule,
    MemoryIngestionSubscriberModule,
    MemoryStoreModule,
)
```

Add a sibling import for the new module:

```python
from ..timeline.lifecycle import TimelineSchedulersModule
```

Then locate `_build_exports_and_maintenance_modules` (around line 158-168 — the function that returns the L2/L3/L4 scheduler registration modules). Add `TimelineSchedulersModule(context)` to the returned list, right after the other scheduler registration modules:

```python
def _build_exports_and_maintenance_modules(context: RuntimeBootstrapContext) -> list[LifecycleModule]:
    return [
        RuntimeExportsModule(context),
        ControlPlaneModule(context),
        L2MaintenanceScheduleRegistrationModule(context),
        L3SummaryScheduleRegistrationModule(context),
        L4MaintenanceScheduleRegistrationModule(context),
        TimelineSchedulersModule(context),  # NEW
        OtherDependenciesModule(context),
        ChannelsModule(context),
    ]
```

#### Step 2: Smoke-check the module is importable

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH python -c "
from magi.bootstrap.runtime_worker_builder import _build_exports_and_maintenance_modules
import inspect
print('imports OK')
print('exports module names contain TimelineSchedulersModule:', 'TimelineSchedulersModule' in inspect.getsource(_build_exports_and_maintenance_modules))
"
```

Expected: `imports OK` and `True`.

#### Step 3: Commit

```bash
cd /Users/asuka/code/magi && git add backend/src/magi/bootstrap/runtime_worker_builder.py && git commit -m "feat(bootstrap): register TimelineSchedulersModule in runtime worker"
```

---

## Task 5: Backfill helper script

So the user doesn't wait hours for the first scheduler tick. A simple CLI that imports the contributors, builds a minimal stand-in context, and triggers all four handlers once.

**Files:**
- Create: `backend/scripts/backfill_timeline.py`

This script doesn't need tests — it's a one-shot operational tool. It should:
1. Open the existing memory.db / l1_events.db (read from `~/.magi/data/memory/`)
2. Construct an `L2CognitionStore`, `L3SummaryStore`, `DailyMoodAggregateStore`
3. Construct the four contributors with their deps
4. Call each `_handle_*` method directly with a synthesized `ScheduledExecutionContext`
5. Print stats

#### Step 1: Create the script

Create `backend/scripts/backfill_timeline.py`:

```python
#!/usr/bin/env python3
"""Manually fire the four timeline scheduler handlers once to backfill data.

Useful right after deploying Plan 4: the schedulers won't fire until their
next tick (which could be hours away), and existing episodes/L1 events
won't have their immersive fields populated. This script runs each handler
exactly once against the production memory.db, so the UI starts showing
real data immediately.

Usage:
    cd /Users/asuka/code/magi/backend
    python scripts/backfill_timeline.py

Or with a custom data root:
    MAGI_DATA_ROOT=/path/to/data python scripts/backfill_timeline.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

# Make `magi` importable when running from anywhere
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent / "src"))

from magi.scheduler.contracts import ScheduledExecutionContext


def _resolve_memory_db_path() -> Path:
    root = os.environ.get("MAGI_DATA_ROOT")
    if root:
        return Path(root).expanduser() / "memory" / "memory.db"
    return Path.home() / ".magi" / "data" / "memory" / "memory.db"


def _make_context() -> ScheduledExecutionContext:
    """Build a minimal context. The contributors only read `triggered_at`."""
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

    # Note: diary narrative requires the LLM scenario pool which the desktop
    # app sets up during bootstrap. Running it from a standalone script needs
    # the same config/credentials wiring — out of scope for the backfill helper.
    # The 3 non-LLM jobs below fully populate standout / mood / asset slots.
    # For diary essence, wait for the desktop app's scheduler tick (or manually
    # trigger via the running app's IPC).

    l2_store = L2CognitionStore(db_path=str(memory_db_path))
    await l2_store.initialize()

    mood_store = DailyMoodAggregateStore(db_path=str(memory_db_path))
    await mood_store.initialize()

    media_registry = MediaSourceRegistry()
    # Photo-library adapter would normally register here via the running app's
    # MediaRegistryModule. For the script we skip that; representative_asset
    # will return None for every episode and that's fine — the next real
    # scheduler tick (with the app running) will fill them in.

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

    print("\nBackfill complete. Diary essence will populate on the next scheduler tick of the running app.")


if __name__ == "__main__":
    asyncio.run(main())
```

#### Step 2: Make it executable

```bash
chmod +x /Users/asuka/code/magi/backend/scripts/backfill_timeline.py
```

#### Step 3: Commit

```bash
cd /Users/asuka/code/magi && git add backend/scripts/backfill_timeline.py && git commit -m "feat(scripts): backfill_timeline.py — one-shot trigger for the 3 non-LLM handlers"
```

---

## Task 6: Verify end-to-end

**Files:** none modified — validation only.

- [ ] **Step 1: Run the full Plan-4 test suite**

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest \
  tests/timeline/test_lifecycle.py \
  tests/timeline/mood/ \
  tests/timeline/standout/ \
  tests/timeline/narrative/ \
  tests/media/test_scheduler_contrib.py \
  --no-header 2>&1 | tail -5
```

Expected: all pass. Updated contributor tests pass with new `schedule_interval` assertions; new sample source + lifecycle tests pass.

- [ ] **Step 2: Run the backfill script against the user's real data**

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH python scripts/backfill_timeline.py
```

Expected: 3 success messages with non-zero stats. If "scored 0 episodes" or "populated 0 refs", investigate (likely no active episodes, or photo adapter not registered).

- [ ] **Step 3: Verify DB state changes**

```bash
sqlite3 ~/.magi/data/memory/memory.db "SELECT SUM(magi_standout) AS standouts, SUM(CASE WHEN representative_asset_ref != '' THEN 1 ELSE 0 END) AS with_photo FROM episodes;"
sqlite3 ~/.magi/data/memory/memory.db "SELECT COUNT(*) FROM daily_mood_aggregate;"
```

Expected: standouts > 0 (assuming some active episodes meet the heuristic threshold) and daily_mood_aggregate has at least 1 row (yesterday).

- [ ] **Step 4: Check the scheduler table got the new schedules**

```bash
sqlite3 ~/.magi/runtime/scheduler.db "SELECT target_type, target_key, enabled FROM schedules WHERE target_type LIKE 'timeline_%';"
```

Expected: 4 rows for `timeline_diary_narrative`, `timeline_standout_rescore`, `timeline_mood_aggregate`, `timeline_representative_asset`, all `enabled=1`. (These appear after the desktop app starts with the new bootstrap module.)

- [ ] **Step 5: Restart the desktop app and verify the new schedules show up**

After running `npm tauri dev` (or however the desktop app starts), the `TimelineSchedulersModule` should run during bootstrap, write the 4 schedule rows, and start ticking.

```bash
sqlite3 ~/.magi/runtime/scheduler.db "SELECT target_type, json_extract(trigger_config, '$.seconds') AS interval_seconds, enabled FROM schedules WHERE target_type LIKE 'timeline_%';"
```

Expected: 4 rows with their respective interval seconds (3600 / 7200 / 14400 / 21600).

- [ ] **Step 6: Final commit if any cleanup**

```bash
cd /Users/asuka/code/magi && git status
# If any cleanup commits are needed:
git add -A && git commit -m "fix(timeline): Plan 4 sweep cleanup"
```

---

## Acceptance criteria for Plan 4

- The 4 timeline scheduler contributors write `ScheduleDefinition` rows to `~/.magi/runtime/scheduler.db` when the desktop app starts.
- The bootstrap composition root instantiates `TimelineSchedulersModule` and runs its `init()` once at startup.
- The mood aggregator has a concrete `L2ValenceSampleSource` and stops being a no-op.
- After running the backfill script, the DB has non-zero `magi_standout` episodes (assuming any meet the scoring threshold) and at least one `daily_mood_aggregate` row.
- After ≥ 6 hours of running the desktop app (or one manual app-side trigger), at least one L3 summary with `narrative_style='diary_2p'` and non-empty `essence_prose` exists for yesterday.
- The immersive timeline UI starts showing real `essence_prose` (in the hero), slice narratives, mood-colored calendar days, and standout list entries — without any frontend changes.

## Where to go after Plan 4

- **Diary narrative quality eval**: the first batch of LLM-generated essence/slice prose needs a human pass. If quality is poor, iterate the prompt in `prompts.py`.
- **Photo-library plugin resolver**: `_resolve_photo_library_asset` in `service.py` is still a stub that returns `None`. To get hero photos showing, the photo-library plugin needs to expose a host-callable resolve API.
- **Tunable intervals**: the constants in each contributor module can be moved to config (`config.agent.timeline.diary_narrative_interval_seconds`, etc.) so they're user-tunable without a code change.
- **State-shift signal**: standout scoring still hardcodes `state_shift_count=0`. Plug in L3 state-marker data.
- **`memory_db_path` on UnifiedMemoryStore**: Plan 2 left this implicit; the mood scheduler currently relies on it being attached. If it's missing in production, the mood scheduler silently skips — verify and surface as a real attribute.
