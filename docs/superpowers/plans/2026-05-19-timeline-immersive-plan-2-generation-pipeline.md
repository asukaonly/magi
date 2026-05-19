# Timeline Immersive Redesign — Plan 2: Generation Pipeline + Scoring + Media

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill the data slots Plan 1 created. After Plan 2: every active L2 episode acquires LLM-generated `slice_narrative` + `slice_sensory_detail`; relevant L3 reflections acquire 2nd-person `essence_prose`; episodes get auto-scored `magi_standout` + `standout_score`; days get `daily_mood_aggregate` rows; episodes acquire `representative_asset_ref` selected from a photo-library MediaSource. **Still no user-visible change** — that comes in Plan 3 (frontend rewrite).

**Architecture:** A new LLM scenario `timeline.diary_narrative` (registered in the existing `ScenarioLLMPool`) backs a single-shot generation that produces a period essence + per-episode prose in one call. Three independent scheduler contributors handle: (a) diary narrative end-of-day/week/month generation, (b) standout heuristic re-scoring, (c) `daily_mood_aggregate` end-of-day computation. The `MediaSourceRegistry` from Plan 1 gets its first source — an L1-event-backed `PhotoLibraryMediaSource` that queries existing `source_type="photo_library"` events without modifying the plugin itself. A fourth scheduler contributor populates `representative_asset_ref` per active episode.

**Tech Stack:** Python 3.13, FastAPI/aiosqlite (existing), `L2LLMJsonClientMixin` for JSON-mode LLM calls with built-in retry, Alembic (existing), pytest-asyncio. Scheduler integration mirrors `SensorSchedulerContrib` (`backend/src/magi/awareness/scheduler_contrib.py`) and `MEMORY_L2_MAINTENANCE` patterns.

---

## Reference docs

- Spec: [docs/superpowers/specs/2026-05-19-timeline-immersive-redesign-design.md](../specs/2026-05-19-timeline-immersive-redesign-design.md)
- Plan 1 (foundations): [2026-05-19-timeline-immersive-plan-1-backend-foundations.md](./2026-05-19-timeline-immersive-plan-1-backend-foundations.md)
- Architecture: [docs/timeline-domain-architecture.md](../../timeline-domain-architecture.md), [docs/memory-system-design.md](../../memory-system-design.md)
- Existing LLM scenario reference: [backend/src/magi/llm/scenario_pool.py](../../../backend/src/magi/llm/scenario_pool.py)
- Existing JSON-mode helper: [backend/src/magi/memory/l2/llm_json_client.py](../../../backend/src/magi/memory/l2/llm_json_client.py)
- Existing scheduler contributor reference: [backend/src/magi/awareness/scheduler_contrib.py](../../../backend/src/magi/awareness/scheduler_contrib.py)

## What's NOT in Plan 2

- Frontend changes (Plan 3)
- On-demand generation via API endpoint (deferred to Plan 3 when the frontend triggers it)
- Photo-library plugin source modifications (we read its L1 events, not its internals)
- Adding `memory_db_path` to the real `UnifiedMemoryStore` — Plan 1 deferred this; we revisit if a job needs it
- Hard `UnifiedMemoryStore.media_source_registry` attribute — Plan 2 wires registration through the scheduler contributor's setup; Plan 3 (or a later cleanup) can promote it to a first-class facade attribute

## File structure (created or modified)

**Created:**
- `backend/src/magi/timeline/narrative/__init__.py`
- `backend/src/magi/timeline/narrative/output_schema.py` — `DiaryNarrativeOutput` Pydantic-like dataclass
- `backend/src/magi/timeline/narrative/prompts.py` — system + user prompt builders
- `backend/src/magi/timeline/narrative/llm_client.py` — `DiaryNarrativeLLMClient` reusing `L2LLMJsonClientMixin`
- `backend/src/magi/timeline/narrative/orchestrator.py` — `DiaryNarrativeOrchestrator`
- `backend/src/magi/timeline/narrative/scheduler_contrib.py` — diary scheduler registration
- `backend/src/magi/timeline/standout/__init__.py`
- `backend/src/magi/timeline/standout/scoring.py` — pure heuristic scoring functions
- `backend/src/magi/timeline/standout/scheduler_contrib.py` — standout rescoring job
- `backend/src/magi/timeline/mood/__init__.py`
- `backend/src/magi/timeline/mood/algorithm.py` — algorithm C
- `backend/src/magi/timeline/mood/scheduler_contrib.py` — mood aggregate scheduler
- `backend/src/magi/media/adapters/__init__.py`
- `backend/src/magi/media/adapters/photo_library.py` — L1-event-backed MediaSource
- `backend/src/magi/media/scheduler_contrib.py` — `representative_asset_ref` populate job
- Tests under `backend/tests/timeline/narrative/`, `backend/tests/timeline/standout/`, `backend/tests/timeline/mood/`, `backend/tests/media/adapters/`

**Modified:**
- `backend/src/magi/config/models.py` — add `TIMELINE_DIARY_NARRATIVE` to `LLMScenario` enum
- `backend/src/magi/llm/scenario_pool.py` — add fallback mapping (`TIMELINE_DIARY_NARRATIVE` → `CORE`)
- `backend/src/magi/scheduler/contracts.py` — add 4 new `ScheduledTargetType` values
- `backend/src/magi/bootstrap/runtime_worker_builder.py` (or the relevant stateful-services module) — instantiate `MediaSourceRegistry` and register `PhotoLibraryMediaSource`
- `backend/tests/_shared/memory_schema.py` — add helper for L1 events DB (if needed for adapter tests)

---

## Task 1: Register `TIMELINE_DIARY_NARRATIVE` LLM scenario

**Files:**
- Modify: `backend/src/magi/config/models.py`
- Modify: `backend/src/magi/llm/scenario_pool.py`
- Test: `backend/tests/llm/test_scenario_pool_timeline_diary.py` (new)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/llm/__init__.py` if missing (empty file).

Create `backend/tests/llm/test_scenario_pool_timeline_diary.py`:

```python
"""Tests for TIMELINE_DIARY_NARRATIVE scenario registration."""

from __future__ import annotations

import pytest

from magi.config.models import LLMScenario


def test_timeline_diary_narrative_scenario_value_exists():
    assert LLMScenario.TIMELINE_DIARY_NARRATIVE.value == "timeline_diary_narrative"


def test_timeline_diary_narrative_falls_back_to_core():
    from magi.llm.scenario_pool import _FALLBACK_SCENARIOS

    fallback = _FALLBACK_SCENARIOS.get(LLMScenario.TIMELINE_DIARY_NARRATIVE)
    assert fallback == LLMScenario.CORE, (
        "TIMELINE_DIARY_NARRATIVE must fall back to CORE so existing model configs work"
    )
```

- [ ] **Step 2: Run, expect failure**

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest tests/llm/test_scenario_pool_timeline_diary.py -v
```

Expected: `AttributeError: TIMELINE_DIARY_NARRATIVE` or similar.

- [ ] **Step 3: Add enum value**

In `backend/src/magi/config/models.py`, locate `class LLMScenario(str, Enum):` (around line 229). Add at the end:

```python
    TIMELINE_DIARY_NARRATIVE = "timeline_diary_narrative"
```

- [ ] **Step 4: Add fallback mapping**

In `backend/src/magi/llm/scenario_pool.py`, find the existing `_FALLBACK_SCENARIOS` dict (or whatever the existing fallback constant is named). If the survey notes `MEMORY_SUMMARIZER → CORE` exists, follow the same pattern. Add:

```python
    LLMScenario.TIMELINE_DIARY_NARRATIVE: LLMScenario.CORE,
```

If the fallback dict is named differently or structured as code (a function), follow the existing structure. The intent: when no explicit model is configured for `TIMELINE_DIARY_NARRATIVE`, the pool resolves to whatever `CORE` resolves to.

- [ ] **Step 5: Run, expect pass**

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest tests/llm/test_scenario_pool_timeline_diary.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
cd /Users/asuka/code/magi && git add backend/src/magi/config/models.py backend/src/magi/llm/scenario_pool.py backend/tests/llm/ && git commit -m "feat(llm): register timeline.diary_narrative scenario with CORE fallback"
```

---

## Task 2: Diary narrative output schema + prompt builders

**Files:**
- Create: `backend/src/magi/timeline/narrative/__init__.py`
- Create: `backend/src/magi/timeline/narrative/output_schema.py`
- Create: `backend/src/magi/timeline/narrative/prompts.py`
- Test: `backend/tests/timeline/__init__.py`
- Test: `backend/tests/timeline/narrative/__init__.py`
- Test: `backend/tests/timeline/narrative/test_output_schema.py`
- Test: `backend/tests/timeline/narrative/test_prompts.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/timeline/__init__.py` and `backend/tests/timeline/narrative/__init__.py` (empty).

Create `backend/tests/timeline/narrative/test_output_schema.py`:

```python
"""Tests for the diary narrative LLM output schema."""

from __future__ import annotations

import pytest


def test_diary_narrative_output_from_valid_raw():
    from magi.timeline.narrative.output_schema import DiaryNarrativeOutput

    raw = {
        "essence_prose": "周日。你大部分时间在 localhost 之间游走。",
        "narrative_style": "diary_2p",
        "slices": [
            {
                "episode_id": "ep-a",
                "slice_narrative": "下午你读了 timeline-domain 的架构文档。",
                "slice_sensory_detail": "窗外光线很柔。",
            },
            {
                "episode_id": "ep-b",
                "slice_narrative": "深夜又一次打开 GitHub。",
                "slice_sensory_detail": None,
            },
        ],
    }
    out = DiaryNarrativeOutput.from_raw(raw)
    assert out.essence_prose.startswith("周日")
    assert out.narrative_style == "diary_2p"
    assert len(out.slices) == 2
    assert out.slices[0].episode_id == "ep-a"
    assert out.slices[0].slice_sensory_detail == "窗外光线很柔。"
    assert out.slices[1].slice_sensory_detail is None


def test_diary_narrative_output_from_empty_raw():
    from magi.timeline.narrative.output_schema import DiaryNarrativeOutput

    out = DiaryNarrativeOutput.from_raw({})
    assert out.essence_prose == ""
    assert out.narrative_style == "default"
    assert out.slices == []


def test_diary_narrative_output_skips_malformed_slices():
    from magi.timeline.narrative.output_schema import DiaryNarrativeOutput

    raw = {
        "essence_prose": "x",
        "slices": [
            {"episode_id": "ep-a", "slice_narrative": "ok"},
            {"slice_narrative": "missing episode_id"},  # dropped
            "not a dict",  # dropped
            {"episode_id": "  ", "slice_narrative": "blank id"},  # dropped
        ],
    }
    out = DiaryNarrativeOutput.from_raw(raw)
    assert len(out.slices) == 1
    assert out.slices[0].episode_id == "ep-a"
```

Create `backend/tests/timeline/narrative/test_prompts.py`:

```python
"""Tests for diary narrative prompt builders."""

from __future__ import annotations


def test_system_prompt_includes_forbidden_patterns():
    from magi.timeline.narrative.prompts import DIARY_NARRATIVE_SYSTEM_PROMPT

    assert "第二人称" in DIARY_NARRATIVE_SYSTEM_PROMPT
    # Forbidden patterns from spec §Voice and writing
    for forbidden in ("internal id", "markdown", "metric"):
        assert forbidden.lower() in DIARY_NARRATIVE_SYSTEM_PROMPT.lower(), (
            f"system prompt should mention forbidden: {forbidden}"
        )


def test_user_prompt_contains_all_episode_ids():
    from magi.timeline.narrative.prompts import build_diary_narrative_user_prompt

    episodes = [
        {"episode_id": "ep-1", "time_start": 100.0, "time_end": 200.0, "label": "morning"},
        {"episode_id": "ep-2", "time_start": 300.0, "time_end": 400.0, "label": "afternoon"},
    ]
    prompt = build_diary_narrative_user_prompt(
        scale="day",
        period_start=0.0,
        period_end=86400.0,
        episodes=episodes,
        place_hints=["家"],
    )
    assert "ep-1" in prompt
    assert "ep-2" in prompt
    assert "morning" in prompt
    assert "afternoon" in prompt
    assert "家" in prompt
    assert "day" in prompt.lower()


def test_user_prompt_handles_empty_episodes():
    from magi.timeline.narrative.prompts import build_diary_narrative_user_prompt

    prompt = build_diary_narrative_user_prompt(
        scale="day",
        period_start=0.0,
        period_end=86400.0,
        episodes=[],
        place_hints=[],
    )
    # Should still produce something — orchestrator decides whether to call LLM at all
    assert prompt
    assert "day" in prompt.lower()
```

- [ ] **Step 2: Run, expect failure (module missing)**

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest tests/timeline/narrative/ -v
```

Expected: `ModuleNotFoundError: No module named 'magi.timeline.narrative'`.

- [ ] **Step 3: Create the output schema module**

Create `backend/src/magi/timeline/narrative/__init__.py`:

```python
"""Diary narrative generation pipeline."""
```

Create `backend/src/magi/timeline/narrative/output_schema.py`:

```python
"""Diary narrative LLM output schema.

The LLM returns a JSON object with a period-level essence and a list of
per-episode slices. This module parses raw dicts into typed dataclasses
and silently drops malformed entries (callers receive partial data
rather than crashing on a single bad slice).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(slots=True)
class DiarySliceNarrative:
    """One generated narrative for a single L2 episode."""

    episode_id: str
    slice_narrative: str = ""
    slice_sensory_detail: str | None = None


@dataclass(slots=True)
class DiaryNarrativeOutput:
    """The full diary narrative output for a period."""

    essence_prose: str = ""
    narrative_style: str = "default"
    slices: list[DiarySliceNarrative] = field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any]) -> "DiaryNarrativeOutput":
        if not isinstance(raw, Mapping):
            return cls()

        essence = str(raw.get("essence_prose") or "").strip()
        style = str(raw.get("narrative_style") or "default").strip() or "default"

        slices_raw = raw.get("slices") or []
        if not isinstance(slices_raw, list):
            slices_raw = []

        slices: list[DiarySliceNarrative] = []
        for item in slices_raw:
            if not isinstance(item, Mapping):
                continue
            episode_id = str(item.get("episode_id") or "").strip()
            if not episode_id:
                continue
            narrative = str(item.get("slice_narrative") or "").strip()
            sensory_raw = item.get("slice_sensory_detail")
            sensory = (
                str(sensory_raw).strip() or None
                if isinstance(sensory_raw, str) and sensory_raw.strip()
                else None
            )
            slices.append(
                DiarySliceNarrative(
                    episode_id=episode_id,
                    slice_narrative=narrative,
                    slice_sensory_detail=sensory,
                )
            )
        return cls(essence_prose=essence, narrative_style=style or "default", slices=slices)
```

- [ ] **Step 4: Create the prompts module**

Create `backend/src/magi/timeline/narrative/prompts.py`:

```python
"""Diary narrative prompt builders.

The system prompt encodes the voice contract (2nd-person, no internal IDs,
no markdown headers, no numeric metrics, no source-name repetition). The
user prompt assembles concrete period evidence — episodes, time bounds,
optional place hints — for a single LLM call.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable


DIARY_NARRATIVE_SYSTEM_PROMPT = """你是一名沉浸式日记的撰稿者。给定一个时段的活动证据，
你要为整段时间生成一段第二人称（用"你"）的散文 essence，并为该时段内的每一个 episode
生成一句叙事 + 可选的一句感官细节。

要求：
- 使用第二人称（"你"），温柔有质感，不堆砌形容词
- essence 控制在 1-3 句话，约 30-80 个汉字
- 每个 slice 的 slice_narrative 控制在 1 句话
- slice_sensory_detail 是可选的"那时还没有发现"或"窗外正下雨"这种小细节，1 句话即可

禁止：
- 出现内部 id（任何形如 ep-xxx、uuid、hash 的字符串）
- 使用 markdown 标题（##、**、--- 等）
- 出现数字 metric（"专注度 62%"、"压力 0.4" 之类）
- 源名重复（不要写"Chrome 历史 / Chrome 历史"这种）

返回严格 JSON：
{
  "essence_prose": "...",
  "narrative_style": "diary_2p",
  "slices": [
    {"episode_id": "ep-xxx", "slice_narrative": "...", "slice_sensory_detail": "..."}
  ]
}

JSON 里允许出现 episode_id（这是机器读取的契约，不是给用户看的文本）。
"""


def build_diary_narrative_user_prompt(
    *,
    scale: str,
    period_start: float,
    period_end: float,
    episodes: Iterable[dict],
    place_hints: Iterable[str] = (),
) -> str:
    """Build the user prompt that gives the LLM concrete period evidence."""
    start_label = datetime.fromtimestamp(period_start, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    end_label = datetime.fromtimestamp(period_end, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines: list[str] = []
    lines.append(f"周期尺度：{scale}（{start_label} ~ {end_label}）")

    places = [p for p in place_hints if p and str(p).strip()]
    if places:
        lines.append("主要地点：" + "、".join(places))

    lines.append("")
    lines.append("Episodes（按时间顺序）：")
    any_episode = False
    for ep in episodes:
        any_episode = True
        ep_id = str(ep.get("episode_id") or "").strip()
        ts = float(ep.get("time_start") or 0.0)
        te = float(ep.get("time_end") or ts)
        t_start = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M")
        t_end = datetime.fromtimestamp(te, tz=timezone.utc).strftime("%H:%M")
        label = str(ep.get("label") or ep.get("user_label") or "").strip()
        topics = ep.get("primary_topic_keys") or []
        entities = ep.get("primary_entity_ids") or []
        bits = [f"id={ep_id}", f"{t_start}–{t_end}"]
        if label:
            bits.append(f"label={label!r}")
        if topics:
            bits.append("topics=" + ",".join(str(t) for t in topics[:5]))
        if entities:
            bits.append("entities=" + ",".join(str(e) for e in entities[:5]))
        lines.append("- " + " · ".join(bits))

    if not any_episode:
        lines.append("- （这个时段没有 episode；只给 essence_prose 即可，slices 返回空数组）")

    lines.append("")
    lines.append("请按系统提示中的 JSON schema 返回结果。")
    return "\n".join(lines)
```

- [ ] **Step 5: Run, expect pass**

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest tests/timeline/narrative/ -v
```

Expected: 6 passed (3 schema + 3 prompts).

- [ ] **Step 6: Commit**

```bash
cd /Users/asuka/code/magi && git add backend/src/magi/timeline/narrative/__init__.py backend/src/magi/timeline/narrative/output_schema.py backend/src/magi/timeline/narrative/prompts.py backend/tests/timeline/ && git commit -m "feat(timeline/narrative): diary output schema + prompt builders"
```

---

## Task 3: Diary narrative LLM client

**Files:**
- Create: `backend/src/magi/timeline/narrative/llm_client.py`
- Test: `backend/tests/timeline/narrative/test_llm_client.py`

The client reuses `L2LLMJsonClientMixin` for JSON-mode + retry handling. Plan 2 calls it once per period; the mixin handles rate-limit backoff automatically.

- [ ] **Step 1: Write failing test (with a stubbed pool)**

Create `backend/tests/timeline/narrative/test_llm_client.py`:

```python
"""Tests for DiaryNarrativeLLMClient (LLM call stubbed)."""

from __future__ import annotations

import json

import pytest


class _StubResponse:
    def __init__(self, content: str) -> None:
        self.content = content
        self.usage = None


class _StubBridge:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.calls: list[dict] = []

    async def chat_response(self, **kwargs):
        self.calls.append(kwargs)
        return _StubResponse(json.dumps(self._payload))


class _StubAdapter:
    provider_name = "stub"
    model_name = "stub-model"


class _StubPool:
    def __init__(self, payload: dict) -> None:
        self._adapter = _StubAdapter()
        self._bridge = _StubBridge(payload)

    def get(self, scenario):
        return self._adapter

    def get_selection(self, scenario):
        return None

    @property
    def bridge(self):
        return self._bridge


@pytest.mark.asyncio
async def test_generate_returns_parsed_output(monkeypatch):
    from magi.timeline.narrative.llm_client import DiaryNarrativeLLMClient
    from magi.llm import LLMProviderBridge

    payload = {
        "essence_prose": "周日的样子。",
        "narrative_style": "diary_2p",
        "slices": [{"episode_id": "ep-1", "slice_narrative": "你读了文档。"}],
    }
    pool = _StubPool(payload)
    monkeypatch.setattr(LLMProviderBridge, "__init__", lambda self, adapter: setattr(self, "_adapter", adapter) or None)
    monkeypatch.setattr(LLMProviderBridge, "chat_response", pool.bridge.chat_response)

    client = DiaryNarrativeLLMClient(scenario_llm_pool=pool)
    out = await client.generate(
        scale="day", period_start=0.0, period_end=86400.0,
        episodes=[{"episode_id": "ep-1", "time_start": 100.0, "time_end": 200.0, "label": "x"}],
        place_hints=[],
    )

    assert out.essence_prose == "周日的样子。"
    assert out.narrative_style == "diary_2p"
    assert len(out.slices) == 1
    assert out.slices[0].episode_id == "ep-1"
    # The pool was called once with json_mode=True
    assert len(pool.bridge.calls) == 1
    assert pool.bridge.calls[0].get("json_mode") is True


@pytest.mark.asyncio
async def test_generate_returns_empty_on_no_adapter():
    from magi.timeline.narrative.llm_client import DiaryNarrativeLLMClient
    from magi.timeline.narrative.output_schema import DiaryNarrativeOutput

    class _NoPool:
        def get(self, scenario):
            return None

        def get_selection(self, scenario):
            return None

    client = DiaryNarrativeLLMClient(scenario_llm_pool=_NoPool())
    out = await client.generate(
        scale="day", period_start=0.0, period_end=1.0, episodes=[], place_hints=[],
    )
    assert isinstance(out, DiaryNarrativeOutput)
    assert out.essence_prose == ""
    assert out.slices == []
```

- [ ] **Step 2: Run, expect failure**

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest tests/timeline/narrative/test_llm_client.py -v
```

- [ ] **Step 3: Create the LLM client**

Create `backend/src/magi/timeline/narrative/llm_client.py`:

```python
"""DiaryNarrativeLLMClient — wraps L2LLMJsonClientMixin for timeline diary generation."""

from __future__ import annotations

from typing import Iterable, Optional

from ...config.models import LLMScenario
from ...llm import ScenarioLLMPool
from ...memory.l2.llm_json_client import L2LLMJsonClientMixin
from .output_schema import DiaryNarrativeOutput
from .prompts import DIARY_NARRATIVE_SYSTEM_PROMPT, build_diary_narrative_user_prompt


class DiaryNarrativeLLMClient(L2LLMJsonClientMixin):
    """Single-shot diary generator.

    Uses the existing L2LLMJsonClientMixin._generate_json helper, which:
      - sends a JSON-mode chat completion via ScenarioLLMPool
      - retries on rate-limit errors (1s/2s/4s backoff)
      - returns {} on adapter unavailability or invalid JSON

    For Plan 2 we don't add a new retry layer — the mixin's behavior is sufficient.
    """

    def __init__(self, *, scenario_llm_pool: Optional[ScenarioLLMPool]) -> None:
        self._scenario_llm_pool = scenario_llm_pool

    async def generate(
        self,
        *,
        scale: str,
        period_start: float,
        period_end: float,
        episodes: Iterable[dict],
        place_hints: Iterable[str] = (),
    ) -> DiaryNarrativeOutput:
        """Generate a diary narrative for the given period.

        Returns an empty DiaryNarrativeOutput on adapter unavailability or
        invalid JSON (callers should treat this as "no generation possible
        right now" and either retry later or fall back to existing data).
        """
        prompt = build_diary_narrative_user_prompt(
            scale=scale,
            period_start=period_start,
            period_end=period_end,
            episodes=list(episodes),
            place_hints=list(place_hints),
        )
        raw = await self._generate_json(
            system_prompt=DIARY_NARRATIVE_SYSTEM_PROMPT,
            prompt=prompt,
            request_kind="timeline_diary_narrative",
            scenario=LLMScenario.TIMELINE_DIARY_NARRATIVE,
        )
        return DiaryNarrativeOutput.from_raw(raw)
```

- [ ] **Step 4: Run, expect pass**

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest tests/timeline/narrative/test_llm_client.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/asuka/code/magi && git add backend/src/magi/timeline/narrative/llm_client.py backend/tests/timeline/narrative/test_llm_client.py && git commit -m "feat(timeline/narrative): DiaryNarrativeLLMClient reusing L2 JSON mixin"
```

---

## Task 4: Diary narrative orchestrator

**Files:**
- Create: `backend/src/magi/timeline/narrative/orchestrator.py`
- Test: `backend/tests/timeline/narrative/test_orchestrator.py`

The orchestrator gathers episodes via `L2CognitionStore.list_episodes` (existing method that filters by `time_start`/`time_end`), calls the LLM client, then writes `essence_prose` to L3 via `upsert_candidate` with overrides, and writes `slice_narrative` + `slice_sensory_detail` to each constituent L2 episode via `update_episode`.

- [ ] **Step 1: Write failing tests**

Create `backend/tests/timeline/narrative/test_orchestrator.py`:

```python
"""Tests for DiaryNarrativeOrchestrator (end-to-end with stubbed LLM)."""

from __future__ import annotations

import pytest

from magi.memory.l2.store import L2CognitionStore
from magi.memory.l3.summary_store import L3SummaryStore
from magi.timeline.narrative.orchestrator import DiaryNarrativeOrchestrator
from magi.timeline.narrative.output_schema import DiaryNarrativeOutput, DiarySliceNarrative


class _StubClient:
    def __init__(self, output: DiaryNarrativeOutput) -> None:
        self._output = output
        self.calls: list[dict] = []

    async def generate(self, **kwargs) -> DiaryNarrativeOutput:
        self.calls.append(kwargs)
        return self._output


@pytest.mark.asyncio
async def test_generate_for_window_writes_essence_to_l3_and_narratives_to_l2(
    l2_store_with_schema: L2CognitionStore,
    tmp_path,
):
    # Set up an L3 store against the same tmp DB
    l3_store = L3SummaryStore(db_path=l2_store_with_schema.db_path)
    await l3_store.initialize()

    # Seed two episodes in the window
    await l2_store_with_schema.create_episode(
        episode_id="ep-a", time_start=100.0, time_end=200.0,
    )
    await l2_store_with_schema.create_episode(
        episode_id="ep-b", time_start=300.0, time_end=400.0,
    )

    stub_output = DiaryNarrativeOutput(
        essence_prose="这是一段周日的样子。",
        narrative_style="diary_2p",
        slices=[
            DiarySliceNarrative(episode_id="ep-a", slice_narrative="下午你读了文档。", slice_sensory_detail="光线柔软。"),
            DiarySliceNarrative(episode_id="ep-b", slice_narrative="深夜还亮着屏。"),
        ],
    )
    client = _StubClient(stub_output)

    orchestrator = DiaryNarrativeOrchestrator(
        l2_store=l2_store_with_schema, l3_store=l3_store, llm_client=client,
    )

    result = await orchestrator.generate_for_window(
        scale="day", period_start=0.0, period_end=500.0, insight_key="diary-2026-05-17",
    )

    assert result.episode_count == 2
    assert result.essence_prose_chars > 0

    # L2 episodes received their narratives
    ep_a = await l2_store_with_schema.get_episode(episode_id="ep-a")
    assert ep_a["slice_narrative"] == "下午你读了文档。"
    assert ep_a["slice_sensory_detail"] == "光线柔软。"
    ep_b = await l2_store_with_schema.get_episode(episode_id="ep-b")
    assert ep_b["slice_narrative"] == "深夜还亮着屏。"
    assert ep_b["slice_sensory_detail"] == ""

    # L3 received the essence prose
    found = await l3_store._find_summary_by_insight_key(insight_key="diary-2026-05-17")
    assert found is not None
    assert found["narrative_style"] == "diary_2p"
    assert found["essence_prose"] == "这是一段周日的样子。"


@pytest.mark.asyncio
async def test_generate_for_window_skips_when_no_episodes(
    l2_store_with_schema: L2CognitionStore,
    tmp_path,
):
    l3_store = L3SummaryStore(db_path=l2_store_with_schema.db_path)
    await l3_store.initialize()

    client = _StubClient(DiaryNarrativeOutput(essence_prose="", slices=[]))
    orchestrator = DiaryNarrativeOrchestrator(
        l2_store=l2_store_with_schema, l3_store=l3_store, llm_client=client,
    )

    result = await orchestrator.generate_for_window(
        scale="day", period_start=0.0, period_end=500.0, insight_key="diary-empty",
    )

    assert result.episode_count == 0
    assert result.essence_prose_chars == 0
    # LLM was NOT called
    assert client.calls == []
    # No L3 summary was created
    found = await l3_store._find_summary_by_insight_key(insight_key="diary-empty")
    assert found is None


@pytest.mark.asyncio
async def test_generate_for_window_handles_empty_llm_output(
    l2_store_with_schema: L2CognitionStore,
    tmp_path,
):
    """If the LLM returns empty content (e.g. rate-limited), the orchestrator should be a no-op."""
    l3_store = L3SummaryStore(db_path=l2_store_with_schema.db_path)
    await l3_store.initialize()

    await l2_store_with_schema.create_episode(
        episode_id="ep-x", time_start=100.0, time_end=200.0,
    )

    client = _StubClient(DiaryNarrativeOutput())  # all defaults — empty
    orchestrator = DiaryNarrativeOrchestrator(
        l2_store=l2_store_with_schema, l3_store=l3_store, llm_client=client,
    )

    result = await orchestrator.generate_for_window(
        scale="day", period_start=0.0, period_end=500.0, insight_key="diary-empty-llm",
    )

    assert result.essence_prose_chars == 0
    # Episode narrative was NOT written (empty output)
    ep = await l2_store_with_schema.get_episode(episode_id="ep-x")
    assert ep["slice_narrative"] == ""
    # No L3 summary
    found = await l3_store._find_summary_by_insight_key(insight_key="diary-empty-llm")
    assert found is None
```

- [ ] **Step 2: Run, expect failure**

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest tests/timeline/narrative/test_orchestrator.py -v
```

- [ ] **Step 3: Create the orchestrator**

Create `backend/src/magi/timeline/narrative/orchestrator.py`:

```python
"""DiaryNarrativeOrchestrator — gather period evidence, call LLM, persist results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from ...core.logger import get_logger
from ...memory.l3.models import L3Candidate
from .output_schema import DiaryNarrativeOutput

logger = get_logger("magi.timeline.narrative.orchestrator")


class _L2EpisodeStoreProtocol(Protocol):
    async def list_episodes(self, **kwargs) -> list[dict]: ...
    async def update_episode(self, *, episode_id: str, **fields) -> bool: ...
    async def get_episode(self, *, episode_id: str) -> dict | None: ...


class _L3SummaryStoreProtocol(Protocol):
    async def upsert_candidate(
        self, *, candidate: L3Candidate, summary_overrides: dict | None = None,
    ) -> dict: ...


class _DiaryLLMClientProtocol(Protocol):
    async def generate(
        self, *, scale: str, period_start: float, period_end: float,
        episodes: Iterable[dict], place_hints: Iterable[str] = (),
    ) -> DiaryNarrativeOutput: ...


@dataclass(slots=True)
class OrchestratorResult:
    """Summary of what was generated for a single orchestrator run."""

    period_start: float
    period_end: float
    scale: str
    episode_count: int
    essence_prose_chars: int
    slices_written: int


class DiaryNarrativeOrchestrator:
    """End-to-end diary generation for a single period window.

    Flow:
      1. List active L2 episodes whose time_start falls in [period_start, period_end).
      2. If none, return without calling LLM.
      3. Call DiaryNarrativeLLMClient.generate(...).
      4. If essence is non-empty, upsert an L3 summary via upsert_candidate(insight_key=...).
      5. For each slice in the output, update the matching L2 episode's narrative fields.

    The orchestrator does NOT compute mood, score standouts, or pick representative
    photos — those are separate jobs in the same plan.
    """

    def __init__(
        self,
        *,
        l2_store: _L2EpisodeStoreProtocol,
        l3_store: _L3SummaryStoreProtocol,
        llm_client: _DiaryLLMClientProtocol,
    ) -> None:
        self._l2_store = l2_store
        self._l3_store = l3_store
        self._llm_client = llm_client

    async def generate_for_window(
        self,
        *,
        scale: str,
        period_start: float,
        period_end: float,
        insight_key: str,
        place_hints: Iterable[str] = (),
    ) -> OrchestratorResult:
        episodes = await self._l2_store.list_episodes(
            statuses=["active"],
            time_start=period_start,
            time_end=period_end,
            limit=200,
        )

        if not episodes:
            logger.info(
                "Diary generation skipped: no episodes in window",
                scale=scale,
                period_start=period_start,
                period_end=period_end,
            )
            return OrchestratorResult(
                period_start=period_start,
                period_end=period_end,
                scale=scale,
                episode_count=0,
                essence_prose_chars=0,
                slices_written=0,
            )

        output = await self._llm_client.generate(
            scale=scale,
            period_start=period_start,
            period_end=period_end,
            episodes=episodes,
            place_hints=place_hints,
        )

        # If the LLM call failed or returned empty content, be a no-op.
        if not output.essence_prose and not output.slices:
            logger.warning(
                "Diary generation produced empty output (LLM unavailable or invalid JSON)",
                scale=scale, period_start=period_start, period_end=period_end,
                episode_count=len(episodes),
            )
            return OrchestratorResult(
                period_start=period_start, period_end=period_end, scale=scale,
                episode_count=len(episodes), essence_prose_chars=0, slices_written=0,
            )

        # Write essence to L3 (only if non-empty)
        if output.essence_prose:
            candidate = L3Candidate(
                summary_type="temporal",
                summary_category=scale,
                content=output.essence_prose,
                source_event_ids=[],
                insight_key=insight_key,
            )
            await self._l3_store.upsert_candidate(
                candidate=candidate,
                summary_overrides={
                    "narrative_style": output.narrative_style or "diary_2p",
                    "essence_prose": output.essence_prose,
                    "period_start": period_start,
                    "period_end": period_end,
                },
            )

        # Write each slice to its episode
        slices_written = 0
        valid_episode_ids = {ep["episode_id"] for ep in episodes}
        for slice_ in output.slices:
            if slice_.episode_id not in valid_episode_ids:
                logger.warning(
                    "Diary slice references unknown episode_id; skipping",
                    episode_id=slice_.episode_id,
                )
                continue
            if not slice_.slice_narrative:
                continue
            await self._l2_store.update_episode(
                episode_id=slice_.episode_id,
                slice_narrative=slice_.slice_narrative,
                slice_sensory_detail=slice_.slice_sensory_detail or "",
            )
            slices_written += 1

        return OrchestratorResult(
            period_start=period_start,
            period_end=period_end,
            scale=scale,
            episode_count=len(episodes),
            essence_prose_chars=len(output.essence_prose),
            slices_written=slices_written,
        )
```

- [ ] **Step 4: Run, expect pass**

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest tests/timeline/narrative/test_orchestrator.py -v
```

Expected: 3 passed.

> **Note on fixture sharing:** the test file uses `l2_store_with_schema` from `tests/memory/l2/conftest.py`. To make it available under `tests/timeline/narrative/`, add a one-line conftest at `backend/tests/timeline/__init__.py` or import the fixture directly. The cleanest fix: pytest's conftest discovery is directory-tree-based, so `tests/timeline/conftest.py` (new, empty file) won't expose L2's fixture. Two options: (a) add `tests/timeline/narrative/conftest.py` that re-exports the fixture, (b) move the fixture to `tests/_shared/`. Use option (a) for surgical scope: 

Create `backend/tests/timeline/conftest.py`:

```python
"""Re-export shared fixtures into the timeline test tree."""

from __future__ import annotations

import pytest_asyncio

from _shared.memory_schema import apply_memory_shared_schema


@pytest_asyncio.fixture
async def l2_store_with_schema(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    db_path = str(tmp_path / "memory.db")
    await apply_memory_shared_schema(db_path)
    store = L2CognitionStore(db_path=db_path)
    await store.initialize()
    return store
```

> The L3 store in the test uses the SAME db path so essence_prose persists correctly.

- [ ] **Step 5: Commit**

```bash
cd /Users/asuka/code/magi && git add backend/src/magi/timeline/narrative/orchestrator.py backend/tests/timeline/narrative/test_orchestrator.py backend/tests/timeline/conftest.py && git commit -m "feat(timeline/narrative): DiaryNarrativeOrchestrator writing essence + slice narratives"
```

---

## Task 5: Diary narrative scheduler contributor

**Files:**
- Modify: `backend/src/magi/scheduler/contracts.py` — add `TIMELINE_DIARY_NARRATIVE` to `ScheduledTargetType`
- Create: `backend/src/magi/timeline/narrative/scheduler_contrib.py`
- Test: `backend/tests/timeline/narrative/test_scheduler_contrib.py`

The contributor registers an end-of-day handler that finds yesterday's window (UTC for now; locality is a Plan 3 concern), constructs an `insight_key` like `diary-day-2026-05-17`, and runs the orchestrator.

- [ ] **Step 1: Add scheduler target type**

In `backend/src/magi/scheduler/contracts.py`, locate `class ScheduledTargetType(str, Enum):`. Append:

```python
    TIMELINE_DIARY_NARRATIVE = "timeline_diary_narrative"
    TIMELINE_STANDOUT_RESCORE = "timeline_standout_rescore"
    TIMELINE_MOOD_AGGREGATE = "timeline_mood_aggregate"
    TIMELINE_REPRESENTATIVE_ASSET = "timeline_representative_asset"
```

(All four go in here at once to avoid touching contracts.py four times.)

- [ ] **Step 2: Write failing test**

Create `backend/tests/timeline/narrative/test_scheduler_contrib.py`:

```python
"""Tests for DiaryNarrativeSchedulerContrib."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from magi.scheduler.contracts import (
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
)


@pytest.mark.asyncio
async def test_scheduler_contrib_registers_handler():
    from magi.timeline.narrative.scheduler_contrib import DiaryNarrativeSchedulerContrib

    contrib = DiaryNarrativeSchedulerContrib(orchestrator=AsyncMock())
    scheduler = AsyncMock()
    scheduler.register_handler = AsyncMock()
    await contrib.register_schedules(scheduler)

    scheduler.register_handler.assert_awaited_once()
    args, _ = scheduler.register_handler.call_args
    assert args[0] == ScheduledTargetType.TIMELINE_DIARY_NARRATIVE


@pytest.mark.asyncio
async def test_handler_calls_orchestrator_for_yesterday_day_window():
    from magi.timeline.narrative.scheduler_contrib import DiaryNarrativeSchedulerContrib

    orchestrator = AsyncMock()
    orchestrator.generate_for_window = AsyncMock(return_value=None)

    contrib = DiaryNarrativeSchedulerContrib(orchestrator=orchestrator)
    context = ScheduledExecutionContext(
        schedule=None, target_state=None, triggered_at=1715990400.0 + 86400 * 3, manual=False,
    )

    result = await contrib._handle_diary_narrative(context)

    assert isinstance(result, ScheduledExecutionResult)
    assert result.success is True
    # Orchestrator called for yesterday (UTC day before triggered_at)
    orchestrator.generate_for_window.assert_awaited_once()
    call_kwargs = orchestrator.generate_for_window.call_args.kwargs
    assert call_kwargs["scale"] == "day"
    assert call_kwargs["insight_key"].startswith("diary-day-")
```

> Note: `ScheduledExecutionContext` instantiation here is illustrative — adjust to the actual dataclass signature from `backend/src/magi/scheduler/contracts.py`. If `schedule` and `target_state` are required typed values rather than allowed to be None, construct minimal stubs or use `unittest.mock.MagicMock()`.

- [ ] **Step 3: Run, expect failure**

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest tests/timeline/narrative/test_scheduler_contrib.py -v
```

- [ ] **Step 4: Create the scheduler contributor**

Create `backend/src/magi/timeline/narrative/scheduler_contrib.py`:

```python
"""Scheduler integration for diary narrative generation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol

from ...core.logger import get_logger
from ...scheduler.contracts import (
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
)

logger = get_logger("magi.timeline.narrative.scheduler")


class _OrchestratorProtocol(Protocol):
    async def generate_for_window(
        self, *, scale: str, period_start: float, period_end: float, insight_key: str,
        place_hints=...,
    ) -> object: ...


class _SchedulerProtocol(Protocol):
    async def register_handler(self, target_type, handler) -> None: ...


class DiaryNarrativeSchedulerContrib:
    """Register an end-of-day diary narrative job.

    The handler computes "yesterday's day window" relative to the trigger time
    (UTC for now; localization is a Plan 3 concern), then dispatches to the
    orchestrator with insight_key = "diary-day-YYYY-MM-DD".

    Week/month variants can be added by extending this contributor with
    additional target_type registrations — kept day-only for Plan 2 scope.
    """

    def __init__(self, *, orchestrator: _OrchestratorProtocol) -> None:
        self._orchestrator = orchestrator

    async def register_schedules(self, scheduler: _SchedulerProtocol) -> None:
        await scheduler.register_handler(
            ScheduledTargetType.TIMELINE_DIARY_NARRATIVE,
            self._handle_diary_narrative,
        )

    async def unregister_schedules(self, scheduler) -> None:
        unregister = getattr(scheduler, "unregister_handler", None)
        if unregister:
            await unregister(ScheduledTargetType.TIMELINE_DIARY_NARRATIVE)

    async def _handle_diary_narrative(
        self, context: ScheduledExecutionContext,
    ) -> ScheduledExecutionResult:
        triggered_at = float(getattr(context, "triggered_at", 0.0) or 0.0)
        if triggered_at <= 0:
            triggered_at = datetime.now(tz=timezone.utc).timestamp()

        triggered_dt = datetime.fromtimestamp(triggered_at, tz=timezone.utc)
        yesterday = triggered_dt.date() - timedelta(days=1)
        period_start_dt = datetime(yesterday.year, yesterday.month, yesterday.day, tzinfo=timezone.utc)
        period_end_dt = period_start_dt + timedelta(days=1)

        period_start = period_start_dt.timestamp()
        period_end = period_end_dt.timestamp()
        insight_key = f"diary-day-{yesterday.isoformat()}"

        try:
            result = await self._orchestrator.generate_for_window(
                scale="day",
                period_start=period_start,
                period_end=period_end,
                insight_key=insight_key,
                place_hints=[],
            )
        except Exception as exc:
            logger.warning("Diary narrative generation failed", error=str(exc), insight_key=insight_key)
            return ScheduledExecutionResult(
                success=False, message=f"diary narrative failed: {exc}", stats={},
            )

        stats = {
            "episode_count": getattr(result, "episode_count", 0),
            "essence_prose_chars": getattr(result, "essence_prose_chars", 0),
            "slices_written": getattr(result, "slices_written", 0),
        }
        return ScheduledExecutionResult(
            success=True,
            message=f"diary narrative generated for {yesterday.isoformat()}",
            stats=stats,
        )
```

- [ ] **Step 5: Run, expect pass**

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest tests/timeline/narrative/test_scheduler_contrib.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
cd /Users/asuka/code/magi && git add backend/src/magi/scheduler/contracts.py backend/src/magi/timeline/narrative/scheduler_contrib.py backend/tests/timeline/narrative/test_scheduler_contrib.py && git commit -m "feat(timeline/narrative): DiaryNarrativeSchedulerContrib end-of-day generation"
```

---

## Task 6: Standout scoring heuristic

**Files:**
- Create: `backend/src/magi/timeline/standout/__init__.py`
- Create: `backend/src/magi/timeline/standout/scoring.py`
- Test: `backend/tests/timeline/standout/__init__.py`
- Test: `backend/tests/timeline/standout/test_scoring.py`

A pure function (no I/O) that takes an episode dict + signals and returns `(magi_standout, standout_score, standout_reason)`. The scoring job (T7) wires it to the real store.

Initial signals (mirroring the spec's draft heuristic):
- Duration > 90 minutes: +0.35
- Has photos in window (from `MediaSourceRegistry.collect_assets`): +0.30
- State-shift markers (count > 0): +0.20
- First occurrence of an entity (entity_id not seen in any older episode): +0.30 each, capped at +0.45
- Score ≥ 0.50 → `magi_standout = True`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/timeline/standout/__init__.py` (empty).

Create `backend/tests/timeline/standout/test_scoring.py`:

```python
"""Tests for the standout scoring heuristic."""

from __future__ import annotations

import pytest


def test_short_episode_with_no_signals_scores_low():
    from magi.timeline.standout.scoring import compute_standout_score, StandoutSignals

    episode = {"time_start": 100.0, "time_end": 200.0, "primary_entity_ids": []}
    signals = StandoutSignals(has_photos=False, state_shift_count=0, first_seen_entities=[])

    score, reason, is_standout = compute_standout_score(episode=episode, signals=signals)
    assert score == pytest.approx(0.0)
    assert is_standout is False
    assert "no signals" in reason or reason == ""


def test_long_episode_with_photos_scores_higher():
    from magi.timeline.standout.scoring import compute_standout_score, StandoutSignals

    # Duration: 2 hours (> 90 min threshold)
    episode = {"time_start": 0.0, "time_end": 7200.0, "primary_entity_ids": []}
    signals = StandoutSignals(has_photos=True, state_shift_count=0, first_seen_entities=[])

    score, reason, is_standout = compute_standout_score(episode=episode, signals=signals)
    # 0.35 (duration) + 0.30 (photos) = 0.65
    assert score == pytest.approx(0.65)
    assert is_standout is True
    assert "duration" in reason
    assert "photos" in reason


def test_first_entity_appearance_caps_at_0_45():
    from magi.timeline.standout.scoring import compute_standout_score, StandoutSignals

    episode = {"time_start": 0.0, "time_end": 60.0, "primary_entity_ids": ["x", "y", "z"]}
    signals = StandoutSignals(
        has_photos=False,
        state_shift_count=0,
        first_seen_entities=["x", "y", "z"],  # 3 firsts * 0.30 = 0.90, but capped at 0.45
    )

    score, _, _ = compute_standout_score(episode=episode, signals=signals)
    assert score == pytest.approx(0.45)


def test_state_shift_signal_adds_0_20():
    from magi.timeline.standout.scoring import compute_standout_score, StandoutSignals

    episode = {"time_start": 0.0, "time_end": 60.0, "primary_entity_ids": []}
    signals = StandoutSignals(has_photos=False, state_shift_count=2, first_seen_entities=[])

    score, _, _ = compute_standout_score(episode=episode, signals=signals)
    assert score == pytest.approx(0.20)


def test_threshold_promotes_to_magi_standout_at_0_50():
    from magi.timeline.standout.scoring import compute_standout_score, StandoutSignals

    # Exactly 0.50 (duration + state_shift)
    episode = {"time_start": 0.0, "time_end": 7200.0}
    signals = StandoutSignals(has_photos=False, state_shift_count=1, first_seen_entities=[])

    score, _, is_standout = compute_standout_score(episode=episode, signals=signals)
    assert score == pytest.approx(0.55)  # 0.35 + 0.20
    assert is_standout is True


def test_reason_includes_all_contributing_signals_sorted():
    from magi.timeline.standout.scoring import compute_standout_score, StandoutSignals

    episode = {"time_start": 0.0, "time_end": 7200.0, "primary_entity_ids": ["x"]}
    signals = StandoutSignals(has_photos=True, state_shift_count=1, first_seen_entities=["x"])

    _, reason, _ = compute_standout_score(episode=episode, signals=signals)
    # Reason should be ;-delimited and include all signals
    parts = sorted(reason.split(";"))
    assert "duration" in parts[0] or any("duration" in p for p in parts)
    assert any("photos" in p for p in parts)
    assert any("first_entity" in p for p in parts)
    assert any("state_shift" in p for p in parts)
```

- [ ] **Step 2: Run, expect failure**

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest tests/timeline/standout/ -v
```

- [ ] **Step 3: Create the scoring module**

Create `backend/src/magi/timeline/standout/__init__.py`:

```python
"""Standout episode scoring for the timeline sidebar 值得回来的 list."""
```

Create `backend/src/magi/timeline/standout/scoring.py`:

```python
"""Heuristic scoring for magi_standout / standout_score / standout_reason.

The function is pure — no I/O. The caller (T7's scheduler job) gathers
the necessary signals from the L2 store + MediaSourceRegistry and passes
them in. Tuning weights in the future is a single-file change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


# Weights — tuning happens here.
WEIGHT_DURATION = 0.35
WEIGHT_PHOTOS = 0.30
WEIGHT_STATE_SHIFT = 0.20
WEIGHT_FIRST_ENTITY_EACH = 0.30
WEIGHT_FIRST_ENTITY_CAP = 0.45

DURATION_THRESHOLD_SECONDS = 90 * 60  # 90 minutes
STANDOUT_THRESHOLD = 0.50


@dataclass(slots=True)
class StandoutSignals:
    """External signals collected by the caller."""

    has_photos: bool = False
    state_shift_count: int = 0
    first_seen_entities: list[str] = field(default_factory=list)


def compute_standout_score(
    *,
    episode: Mapping[str, Any],
    signals: StandoutSignals,
) -> tuple[float, str, bool]:
    """Return (score, reason, is_standout) for an episode.

    `score` is clamped to [0.0, 1.0]. `reason` is a ;-joined list of
    contributing signal tags (e.g. "duration;photos;first_entity[x,y]").
    `is_standout` is True iff score >= STANDOUT_THRESHOLD.
    """
    score = 0.0
    reasons: list[str] = []

    # Duration
    duration_seconds = max(
        0.0,
        float(episode.get("time_end") or 0.0) - float(episode.get("time_start") or 0.0),
    )
    if duration_seconds >= DURATION_THRESHOLD_SECONDS:
        score += WEIGHT_DURATION
        minutes = int(duration_seconds // 60)
        reasons.append(f"duration[{minutes}min]")

    # Photos
    if signals.has_photos:
        score += WEIGHT_PHOTOS
        reasons.append("photos")

    # State shifts
    shift_count = max(0, int(signals.state_shift_count or 0))
    if shift_count > 0:
        score += WEIGHT_STATE_SHIFT
        reasons.append(f"state_shift[{shift_count}]")

    # First-occurrence entities
    firsts = [e for e in (signals.first_seen_entities or []) if e]
    if firsts:
        entity_score = min(WEIGHT_FIRST_ENTITY_CAP, len(firsts) * WEIGHT_FIRST_ENTITY_EACH)
        score += entity_score
        # Show up to 3 entity ids in the reason for traceability
        sample = ",".join(firsts[:3])
        reasons.append(f"first_entity[{sample}]")

    score = max(0.0, min(1.0, score))
    reason = ";".join(reasons) if reasons else "no signals"
    is_standout = score >= STANDOUT_THRESHOLD
    return score, reason, is_standout
```

- [ ] **Step 4: Run, expect pass**

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest tests/timeline/standout/ -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/asuka/code/magi && git add backend/src/magi/timeline/standout/ backend/tests/timeline/standout/ && git commit -m "feat(timeline/standout): heuristic scoring function"
```

---

## Task 7: Standout rescoring scheduler

**Files:**
- Create: `backend/src/magi/timeline/standout/scheduler_contrib.py`
- Test: `backend/tests/timeline/standout/test_scheduler_contrib.py`

Periodically iterates active episodes, computes signals, calls `compute_standout_score`, persists `magi_standout`/`standout_score`/`standout_reason` via `update_episode`.

- [ ] **Step 1: Write failing test**

Create `backend/tests/timeline/standout/test_scheduler_contrib.py`:

```python
"""Tests for StandoutScoringSchedulerContrib."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from magi.scheduler.contracts import (
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
)


@pytest.mark.asyncio
async def test_contributor_registers_handler():
    from magi.timeline.standout.scheduler_contrib import StandoutScoringSchedulerContrib

    contrib = StandoutScoringSchedulerContrib(
        l2_store=AsyncMock(), media_registry=AsyncMock(),
    )
    scheduler = AsyncMock()
    scheduler.register_handler = AsyncMock()
    await contrib.register_schedules(scheduler)

    scheduler.register_handler.assert_awaited_once()
    args, _ = scheduler.register_handler.call_args
    assert args[0] == ScheduledTargetType.TIMELINE_STANDOUT_RESCORE


@pytest.mark.asyncio
async def test_handler_scores_active_episodes_and_writes_back(
    l2_store_with_schema, tmp_path,
):
    from magi.timeline.standout.scheduler_contrib import StandoutScoringSchedulerContrib
    from magi.media.source_registry import MediaSourceRegistry

    # Seed: one long episode (90 min+), one short
    await l2_store_with_schema.create_episode(
        episode_id="ep-long", time_start=0.0, time_end=7200.0,
        primary_entity_ids=["alice"],
    )
    await l2_store_with_schema.update_episode(episode_id="ep-long", status="active")
    await l2_store_with_schema.create_episode(
        episode_id="ep-short", time_start=8000.0, time_end=8100.0,
        primary_entity_ids=[],
    )
    await l2_store_with_schema.update_episode(episode_id="ep-short", status="active")

    registry = MediaSourceRegistry()  # empty — no photos
    contrib = StandoutScoringSchedulerContrib(
        l2_store=l2_store_with_schema, media_registry=registry,
    )
    context = ScheduledExecutionContext(
        schedule=None, target_state=None, triggered_at=10000.0, manual=False,
    )

    result = await contrib._handle_rescore(context)
    assert isinstance(result, ScheduledExecutionResult)
    assert result.success is True

    long_ep = await l2_store_with_schema.get_episode(episode_id="ep-long")
    short_ep = await l2_store_with_schema.get_episode(episode_id="ep-short")

    # Long episode duration alone (0.35) is below threshold (0.50), but with first-entity for "alice"
    # (0.30) → 0.65, magi_standout = True.
    assert long_ep["magi_standout"] is True
    assert long_ep["standout_score"] > 0.5
    assert "duration" in long_ep["standout_reason"]

    # Short episode — no signals
    assert short_ep["magi_standout"] is False
    assert short_ep["standout_score"] == pytest.approx(0.0)
```

- [ ] **Step 2: Run, expect failure (module missing)**

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest tests/timeline/standout/test_scheduler_contrib.py -v
```

- [ ] **Step 3: Create the scheduler contributor**

Create `backend/src/magi/timeline/standout/scheduler_contrib.py`:

```python
"""Scheduler integration for standout episode rescoring."""

from __future__ import annotations

from typing import Protocol

from ...core.logger import get_logger
from ...media.source_registry import MediaSourceRegistry
from ...scheduler.contracts import (
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
)
from .scoring import StandoutSignals, compute_standout_score

logger = get_logger("magi.timeline.standout.scheduler")


class _L2EpisodeStoreProtocol(Protocol):
    async def list_episodes(self, **kwargs) -> list[dict]: ...
    async def update_episode(self, *, episode_id: str, **fields) -> bool: ...


class StandoutScoringSchedulerContrib:
    """Periodic rescore of all active episodes.

    Picks signals lazily from existing data:
      - has_photos: MediaSourceRegistry.collect_assets within the episode window
      - state_shift_count: not yet wired; defaults to 0 in Plan 2 (Plan 3 frontend
        won't notice; later we can plug in state-marker data from L3)
      - first_seen_entities: an entity is "first seen" if no earlier episode shares it

    First-seen detection is approximate and per-batch: we compare the current
    episode's entities against entities seen in episodes with strictly smaller
    time_start. Good enough for scoring; precise dedup is a future refinement.
    """

    def __init__(
        self,
        *,
        l2_store: _L2EpisodeStoreProtocol,
        media_registry: MediaSourceRegistry,
        batch_limit: int = 500,
    ) -> None:
        self._l2_store = l2_store
        self._media_registry = media_registry
        self._batch_limit = batch_limit

    async def register_schedules(self, scheduler) -> None:
        await scheduler.register_handler(
            ScheduledTargetType.TIMELINE_STANDOUT_RESCORE,
            self._handle_rescore,
        )

    async def unregister_schedules(self, scheduler) -> None:
        unregister = getattr(scheduler, "unregister_handler", None)
        if unregister:
            await unregister(ScheduledTargetType.TIMELINE_STANDOUT_RESCORE)

    async def _handle_rescore(
        self, context: ScheduledExecutionContext,
    ) -> ScheduledExecutionResult:
        episodes = await self._l2_store.list_episodes(
            statuses=["active"], limit=self._batch_limit,
        )

        # Order ascending by time_start for first-entity detection
        episodes_sorted = sorted(episodes, key=lambda e: float(e.get("time_start") or 0.0))
        seen_entities: set[str] = set()
        scored = 0
        promoted = 0

        for ep in episodes_sorted:
            ep_entities = [str(e) for e in (ep.get("primary_entity_ids") or []) if e]
            first_seen = [e for e in ep_entities if e not in seen_entities]
            seen_entities.update(ep_entities)

            # has_photos check via media registry
            ts = float(ep.get("time_start") or 0.0)
            te = float(ep.get("time_end") or ts)
            try:
                assets = await self._media_registry.collect_assets(start=ts, end=te)
            except Exception:
                assets = []
            has_photos = bool(assets)

            signals = StandoutSignals(
                has_photos=has_photos,
                state_shift_count=0,  # plan 3+ when L3 markers wire in
                first_seen_entities=first_seen,
            )
            score, reason, is_standout = compute_standout_score(episode=ep, signals=signals)

            await self._l2_store.update_episode(
                episode_id=ep["episode_id"],
                magi_standout=is_standout,
                standout_score=score,
                standout_reason=reason,
            )
            scored += 1
            if is_standout:
                promoted += 1

        return ScheduledExecutionResult(
            success=True,
            message=f"scored {scored} episodes, promoted {promoted} to standout",
            stats={"scored": scored, "promoted": promoted},
        )
```

- [ ] **Step 4: Run, expect pass**

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest tests/timeline/standout/test_scheduler_contrib.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/asuka/code/magi && git add backend/src/magi/timeline/standout/scheduler_contrib.py backend/tests/timeline/standout/test_scheduler_contrib.py && git commit -m "feat(timeline/standout): rescoring scheduler contributor"
```

---

## Task 8: daily_mood_aggregate algorithm C

**Files:**
- Create: `backend/src/magi/timeline/mood/__init__.py`
- Create: `backend/src/magi/timeline/mood/algorithm.py`
- Test: `backend/tests/timeline/mood/__init__.py`
- Test: `backend/tests/timeline/mood/test_algorithm.py`

A pure function `compute_daily_mood_aggregate(valence_samples) -> DailyMoodAggregate` implementing algorithm C from the spec: time-weighted dominant valence + volatility (scaled stddev) + a compact hourly sparkline.

Input shape: a list of `(timestamp, valence)` pairs spanning the day. Valence is mapped to a band string (warm / bright / neutral / cool / tense) using the same thresholds the existing `TimelineStateBandBuilder` uses.

- [ ] **Step 1: Write failing tests**

Create `backend/tests/timeline/mood/__init__.py` (empty).

Create `backend/tests/timeline/mood/test_algorithm.py`:

```python
"""Tests for the daily mood aggregate algorithm (Algorithm C)."""

from __future__ import annotations

import pytest


def test_flat_warm_day_has_low_volatility():
    from magi.timeline.mood.algorithm import compute_daily_mood_aggregate

    # 24 samples of valence 0.5 (warm) at hourly intervals
    samples = [(float(h * 3600), 0.5) for h in range(24)]
    agg = compute_daily_mood_aggregate(day_local_date="2026-05-17", samples=samples)

    assert agg.day_local_date == "2026-05-17"
    assert agg.dominant_valence == "warm"
    assert agg.volatility_score < 0.1
    assert agg.event_count == 24
    assert len(agg.state_curve_compact) == 24


def test_mixed_morning_tense_afternoon_bright_has_high_volatility():
    from magi.timeline.mood.algorithm import compute_daily_mood_aggregate

    # First half tense (-0.6), second half bright (0.75)
    samples = [(float(h * 3600), -0.6) for h in range(12)]
    samples += [(float(h * 3600), 0.75) for h in range(12, 24)]
    agg = compute_daily_mood_aggregate(day_local_date="2026-05-17", samples=samples)

    # Roughly tied — either could dominate; check volatility is high
    assert agg.volatility_score > 0.5
    assert agg.dominant_valence in ("tense", "bright")  # whichever the algorithm picks
    assert len(agg.state_curve_compact) == 24


def test_dominant_valence_is_longest_band_by_time():
    from magi.timeline.mood.algorithm import compute_daily_mood_aggregate

    # 1 hour tense, 23 hours warm — warm should dominate
    samples = [(0.0, -0.5)] + [(float(h * 3600), 0.5) for h in range(1, 24)]
    agg = compute_daily_mood_aggregate(day_local_date="2026-05-17", samples=samples)

    assert agg.dominant_valence == "warm"


def test_empty_samples_produces_neutral_default():
    from magi.timeline.mood.algorithm import compute_daily_mood_aggregate

    agg = compute_daily_mood_aggregate(day_local_date="2026-05-17", samples=[])
    assert agg.dominant_valence == "neutral"
    assert agg.volatility_score == pytest.approx(0.0)
    assert agg.event_count == 0
    assert agg.state_curve_compact == []


def test_valence_band_thresholds_match_spec():
    from magi.timeline.mood.algorithm import valence_to_band

    assert valence_to_band(0.65) == "bright"
    assert valence_to_band(0.45) == "warm"
    assert valence_to_band(0.0) == "neutral"
    assert valence_to_band(-0.3) == "cool"
    assert valence_to_band(-0.6) == "tense"
```

- [ ] **Step 2: Run, expect failure**

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest tests/timeline/mood/ -v
```

- [ ] **Step 3: Create the algorithm module**

Create `backend/src/magi/timeline/mood/__init__.py`:

```python
"""Daily mood aggregate computation (Algorithm C)."""
```

Create `backend/src/magi/timeline/mood/algorithm.py`:

```python
"""Algorithm C: time-weighted dominant valence + volatility + sparkline.

The dominant_valence is the band that held the longest time fraction of
the day. The volatility_score is a scaled standard deviation of valence
samples. The state_curve_compact is an hourly-bucketed valence list
(0-24 floats; -1.0 means "no data" so the UI can render gaps).
"""

from __future__ import annotations

import statistics
import time
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Sequence

from ...memory.l3.daily_mood.models import DailyMoodAggregate


VALENCE_BANDS: Sequence[tuple[float, str]] = (
    (0.60, "bright"),
    (0.20, "warm"),
    (-0.20, "neutral"),
    (-0.50, "cool"),
    (-1.01, "tense"),  # catch-all floor
)


def valence_to_band(valence: float) -> str:
    """Map a valence value [-1, 1] to a band label."""
    for threshold, band in VALENCE_BANDS:
        if valence >= threshold:
            return band
    return "tense"


def compute_daily_mood_aggregate(
    *,
    day_local_date: str,
    samples: Iterable[tuple[float, float]],
) -> DailyMoodAggregate:
    """Compute the per-day aggregate from raw (timestamp, valence) samples.

    The samples should span a single day. Caller is responsible for
    bucketing per-day before invoking.
    """
    samples_list = sorted(samples, key=lambda s: s[0])

    if not samples_list:
        return DailyMoodAggregate(
            day_local_date=day_local_date,
            dominant_valence="neutral",
            volatility_score=0.0,
            state_curve_compact=[],
            event_count=0,
            computed_at=time.time(),
        )

    # Time-weighted dominant band: each sample carries a duration weight
    # equal to its gap from the next sample (last sample gets the residual
    # to a 24h boundary or 60s, whichever is smaller).
    band_durations: Counter[str] = Counter()
    for i, (ts, val) in enumerate(samples_list):
        band = valence_to_band(val)
        if i < len(samples_list) - 1:
            duration = samples_list[i + 1][0] - ts
        else:
            duration = 60.0
        if duration <= 0:
            duration = 60.0
        band_durations[band] += duration

    dominant_valence = band_durations.most_common(1)[0][0]

    # Volatility: stddev of valence values, scaled to [0, 1] (typical stddev
    # tops out around 0.7 for very swingy days; clamp at 1.0).
    valences = [v for _, v in samples_list]
    if len(valences) < 2:
        volatility = 0.0
    else:
        sd = statistics.stdev(valences)
        # Scale: 0.5 stddev ≈ moderate, 1.0 stddev ≈ max swings
        volatility = max(0.0, min(1.0, sd / 1.0))

    # Sparkline: bucket by hour (0-23), average valence in each bucket.
    hourly: dict[int, list[float]] = {}
    for ts, val in samples_list:
        # Bucket relative to the day start (assume samples span 0-86400s of the day)
        hour = int((ts // 3600) % 24)
        hourly.setdefault(hour, []).append(val)
    state_curve = []
    for h in range(24):
        bucket = hourly.get(h)
        if not bucket:
            continue
        state_curve.append(sum(bucket) / len(bucket))

    return DailyMoodAggregate(
        day_local_date=day_local_date,
        dominant_valence=dominant_valence,
        volatility_score=volatility,
        state_curve_compact=state_curve,
        event_count=len(samples_list),
        computed_at=time.time(),
    )
```

- [ ] **Step 4: Run, expect pass**

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest tests/timeline/mood/ -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/asuka/code/magi && git add backend/src/magi/timeline/mood/ backend/tests/timeline/mood/ && git commit -m "feat(timeline/mood): algorithm C — time-weighted dominant + volatility + sparkline"
```

---

## Task 9: Mood aggregate scheduler contributor

**Files:**
- Create: `backend/src/magi/timeline/mood/scheduler_contrib.py`
- Test: `backend/tests/timeline/mood/test_scheduler_contrib.py`

End-of-day handler that:
1. Computes yesterday's [start, end) UTC window
2. Gathers valence samples from L2 tom_trait_assertions (trait_families=["mood","valence"]) + L3 sentiment_summary in that window
3. Calls `compute_daily_mood_aggregate`
4. Upserts via `DailyMoodAggregateStore`

For Plan 2 we use a minimal sample source — assertions only. L3 sentiment is a follow-up if the assertions alone are too sparse.

- [ ] **Step 1: Write failing test**

Create `backend/tests/timeline/mood/test_scheduler_contrib.py`:

```python
"""Tests for MoodAggregateSchedulerContrib."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from magi.scheduler.contracts import (
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
)


@pytest.mark.asyncio
async def test_contributor_registers_handler():
    from magi.timeline.mood.scheduler_contrib import MoodAggregateSchedulerContrib

    contrib = MoodAggregateSchedulerContrib(
        sample_source=AsyncMock(), mood_store=AsyncMock(),
    )
    scheduler = AsyncMock()
    scheduler.register_handler = AsyncMock()
    await contrib.register_schedules(scheduler)

    scheduler.register_handler.assert_awaited_once()
    args, _ = scheduler.register_handler.call_args
    assert args[0] == ScheduledTargetType.TIMELINE_MOOD_AGGREGATE


@pytest.mark.asyncio
async def test_handler_aggregates_yesterday_and_upserts():
    from magi.timeline.mood.scheduler_contrib import MoodAggregateSchedulerContrib

    # Fake sample source returns 24 warm samples for any window
    sample_source = AsyncMock()
    sample_source.list_valence_samples = AsyncMock(
        return_value=[(float(h * 3600), 0.5) for h in range(24)]
    )

    upserted: list = []
    mood_store = AsyncMock()
    mood_store.upsert_aggregate = AsyncMock(
        side_effect=lambda agg: upserted.append(agg),
    )

    contrib = MoodAggregateSchedulerContrib(
        sample_source=sample_source, mood_store=mood_store,
    )
    context = ScheduledExecutionContext(
        schedule=None, target_state=None, triggered_at=1715990400.0 + 86400 * 3, manual=False,
    )

    result = await contrib._handle_aggregate(context)
    assert isinstance(result, ScheduledExecutionResult)
    assert result.success is True

    assert len(upserted) == 1
    agg = upserted[0]
    assert agg.dominant_valence == "warm"
    assert agg.volatility_score < 0.1
    assert agg.event_count == 24
```

- [ ] **Step 2: Run, expect failure**

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest tests/timeline/mood/test_scheduler_contrib.py -v
```

- [ ] **Step 3: Create the scheduler contributor**

Create `backend/src/magi/timeline/mood/scheduler_contrib.py`:

```python
"""Scheduler integration for daily mood aggregate computation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol

from ...core.logger import get_logger
from ...memory.l3.daily_mood.store import DailyMoodAggregateStore
from ...scheduler.contracts import (
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
)
from .algorithm import compute_daily_mood_aggregate

logger = get_logger("magi.timeline.mood.scheduler")


class _SampleSourceProtocol(Protocol):
    """Anything that can yield (timestamp, valence) pairs for a window."""

    async def list_valence_samples(
        self, *, start: float, end: float,
    ) -> list[tuple[float, float]]: ...


class MoodAggregateSchedulerContrib:
    """End-of-day handler that computes yesterday's mood aggregate."""

    def __init__(
        self,
        *,
        sample_source: _SampleSourceProtocol,
        mood_store: DailyMoodAggregateStore,
    ) -> None:
        self._sample_source = sample_source
        self._mood_store = mood_store

    async def register_schedules(self, scheduler) -> None:
        await scheduler.register_handler(
            ScheduledTargetType.TIMELINE_MOOD_AGGREGATE,
            self._handle_aggregate,
        )

    async def unregister_schedules(self, scheduler) -> None:
        unregister = getattr(scheduler, "unregister_handler", None)
        if unregister:
            await unregister(ScheduledTargetType.TIMELINE_MOOD_AGGREGATE)

    async def _handle_aggregate(
        self, context: ScheduledExecutionContext,
    ) -> ScheduledExecutionResult:
        triggered_at = float(getattr(context, "triggered_at", 0.0) or 0.0)
        if triggered_at <= 0:
            triggered_at = datetime.now(tz=timezone.utc).timestamp()

        triggered_dt = datetime.fromtimestamp(triggered_at, tz=timezone.utc)
        yesterday = triggered_dt.date() - timedelta(days=1)
        period_start_dt = datetime(yesterday.year, yesterday.month, yesterday.day, tzinfo=timezone.utc)
        period_end_dt = period_start_dt + timedelta(days=1)

        period_start = period_start_dt.timestamp()
        period_end = period_end_dt.timestamp()

        try:
            samples = await self._sample_source.list_valence_samples(
                start=period_start, end=period_end,
            )
        except Exception as exc:
            logger.warning("Mood sample fetch failed", error=str(exc), date=yesterday.isoformat())
            return ScheduledExecutionResult(
                success=False, message=f"sample fetch failed: {exc}", stats={},
            )

        # Shift sample timestamps to be relative to day start so the
        # algorithm's hourly bucketing maps correctly.
        relative_samples = [(ts - period_start, val) for (ts, val) in samples]

        agg = compute_daily_mood_aggregate(
            day_local_date=yesterday.isoformat(), samples=relative_samples,
        )
        await self._mood_store.upsert_aggregate(agg)

        return ScheduledExecutionResult(
            success=True,
            message=f"mood aggregate computed for {yesterday.isoformat()}",
            stats={
                "event_count": agg.event_count,
                "dominant_valence": agg.dominant_valence,
                "volatility_score": agg.volatility_score,
            },
        )
```

- [ ] **Step 4: Run, expect pass**

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest tests/timeline/mood/ -v
```

Expected: 7 passed (5 algorithm + 2 scheduler).

- [ ] **Step 5: Commit**

```bash
cd /Users/asuka/code/magi && git add backend/src/magi/timeline/mood/scheduler_contrib.py backend/tests/timeline/mood/test_scheduler_contrib.py && git commit -m "feat(timeline/mood): end-of-day aggregate scheduler contributor"
```

---

## Task 10: PhotoLibrary MediaSource adapter (L1-event backed)

**Files:**
- Create: `backend/src/magi/media/adapters/__init__.py`
- Create: `backend/src/magi/media/adapters/photo_library.py`
- Test: `backend/tests/media/adapters/__init__.py`
- Test: `backend/tests/media/adapters/test_photo_library.py`

The adapter reads existing L1 events of `source_type="photo_library"` rather than touching the plugin code. Each L1 event carries a `content_blocks` list with image refs and EXIF metadata that the photo-library sensor emitted at ingestion time. The adapter shapes them into the `{ref, timestamp, ...}` dicts that `MediaSelector.pick_representative` expects.

> **Implementation note:** because the L1 event schema's exact field layout depends on what the photo-library sensor writes, the adapter MUST treat individual fields defensively (defaults, optional, type-coerce). The implementer should peek at `target/release/sidecar-dist/_internal/plugins/photo-library/normalizers.py` and at one real `l1_events.db` row (via `sqlite3` if available, or by reading the sensor source) to confirm the exact shape before wiring the adapter. A defensive `dict.get(...)` pattern is essential.

- [ ] **Step 1: Inspect photo-library L1 event shape**

```bash
cd /Users/asuka/code/magi/target/release/sidecar-dist/_internal/plugins/photo-library && head -200 normalizers.py 2>/dev/null | head -80
```

Look for the structure being written into `SensorOutput` / L1 events. Note the fields: timestamp source, asset_ref shape (e.g. `photo-library://YYYY-MM-DD/IMG_xxxx.HEIC`), metadata keys.

If the plugin source is not available, fall back to inspecting an actual `l1_events.db` row via:

```bash
sqlite3 ~/.magi/data/memory/l1_events.db "SELECT * FROM fact_events WHERE source_type = 'photo_library' LIMIT 1;" 2>/dev/null || echo "no photo_library events present"
```

Record what you find. The adapter contract assumes (a) `timestamp` is a unix-seconds float and (b) there's a stable asset_ref string somewhere in the event payload. If the actual shape diverges, adapt the adapter to extract those two fields correctly; do not invent fields.

- [ ] **Step 2: Write failing tests**

Create `backend/tests/media/adapters/__init__.py` (empty).

Create `backend/tests/media/adapters/test_photo_library.py`:

```python
"""Tests for PhotoLibraryMediaSource (L1-event-backed)."""

from __future__ import annotations

from typing import List

import pytest


class _FakeL1Store:
    """Stub L1 store that lets us inject fact_events for specific source_types."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    async def list_events_by_source_type(
        self, *, source_type: str, start: float, end: float,
    ) -> list[dict]:
        return [
            e for e in self.events
            if e["source_type"] == source_type and start <= e["timestamp"] <= end
        ]


def test_source_id_matches_protocol():
    from magi.media.adapters.photo_library import PhotoLibraryMediaSource

    src = PhotoLibraryMediaSource(l1_store=_FakeL1Store())
    assert src.source_id == "photo-library"


@pytest.mark.asyncio
async def test_list_assets_returns_empty_when_no_events():
    from magi.media.adapters.photo_library import PhotoLibraryMediaSource

    src = PhotoLibraryMediaSource(l1_store=_FakeL1Store())
    out = await src.list_assets(start=0.0, end=1000.0)
    assert out == []


@pytest.mark.asyncio
async def test_list_assets_maps_photo_events_to_asset_dicts():
    from magi.media.adapters.photo_library import PhotoLibraryMediaSource

    l1 = _FakeL1Store()
    l1.events.append({
        "event_id": "evt-1",
        "source_type": "photo_library",
        "timestamp": 500.0,
        "asset_ref": "photo-library://2026-05-17/IMG_4423.HEIC",
        "mime_type": "image/heic",
        "metadata": {"location": "家", "people": ["alice"]},
    })
    l1.events.append({
        "event_id": "evt-2",
        "source_type": "photo_library",
        "timestamp": 800.0,
        "asset_ref": "photo-library://2026-05-17/IMG_4424.HEIC",
        "mime_type": "image/heic",
        "metadata": {},
    })

    src = PhotoLibraryMediaSource(l1_store=l1)
    out = await src.list_assets(start=0.0, end=1000.0)
    refs = sorted(a["ref"] for a in out)
    assert len(out) == 2
    assert refs == [
        "photo-library://2026-05-17/IMG_4423.HEIC",
        "photo-library://2026-05-17/IMG_4424.HEIC",
    ]
    # Each item has timestamp + extra metadata for the selector
    first = next(a for a in out if a["ref"].endswith("IMG_4423.HEIC"))
    assert first["timestamp"] == 500.0
    assert first.get("mime_type") == "image/heic"
    assert first.get("location") == "家"


@pytest.mark.asyncio
async def test_list_assets_skips_events_missing_asset_ref():
    from magi.media.adapters.photo_library import PhotoLibraryMediaSource

    l1 = _FakeL1Store()
    l1.events.append({"event_id": "evt-x", "source_type": "photo_library", "timestamp": 100.0})
    # No asset_ref — must be skipped, not crash
    src = PhotoLibraryMediaSource(l1_store=l1)
    out = await src.list_assets(start=0.0, end=1000.0)
    assert out == []
```

- [ ] **Step 3: Run, expect failure (module missing)**

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest tests/media/adapters/ -v
```

- [ ] **Step 4: Create the adapter**

Create `backend/src/magi/media/adapters/__init__.py`:

```python
"""Adapters that bridge plugin/domain L1 events to the MediaSource protocol."""

from .photo_library import PhotoLibraryMediaSource

__all__ = ["PhotoLibraryMediaSource"]
```

Create `backend/src/magi/media/adapters/photo_library.py`:

```python
"""PhotoLibraryMediaSource — exposes photo-library plugin events as a MediaSource.

The plugin itself (plugins/photo-library/) writes L1 events of
source_type="photo_library" carrying asset refs and EXIF metadata. This
adapter reads those events through the L1 store and shapes them into the
{ref, timestamp, ...} dicts the MediaSelector expects.

The adapter is intentionally tolerant of missing fields: any event that
doesn't carry a stable asset_ref is silently skipped (rather than crashing
the registry's collect_assets fan-out).
"""

from __future__ import annotations

from typing import Any, Protocol


class _L1StoreProtocol(Protocol):
    async def list_events_by_source_type(
        self, *, source_type: str, start: float, end: float,
    ) -> list[dict[str, Any]]: ...


class PhotoLibraryMediaSource:
    """MediaSource adapter over photo_library L1 events."""

    source_id = "photo-library"

    def __init__(self, *, l1_store: _L1StoreProtocol) -> None:
        self._l1_store = l1_store

    async def list_assets(self, *, start: float, end: float) -> list[dict]:
        try:
            events = await self._l1_store.list_events_by_source_type(
                source_type="photo_library", start=start, end=end,
            )
        except Exception:
            return []

        out: list[dict] = []
        for ev in events or []:
            ref = self._extract_asset_ref(ev)
            if not ref:
                continue
            ts = float(ev.get("timestamp") or 0.0)
            metadata = ev.get("metadata") or {}
            entry: dict = {
                "ref": ref,
                "timestamp": ts,
                "mime_type": ev.get("mime_type"),
            }
            if isinstance(metadata, dict):
                # Surface known keys at the top level for selector convenience.
                for key in ("location", "people", "tags"):
                    if key in metadata:
                        entry[key] = metadata[key]
            out.append(entry)
        return out

    @staticmethod
    def _extract_asset_ref(event: dict) -> str | None:
        """Defensive extraction — adapt as the plugin's L1 event schema evolves.

        Looks at common locations: top-level `asset_ref`, content_blocks first item.
        Returns None if nothing usable is present.
        """
        ref = event.get("asset_ref")
        if isinstance(ref, str) and ref.strip():
            return ref.strip()

        content_blocks = event.get("content_blocks")
        if isinstance(content_blocks, list) and content_blocks:
            first = content_blocks[0]
            if isinstance(first, dict):
                candidate = first.get("ref") or first.get("value")
                if isinstance(candidate, str) and candidate.startswith("photo-library://"):
                    return candidate.strip()

        return None
```

> **NOTE for the implementer:** the `list_events_by_source_type` method on the L1 store may not yet exist with that exact signature. Check `backend/src/magi/memory/l1/`. If the real method is named differently (e.g., `list_events(...)` with a `source_type=` filter, or `find_events_in_window(...)`), adapt the adapter to call the real method. The interface above is what the adapter NEEDS — the implementer may need to add a thin wrapper or rename to match the real L1 API.

- [ ] **Step 5: Run, expect pass**

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest tests/media/adapters/ -v
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
cd /Users/asuka/code/magi && git add backend/src/magi/media/adapters/ backend/tests/media/adapters/ && git commit -m "feat(media/adapters): PhotoLibraryMediaSource over L1 events"
```

---

## Task 11: MediaSourceRegistry bootstrap wiring

**Files:**
- Modify: `backend/src/magi/bootstrap/runtime_worker_builder.py` (or the appropriate composition root module) — instantiate `MediaSourceRegistry`, register the photo adapter

- [ ] **Step 1: Locate the composition root for memory/stateful services**

```bash
cd /Users/asuka/code/magi && grep -n "_build_stateful_service_modules\|MemoryStore\|l1_store" backend/src/magi/bootstrap/runtime_worker_builder.py | head -20
```

Find the function that builds memory/L1 services. The registry registration needs the L1 store reference.

- [ ] **Step 2: Add registry instantiation and source registration**

In the composition root, after the L1 store is built but before the scheduler module is built, add:

```python
        from ..media.source_registry import MediaSourceRegistry
        from ..media.adapters import PhotoLibraryMediaSource

        media_source_registry = MediaSourceRegistry()
        media_source_registry.register(PhotoLibraryMediaSource(l1_store=l1_store))
        # Expose on the bootstrap context so scheduler contributors can reach it
        context.media_source_registry = media_source_registry
```

> **Implementer note:** the exact way to expose this depends on the bootstrap pattern. Two cases:
> 1. If `context` is a `BootstrapContext` dataclass with explicit fields, add `media_source_registry: MediaSourceRegistry | None = None` to the dataclass definition (find it in `backend/src/magi/bootstrap/`) and assign as above.
> 2. If `context` uses a service container (dependency-injector), register via the container's `media_source_registry.override(providers.Object(...))` pattern.
> Use whichever pattern the surrounding code uses. The goal: the standout scoring scheduler (T7) and representative-asset populate scheduler (T12) can obtain the registry from the same context.

- [ ] **Step 3: Smoke-test the wiring**

There's no neat unit test for bootstrap wiring — instead, write a smoke test that import-checks the chain:

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH python -c "
from magi.media import MediaSourceRegistry
from magi.media.adapters import PhotoLibraryMediaSource

class _StubL1:
    async def list_events_by_source_type(self, **kwargs):
        return []

reg = MediaSourceRegistry()
src = PhotoLibraryMediaSource(l1_store=_StubL1())
reg.register(src)

assert reg.get('photo-library') is src
print('wiring OK')
"
```

Expected: `wiring OK`.

- [ ] **Step 4: Commit**

```bash
cd /Users/asuka/code/magi && git add backend/src/magi/bootstrap/runtime_worker_builder.py && git commit -m "feat(bootstrap): wire MediaSourceRegistry with PhotoLibraryMediaSource"
```

---

## Task 12: representative_asset_ref populate scheduler

**Files:**
- Create: `backend/src/magi/media/scheduler_contrib.py`
- Test: `backend/tests/media/test_scheduler_contrib.py`

Periodic job that finds active episodes lacking `representative_asset_ref`, calls `MediaSelector.pick_representative(start, end)`, writes the ref back via `update_episode`.

- [ ] **Step 1: Write failing test**

Create `backend/tests/media/test_scheduler_contrib.py`:

```python
"""Tests for RepresentativeAssetPopulateSchedulerContrib."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from magi.scheduler.contracts import (
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
)


@pytest.mark.asyncio
async def test_contributor_registers_handler():
    from magi.media.scheduler_contrib import RepresentativeAssetPopulateSchedulerContrib

    contrib = RepresentativeAssetPopulateSchedulerContrib(
        l2_store=AsyncMock(), selector=AsyncMock(),
    )
    scheduler = AsyncMock()
    scheduler.register_handler = AsyncMock()
    await contrib.register_schedules(scheduler)

    scheduler.register_handler.assert_awaited_once()
    args, _ = scheduler.register_handler.call_args
    assert args[0] == ScheduledTargetType.TIMELINE_REPRESENTATIVE_ASSET


@pytest.mark.asyncio
async def test_handler_populates_missing_refs(l2_store_with_schema, tmp_path):
    from magi.media.scheduler_contrib import RepresentativeAssetPopulateSchedulerContrib
    from magi.media.selector import MediaSelector
    from magi.media.source_registry import MediaSourceRegistry

    # Seed: 2 episodes, neither has a representative_asset_ref yet
    await l2_store_with_schema.create_episode(
        episode_id="ep-a", time_start=100.0, time_end=200.0,
    )
    await l2_store_with_schema.update_episode(episode_id="ep-a", status="active")
    await l2_store_with_schema.create_episode(
        episode_id="ep-b", time_start=300.0, time_end=400.0,
    )
    await l2_store_with_schema.update_episode(episode_id="ep-b", status="active")

    # Stub source that returns a photo for episode A's window only
    class _StubSource:
        source_id = "photo-library"

        async def list_assets(self, *, start: float, end: float) -> list[dict]:
            if start <= 150.0 <= end:
                return [{"ref": "photo-library://A.HEIC", "timestamp": 150.0}]
            return []

    registry = MediaSourceRegistry()
    registry.register(_StubSource())
    selector = MediaSelector(registry=registry)

    contrib = RepresentativeAssetPopulateSchedulerContrib(
        l2_store=l2_store_with_schema, selector=selector,
    )
    context = ScheduledExecutionContext(
        schedule=None, target_state=None, triggered_at=1000.0, manual=False,
    )

    result = await contrib._handle_populate(context)
    assert isinstance(result, ScheduledExecutionResult)
    assert result.success is True

    ep_a = await l2_store_with_schema.get_episode(episode_id="ep-a")
    ep_b = await l2_store_with_schema.get_episode(episode_id="ep-b")

    assert ep_a["representative_asset_ref"] == "photo-library://A.HEIC"
    # Episode B's window had no photos → stays empty
    assert ep_b["representative_asset_ref"] == ""


@pytest.mark.asyncio
async def test_handler_does_not_overwrite_existing_ref(l2_store_with_schema, tmp_path):
    from magi.media.scheduler_contrib import RepresentativeAssetPopulateSchedulerContrib
    from magi.media.selector import MediaSelector
    from magi.media.source_registry import MediaSourceRegistry

    await l2_store_with_schema.create_episode(
        episode_id="ep-pre", time_start=100.0, time_end=200.0,
    )
    await l2_store_with_schema.update_episode(
        episode_id="ep-pre", status="active",
        representative_asset_ref="photo-library://existing.HEIC",
    )

    # Selector would return a different ref if asked
    class _StubSource:
        source_id = "photo-library"
        async def list_assets(self, *, start, end):
            return [{"ref": "photo-library://newer.HEIC", "timestamp": 150.0}]

    registry = MediaSourceRegistry()
    registry.register(_StubSource())
    selector = MediaSelector(registry=registry)

    contrib = RepresentativeAssetPopulateSchedulerContrib(
        l2_store=l2_store_with_schema, selector=selector,
    )
    context = ScheduledExecutionContext(
        schedule=None, target_state=None, triggered_at=1000.0, manual=False,
    )

    await contrib._handle_populate(context)
    ep = await l2_store_with_schema.get_episode(episode_id="ep-pre")
    assert ep["representative_asset_ref"] == "photo-library://existing.HEIC"
```

> The L2 conftest fixture `l2_store_with_schema` is discovered from `tests/memory/l2/conftest.py` only within that directory tree. To use it under `tests/media/`, either add a `tests/media/conftest.py` mirroring T4's pattern, or re-define the fixture inline. Pick the inline approach to keep this task self-contained:
>
> Append to `backend/tests/media/conftest.py` (file may need to be created):
> ```python
> from __future__ import annotations
>
> import pytest_asyncio
>
> from _shared.memory_schema import apply_memory_shared_schema
>
>
> @pytest_asyncio.fixture
> async def l2_store_with_schema(tmp_path):
>     from magi.memory.l2.store import L2CognitionStore
>
>     db_path = str(tmp_path / "l2.db")
>     await apply_memory_shared_schema(db_path)
>     store = L2CognitionStore(db_path=db_path)
>     await store.initialize()
>     return store
> ```

- [ ] **Step 2: Run, expect failure**

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest tests/media/test_scheduler_contrib.py -v
```

- [ ] **Step 3: Create the scheduler contributor**

Create `backend/src/magi/media/scheduler_contrib.py`:

```python
"""Scheduler integration for populating L2 episode representative_asset_ref."""

from __future__ import annotations

from typing import Protocol

from ..core.logger import get_logger
from ..scheduler.contracts import (
    ScheduledExecutionContext,
    ScheduledExecutionResult,
    ScheduledTargetType,
)
from .selector import MediaSelector

logger = get_logger("magi.media.scheduler")


class _L2EpisodeStoreProtocol(Protocol):
    async def list_episodes(self, **kwargs) -> list[dict]: ...
    async def update_episode(self, *, episode_id: str, **fields) -> bool: ...


class RepresentativeAssetPopulateSchedulerContrib:
    """Populate representative_asset_ref for active episodes that lack one.

    Does NOT overwrite an existing ref — the act of having a ref means
    either the populate job already picked one or a Plan-3-era user
    explicitly chose. Both should be respected.
    """

    def __init__(
        self,
        *,
        l2_store: _L2EpisodeStoreProtocol,
        selector: MediaSelector,
        batch_limit: int = 200,
    ) -> None:
        self._l2_store = l2_store
        self._selector = selector
        self._batch_limit = batch_limit

    async def register_schedules(self, scheduler) -> None:
        await scheduler.register_handler(
            ScheduledTargetType.TIMELINE_REPRESENTATIVE_ASSET,
            self._handle_populate,
        )

    async def unregister_schedules(self, scheduler) -> None:
        unregister = getattr(scheduler, "unregister_handler", None)
        if unregister:
            await unregister(ScheduledTargetType.TIMELINE_REPRESENTATIVE_ASSET)

    async def _handle_populate(
        self, context: ScheduledExecutionContext,
    ) -> ScheduledExecutionResult:
        episodes = await self._l2_store.list_episodes(
            statuses=["active"], limit=self._batch_limit,
        )

        populated = 0
        skipped_already_set = 0
        for ep in episodes:
            existing = ep.get("representative_asset_ref")
            if existing:
                skipped_already_set += 1
                continue
            ts = float(ep.get("time_start") or 0.0)
            te = float(ep.get("time_end") or ts)
            ref = await self._selector.pick_representative(
                start=ts, end=te, hint="hero",
            )
            if not ref:
                continue
            await self._l2_store.update_episode(
                episode_id=ep["episode_id"], representative_asset_ref=ref,
            )
            populated += 1

        return ScheduledExecutionResult(
            success=True,
            message=f"populated {populated} refs ({skipped_already_set} already set)",
            stats={"populated": populated, "skipped": skipped_already_set},
        )
```

- [ ] **Step 4: Run, expect pass**

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest tests/media/test_scheduler_contrib.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/asuka/code/magi && git add backend/src/magi/media/scheduler_contrib.py backend/tests/media/test_scheduler_contrib.py backend/tests/media/conftest.py && git commit -m "feat(media): RepresentativeAssetPopulateSchedulerContrib"
```

---

## Task 13: Integration test + full sweep

**Files:** none modified — validation only.

- [ ] **Step 1: Run the full Plan-2 test suite**

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest \
  tests/llm/test_scenario_pool_timeline_diary.py \
  tests/timeline/narrative/ \
  tests/timeline/standout/ \
  tests/timeline/mood/ \
  tests/media/adapters/ \
  tests/media/test_scheduler_contrib.py \
  --no-header 2>&1 | tail -5
```

Expected: all green. Pass count should be roughly: 2 (LLM scenario) + 6 (narrative schema+prompts) + 2 (LLM client) + 3 (orchestrator) + 2 (diary scheduler) + 6 (standout scoring) + 2 (standout scheduler) + 5 (mood algorithm) + 2 (mood scheduler) + 4 (photo adapter) + 3 (asset populate scheduler) = **37 passed**.

- [ ] **Step 2: Re-run Plan-1 suite to confirm no regression**

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH pytest \
  tests/memory/l2/test_episodes_immersive_fields.py \
  tests/memory/l3/test_summaries_essence_prose.py \
  tests/memory/l3/daily_mood/ \
  tests/media/test_source_registry.py \
  tests/media/test_selector.py \
  tests/api/test_timeline_standout.py \
  tests/api/test_timeline_mood_calendar.py \
  --no-header 2>&1 | tail -5
```

Expected: 28 passed (unchanged from Plan 1 acceptance).

- [ ] **Step 3: Run API contract checker**

```bash
cd /Users/asuka/code/magi && PATH=/Users/asuka/lib/miniconda3/bin:$PATH python scripts/check-api-contract.py 2>&1 | tail -3
```

Expected: `Gateway API contract check passed`. Plan 2 didn't add new endpoints, so this should still pass.

- [ ] **Step 4: Run SQLite ownership checker**

```bash
cd /Users/asuka/code/magi && PATH=/Users/asuka/lib/miniconda3/bin:$PATH python scripts/check-sqlite-ownership.py 2>&1 | tail -3
```

Expected: `SQLite ownership check passed`. Plan 2 didn't add new tables — only Python-owned writes to existing Plan-1 tables.

- [ ] **Step 5: End-to-end smoke (optional)**

If a real runtime DB is convenient, run the standout rescoring scheduler manually against it:

```bash
cd /Users/asuka/code/magi/backend && PATH=/Users/asuka/lib/miniconda3/bin:$PATH python -c "
import asyncio
from magi.memory.l2.store import L2CognitionStore
from magi.media.source_registry import MediaSourceRegistry
from magi.timeline.standout.scheduler_contrib import StandoutScoringSchedulerContrib

async def go():
    store = L2CognitionStore(db_path='~/.magi/data/memory/memory.db')
    await store.initialize()
    contrib = StandoutScoringSchedulerContrib(l2_store=store, media_registry=MediaSourceRegistry())
    class _Ctx: triggered_at = 0; schedule=None; target_state=None; manual=True
    result = await contrib._handle_rescore(_Ctx())
    print(result.message)
asyncio.run(go())
" 2>&1 | tail -5
```

Optional — skip if no real DB. If run, expect a message like `scored N episodes, promoted M to standout`.

- [ ] **Step 6: Final commit if any fixes were applied**

If you had to adjust any code during the sweep:

```bash
cd /Users/asuka/code/magi && git status
git add -A && git commit -m "fix(timeline): typecheck/contract fixes after Plan 2 sweep"
```

If everything passed clean, no commit needed.

---

## Acceptance criteria for Plan 2

- `TIMELINE_DIARY_NARRATIVE` scenario is registered and resolves through `ScenarioLLMPool` (falls back to `CORE`).
- The diary orchestrator generates an L3 essence + per-episode `slice_narrative` for any period with active episodes, given a working LLM.
- Empty-period and empty-LLM-response cases are no-ops (no L3 row created, no slice writes).
- The `DiaryNarrativeSchedulerContrib` registers on `TIMELINE_DIARY_NARRATIVE` and processes yesterday's day window when triggered.
- The standout scoring function returns deterministic `(score, reason, is_standout)` for given signals.
- The standout rescoring scheduler processes all active episodes, updating `magi_standout`/`standout_score`/`standout_reason`.
- The mood algorithm returns the time-weighted dominant band and volatility score; flat days have low volatility, swingy days high.
- The mood aggregate scheduler computes yesterday's aggregate and upserts into `DailyMoodAggregateStore`.
- The `PhotoLibraryMediaSource` adapter returns `{ref, timestamp, ...}` dicts from L1 events of `source_type="photo_library"`.
- The bootstrap composition root wires `MediaSourceRegistry` and registers the photo adapter at startup.
- The `RepresentativeAssetPopulateSchedulerContrib` writes `representative_asset_ref` for episodes that don't have one and does not overwrite existing values.
- All Plan-1 acceptance criteria still hold (no regression).
- API contract and SQLite ownership checks still pass.

## Handoff to Plan 3

Plan 3 (frontend immersive redesign) will:
- Rewrite `frontend/src/pages/Timeline.tsx` and its component tree per the spec
- Remove `TimelineContextDrawer` and the calibration handlers
- Render hero photos using `representative_asset_ref` (resolved server-side via a Plan 3 endpoint or the chat-attachment URL pattern)
- Render sidebar mood calendar using `/timeline/mood-calendar` (from Plan 1)
- Render sidebar 值得回来的 using `/timeline/standout` (from Plan 1)
- Render slice prose using `slice_narrative` + `slice_sensory_detail` (populated by Plan 2's orchestrator)
- Render period essence using L3 `essence_prose` (populated by Plan 2's orchestrator) — viewport endpoint may need a small extension to surface this field
- Add the ♡ hover gesture (calls existing `annotateEpisode` API) and ⋯ hide menu (calls existing `forgetEpisode(id, false)`)
- Switch default landing scale from `month` to `day`

Plan 2 changes are entirely backend; Plan 3 is entirely frontend. They can be developed in parallel after Plan 2's contract surfaces stabilize.
