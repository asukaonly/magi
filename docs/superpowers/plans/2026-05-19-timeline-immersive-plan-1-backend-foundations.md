# Timeline Immersive Redesign — Plan 1: Backend Foundations

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the schema migrations, persistence extensions, the new `backend/src/magi/media/` layer, and the two new read endpoints (`/timeline/standout`, `/timeline/mood-calendar`) so that Plan 2 (generation pipeline) and Plan 3 (frontend) have stable contracts to consume. **No user-visible behavior change** — the existing timeline UI continues to work; new fields are nullable/optional and unread by the current frontend.

**Architecture:** L2 episode + L3 summary tables gain new nullable columns via Alembic migrations under `backend/src/magi/db/migrations/memory_shared/versions/`. A new `daily_mood_aggregate` table is created. The new `backend/src/magi/media/` package provides a `MediaSourceRegistry` + `MediaSelector` + `AssetResolver` skeleton (no sources registered yet — Plan 2 will register photo-library). Two read endpoints are added to the existing `timeline` router; they return sparse but valid results until Plan 2 populates the underlying data.

**Tech Stack:** Python 3.13, FastAPI (in-memory ASGI), aiosqlite, Alembic, pytest-asyncio. The new endpoints are Python-only and reached through the Rust gateway's existing python-ipc proxy — no Rust changes required since `/api/timeline` is already a registered proxy prefix in `contracts/api/gateway_routes.json`.

---

## Reference docs

- Spec: [docs/superpowers/specs/2026-05-19-timeline-immersive-redesign-design.md](../specs/2026-05-19-timeline-immersive-redesign-design.md)
- Architecture context: [docs/timeline-domain-architecture.md](../../timeline-domain-architecture.md), [docs/memory-system-design.md](../../memory-system-design.md)
- Related (proposed): [docs/unified-asset-resolver-architecture.md](../../unified-asset-resolver-architecture.md) — the `AssetResolver` in this plan is a forward-compatible skeleton for that proposal.

## File structure (created or modified by this plan)

**Created:**
- `backend/src/magi/db/migrations/memory_shared/versions/0003_l2_episode_immersive_columns.py`
- `backend/src/magi/db/migrations/memory_shared/versions/0004_l3_summary_essence_prose.py`
- `backend/src/magi/db/migrations/memory_shared/versions/0005_daily_mood_aggregate.py`
- `backend/src/magi/memory/l3/daily_mood/__init__.py`
- `backend/src/magi/memory/l3/daily_mood/models.py`
- `backend/src/magi/memory/l3/daily_mood/store.py`
- `backend/src/magi/media/__init__.py`
- `backend/src/magi/media/source_registry.py`
- `backend/src/magi/media/selector.py`
- `backend/src/magi/media/resolver.py`
- `backend/tests/memory/l2/test_episodes_immersive_fields.py`
- `backend/tests/memory/l3/test_summaries_essence_prose.py`
- `backend/tests/memory/l3/daily_mood/__init__.py`
- `backend/tests/memory/l3/daily_mood/test_store.py`
- `backend/tests/media/__init__.py`
- `backend/tests/media/test_source_registry.py`
- `backend/tests/media/test_selector.py`
- `backend/tests/api/test_timeline_standout.py`
- `backend/tests/api/test_timeline_mood_calendar.py`

**Modified:**
- `backend/src/magi/memory/l2/episode_models.py` (extend `EpisodeWrite`)
- `backend/src/magi/memory/l2/episodes/crud.py` (extend `create_episode` + `update_episode` allowed set)
- `backend/src/magi/memory/l2/episodes/codec.py` (extend `_episode_row_to_dict`)
- `backend/src/magi/api/routers/timeline.py` (add 2 new endpoints)
- `backend/src/magi/api/routes.py` (add new public-route entries under `timeline`)

No changes to Rust gateway code or `gateway_routes.json` (timeline prefix already registered as `python-ipc`).

---

## Task 1: Migration 0003 — extend `episodes` table

**Files:**
- Create: `backend/src/magi/db/migrations/memory_shared/versions/0003_l2_episode_immersive_columns.py`

Adds 6 nullable columns to `episodes`: `slice_narrative`, `slice_sensory_detail`, `magi_standout`, `standout_score`, `standout_reason`, `representative_asset_ref`. SQLite does not support multi-column `ALTER`; one statement per column.

- [ ] **Step 1: Write the migration file**

```python
"""l2 episode immersive columns

Revision ID: 0003_l2_episode_immersive_columns
Revises: 0002_user_profile_projection
Create Date: 2026-05-19
"""

from __future__ import annotations

from alembic import op

revision = "0003_l2_episode_immersive_columns"
down_revision = "0002_user_profile_projection"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
ALTER TABLE episodes ADD COLUMN slice_narrative TEXT;
ALTER TABLE episodes ADD COLUMN slice_sensory_detail TEXT;
ALTER TABLE episodes ADD COLUMN magi_standout INTEGER NOT NULL DEFAULT 0;
ALTER TABLE episodes ADD COLUMN standout_score REAL NOT NULL DEFAULT 0.0;
ALTER TABLE episodes ADD COLUMN standout_reason TEXT;
ALTER TABLE episodes ADD COLUMN representative_asset_ref TEXT;
CREATE INDEX IF NOT EXISTS idx_episodes_standout
    ON episodes(magi_standout, standout_score DESC, time_start DESC)
    WHERE magi_standout = 1 OR user_pinned = 1;
"""

DROP_SQL = """
DROP INDEX IF EXISTS idx_episodes_standout;
ALTER TABLE episodes DROP COLUMN representative_asset_ref;
ALTER TABLE episodes DROP COLUMN standout_reason;
ALTER TABLE episodes DROP COLUMN standout_score;
ALTER TABLE episodes DROP COLUMN magi_standout;
ALTER TABLE episodes DROP COLUMN slice_sensory_detail;
ALTER TABLE episodes DROP COLUMN slice_narrative;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
```

- [ ] **Step 2: Run migration against an empty test DB to verify SQL is valid**

```bash
cd /Users/asuka/code/magi/backend && python -c "
import asyncio, tempfile, aiosqlite
from magi.db.migrations.memory_shared.versions import (
    _0001_initial as m1, _0002_user_profile_projection as m2,
)
from magi.db.migrations.memory_shared.versions._0003_l2_episode_immersive_columns import SCHEMA_SQL as s3
async def go():
    with tempfile.NamedTemporaryFile(suffix='.db') as f:
        async with aiosqlite.connect(f.name) as db:
            await db.executescript(m1.SCHEMA_SQL)
            await db.executescript(m2.SCHEMA_SQL)
            await db.executescript(s3)
            cur = await db.execute('PRAGMA table_info(episodes)')
            cols = [r[1] for r in await cur.fetchall()]
            for needed in ['slice_narrative','slice_sensory_detail','magi_standout','standout_score','standout_reason','representative_asset_ref']:
                assert needed in cols, f'missing column {needed}'
            print('OK', len(cols), 'columns')
asyncio.run(go())
"
```

Expected: `OK 30 columns` (24 original + 6 new). If module import paths complain about the leading-digit filename, rename to use module-friendly import or skip this command and rely on the test in Task 2.

- [ ] **Step 3: Commit**

```bash
git add backend/src/magi/db/migrations/memory_shared/versions/0003_l2_episode_immersive_columns.py
git commit -m "feat(memory/l2): migration 0003 add immersive timeline columns to episodes"
```

---

## Task 2: Extend `EpisodeWrite` dataclass with the 6 new fields

**Files:**
- Modify: `backend/src/magi/memory/l2/episode_models.py`
- Test: `backend/tests/memory/l2/test_episodes_immersive_fields.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/memory/l2/test_episodes_immersive_fields.py`:

```python
"""Tests for the immersive-timeline fields added to EpisodeWrite."""

from __future__ import annotations

import pytest


def test_episode_write_defaults_for_immersive_fields():
    from magi.memory.l2.episode_models import EpisodeWrite

    ep = EpisodeWrite(episode_id="ep-1", time_start=100.0, time_end=200.0)

    assert ep.slice_narrative == ""
    assert ep.slice_sensory_detail == ""
    assert ep.magi_standout is False
    assert ep.standout_score == 0.0
    assert ep.standout_reason == ""
    assert ep.representative_asset_ref == ""


def test_episode_write_accepts_immersive_fields():
    from magi.memory.l2.episode_models import EpisodeWrite

    ep = EpisodeWrite(
        episode_id="ep-2",
        time_start=100.0,
        time_end=200.0,
        slice_narrative="下午你在改 portrait rail。",
        slice_sensory_detail="窗外开始下雨。",
        magi_standout=True,
        standout_score=0.83,
        standout_reason="duration>90min;has_photos;first_entity",
        representative_asset_ref="photo-library://2026-05-17/IMG_4423.HEIC",
    )

    assert ep.slice_narrative == "下午你在改 portrait rail。"
    assert ep.magi_standout is True
    assert ep.standout_score == pytest.approx(0.83)
    assert ep.representative_asset_ref.startswith("photo-library://")


def test_episode_write_from_dict_round_trip_includes_immersive():
    from magi.memory.l2.episode_models import EpisodeWrite

    src = {
        "episode_id": "ep-3",
        "time_start": 0.0,
        "time_end": 1.0,
        "magi_standout": True,
        "standout_score": 0.5,
        "slice_narrative": "x",
        "representative_asset_ref": "ref://y",
    }
    restored = EpisodeWrite.from_dict(src)
    out = restored.to_dict()
    assert out["magi_standout"] is True
    assert out["standout_score"] == 0.5
    assert out["slice_narrative"] == "x"
    assert out["representative_asset_ref"] == "ref://y"
```

- [ ] **Step 2: Run the test, expect failure**

```bash
cd /Users/asuka/code/magi/backend && pytest tests/memory/l2/test_episodes_immersive_fields.py -v
```

Expected: 3 failures with `AttributeError: 'EpisodeWrite' object has no attribute 'slice_narrative'` (or similar for other fields).

- [ ] **Step 3: Extend `EpisodeWrite` in `backend/src/magi/memory/l2/episode_models.py`**

Add 6 new fields to the dataclass (insert after `privacy_scope: str = "private"`, before `def __post_init__`):

```python
    # Immersive timeline fields (Plan 1 — Plan 2 fills via LLM/scheduler)
    slice_narrative: str = ""
    slice_sensory_detail: str = ""
    magi_standout: bool = False
    standout_score: float = 0.0
    standout_reason: str = ""
    representative_asset_ref: str = ""
```

Extend `__post_init__` after the existing `self.privacy_scope = ...` line:

```python
        self.slice_narrative = _optional_text(self.slice_narrative) or ""
        self.slice_sensory_detail = _optional_text(self.slice_sensory_detail) or ""
        self.magi_standout = bool(self.magi_standout)
        self.standout_score = float(self.standout_score or 0.0)
        self.standout_reason = _optional_text(self.standout_reason) or ""
        self.representative_asset_ref = _optional_text(self.representative_asset_ref) or ""
```

Extend `from_dict` after the existing `privacy_scope=...` entry (before the closing `)`):

```python
            slice_narrative=str(data.get("slice_narrative", "") or ""),
            slice_sensory_detail=str(data.get("slice_sensory_detail", "") or ""),
            magi_standout=bool(data.get("magi_standout", False)),
            standout_score=float(data.get("standout_score", 0.0)),
            standout_reason=str(data.get("standout_reason", "") or ""),
            representative_asset_ref=str(data.get("representative_asset_ref", "") or ""),
```

- [ ] **Step 4: Run the test, expect pass**

```bash
cd /Users/asuka/code/magi/backend && pytest tests/memory/l2/test_episodes_immersive_fields.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/l2/episode_models.py backend/tests/memory/l2/test_episodes_immersive_fields.py
git commit -m "feat(memory/l2): add 6 immersive timeline fields to EpisodeWrite"
```

---

## Task 3: Persist and read the new fields through CRUD + codec

**Files:**
- Modify: `backend/src/magi/memory/l2/episodes/crud.py`
- Modify: `backend/src/magi/memory/l2/episodes/codec.py`
- Test: `backend/tests/memory/l2/test_episodes_immersive_fields.py` (extend)

- [ ] **Step 1: Append a CRUD round-trip test**

Append to `backend/tests/memory/l2/test_episodes_immersive_fields.py`:

```python
@pytest.mark.asyncio
async def test_store_round_trip_immersive_fields(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    eid = "ep-rt-1"
    await store.create_episode(
        episode_id=eid,
        time_start=100.0,
        time_end=200.0,
        slice_narrative="周日下午你在读架构文档。",
        slice_sensory_detail="窗外光线很柔。",
        magi_standout=True,
        standout_score=0.72,
        standout_reason="duration",
        representative_asset_ref="photo-library://x/y.HEIC",
    )

    got = await store.get_episode(episode_id=eid)
    assert got["slice_narrative"] == "周日下午你在读架构文档。"
    assert got["slice_sensory_detail"] == "窗外光线很柔。"
    assert got["magi_standout"] is True
    assert got["standout_score"] == pytest.approx(0.72)
    assert got["standout_reason"] == "duration"
    assert got["representative_asset_ref"] == "photo-library://x/y.HEIC"


@pytest.mark.asyncio
async def test_update_episode_immersive_fields(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    eid = "ep-rt-2"
    await store.create_episode(episode_id=eid, time_start=0.0, time_end=1.0)

    ok = await store.update_episode(
        episode_id=eid,
        magi_standout=True,
        standout_score=0.9,
        slice_narrative="一个新的切片叙事。",
        representative_asset_ref="ref://abc",
    )
    assert ok is True

    got = await store.get_episode(episode_id=eid)
    assert got["magi_standout"] is True
    assert got["standout_score"] == pytest.approx(0.9)
    assert got["slice_narrative"] == "一个新的切片叙事。"
    assert got["representative_asset_ref"] == "ref://abc"
```

- [ ] **Step 2: Run, expect failures**

```bash
cd /Users/asuka/code/magi/backend && pytest tests/memory/l2/test_episodes_immersive_fields.py -v
```

Expected: the 2 new round-trip tests fail (SQL error: no such column, or returned dict missing keys).

- [ ] **Step 3: Extend `create_episode` in `backend/src/magi/memory/l2/episodes/crud.py`**

Add 6 new keyword-only parameters to the signature (before `privacy_scope`):

```python
        slice_narrative: Optional[str] = None,
        slice_sensory_detail: Optional[str] = None,
        magi_standout: bool = False,
        standout_score: float = 0.0,
        standout_reason: Optional[str] = None,
        representative_asset_ref: Optional[str] = None,
```

Update the INSERT column list and the VALUES tuple. Replace the INSERT block with:

```python
            await db.execute(
                """
                INSERT INTO episodes(
                    episode_id, episode_type, status, time_start, time_end,
                    parent_episode_id, label, summary, dominant_mode,
                    primary_entity_ids, primary_place_ids, primary_topic_keys,
                    continuity_signals, formation_method, confidence,
                    source_event_count, privacy_scope,
                    slice_narrative, slice_sensory_detail, magi_standout,
                    standout_score, standout_reason, representative_asset_ref,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    episode_id,
                    episode_type,
                    status,
                    time_start,
                    time_end,
                    parent_episode_id,
                    label,
                    summary,
                    dominant_mode,
                    json.dumps(primary_entity_ids or [], ensure_ascii=False),
                    json.dumps(primary_place_ids or [], ensure_ascii=False),
                    json.dumps(primary_topic_keys or [], ensure_ascii=False),
                    json.dumps(continuity_signals or [], ensure_ascii=False),
                    formation_method,
                    confidence,
                    source_event_count,
                    privacy_scope,
                    slice_narrative,
                    slice_sensory_detail,
                    1 if magi_standout else 0,
                    standout_score,
                    standout_reason,
                    representative_asset_ref,
                    now,
                    now,
                ),
            )
```

- [ ] **Step 4: Extend the `update_episode` `allowed` set**

In the same `crud.py`, locate the `allowed = {...}` set inside `update_episode` (around line 99). Add the 6 field names:

```python
        allowed = {
            "status", "time_start", "time_end", "label", "summary",
            "dominant_mode", "primary_entity_ids", "primary_place_ids",
            "primary_topic_keys", "continuity_signals", "confidence",
            "source_event_count", "parent_episode_id", "user_label",
            "user_note", "user_pinned", "embedding_status",
            "embedding_profile_id", "last_embedded_at", "last_recomputed_at",
            "privacy_scope",
            # Immersive timeline fields (Plan 1)
            "slice_narrative", "slice_sensory_detail", "magi_standout",
            "standout_score", "standout_reason", "representative_asset_ref",
        }
```

Find the `for list_field in (...)` loop just after. Below it (before the SET-clause assembly), add boolean normalization for `magi_standout`:

```python
        if "magi_standout" in updates:
            updates["magi_standout"] = 1 if updates["magi_standout"] else 0
```

- [ ] **Step 5: Extend `_episode_row_to_dict` in `backend/src/magi/memory/l2/episodes/codec.py`**

Add to the returned dict (before the closing `}`):

```python
            "slice_narrative": str(row["slice_narrative"]) if row["slice_narrative"] else "",
            "slice_sensory_detail": str(row["slice_sensory_detail"]) if row["slice_sensory_detail"] else "",
            "magi_standout": bool(row["magi_standout"]),
            "standout_score": float(row["standout_score"]),
            "standout_reason": str(row["standout_reason"]) if row["standout_reason"] else "",
            "representative_asset_ref": str(row["representative_asset_ref"]) if row["representative_asset_ref"] else "",
```

- [ ] **Step 6: Run tests, expect all pass**

```bash
cd /Users/asuka/code/magi/backend && pytest tests/memory/l2/test_episodes_immersive_fields.py tests/memory/l2/test_episodes.py -v
```

Expected: all pass (5+ tests).

- [ ] **Step 7: Commit**

```bash
git add backend/src/magi/memory/l2/episodes/crud.py backend/src/magi/memory/l2/episodes/codec.py backend/tests/memory/l2/test_episodes_immersive_fields.py
git commit -m "feat(memory/l2): persist + read immersive timeline fields on episodes"
```

---

## Task 4: Migration 0004 — extend `summaries` table for diary essence

**Files:**
- Create: `backend/src/magi/db/migrations/memory_shared/versions/0004_l3_summary_essence_prose.py`

Adds two nullable columns to `summaries`: `narrative_style` (text, default `'default'`) and `essence_prose` (text, nullable). These let an L3 reflection carry the new 2nd-person diary essence without disturbing existing summary content.

- [ ] **Step 1: Write the migration file**

```python
"""l3 summary essence prose

Revision ID: 0004_l3_summary_essence_prose
Revises: 0003_l2_episode_immersive_columns
Create Date: 2026-05-19
"""

from __future__ import annotations

from alembic import op

revision = "0004_l3_summary_essence_prose"
down_revision = "0003_l2_episode_immersive_columns"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
ALTER TABLE summaries ADD COLUMN narrative_style TEXT NOT NULL DEFAULT 'default';
ALTER TABLE summaries ADD COLUMN essence_prose TEXT;
CREATE INDEX IF NOT EXISTS idx_summaries_narrative_style
    ON summaries(narrative_style, summary_type, period_start DESC);
"""

DROP_SQL = """
DROP INDEX IF EXISTS idx_summaries_narrative_style;
ALTER TABLE summaries DROP COLUMN essence_prose;
ALTER TABLE summaries DROP COLUMN narrative_style;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
```

- [ ] **Step 2: Commit**

```bash
git add backend/src/magi/db/migrations/memory_shared/versions/0004_l3_summary_essence_prose.py
git commit -m "feat(memory/l3): migration 0004 add essence_prose + narrative_style to summaries"
```

---

## Task 5: L3 summary store read/write for `essence_prose` + `narrative_style`

**Files:**
- Modify: `backend/src/magi/memory/l3/storage/operations.py` (insert + row decode for the new columns)
- Test: `backend/tests/memory/l3/test_summaries_essence_prose.py`

> Locate every `INSERT INTO summaries(...)` and every `SELECT ... FROM summaries` in `operations.py`. Add the two new columns to both. If multiple insert paths exist, update each.

- [ ] **Step 1: Inspect current summary insert/select shape**

```bash
cd /Users/asuka/code/magi/backend && grep -n "INSERT INTO summaries\|SELECT.*FROM summaries\|UPDATE summaries" src/magi/memory/l3/storage/operations.py
```

Note each line for modification in step 3.

- [ ] **Step 2: Write the failing test**

Create `backend/tests/memory/l3/test_summaries_essence_prose.py`:

```python
"""Tests for L3 summary diary essence fields."""

from __future__ import annotations

import time
import uuid

import pytest


@pytest.mark.asyncio
async def test_summary_round_trip_with_essence_prose(tmp_path):
    from magi.memory.l3.summary_store import L3SummaryStore

    store = L3SummaryStore(db_path=str(tmp_path / "memory.db"))
    await store.initialize()

    sid = str(uuid.uuid4())
    now = time.time()
    await store.create_summary(
        summary_id=sid,
        summary_type="temporal",
        summary_category="day",
        period_start=now - 86400,
        period_end=now,
        content="(legacy summary body)",
        source_event_ids=[],
        source_event_count=0,
        narrative_style="diary_2p",
        essence_prose="周日。你大部分时间在 localhost 之间游走，深夜还亮着屏。",
    )

    got = await store.get_summary(summary_id=sid)
    assert got is not None
    assert got["narrative_style"] == "diary_2p"
    assert got["essence_prose"] == "周日。你大部分时间在 localhost 之间游走，深夜还亮着屏。"


@pytest.mark.asyncio
async def test_summary_default_narrative_style_is_default(tmp_path):
    from magi.memory.l3.summary_store import L3SummaryStore

    store = L3SummaryStore(db_path=str(tmp_path / "memory.db"))
    await store.initialize()

    sid = str(uuid.uuid4())
    now = time.time()
    await store.create_summary(
        summary_id=sid,
        summary_type="temporal",
        summary_category="day",
        period_start=now - 86400,
        period_end=now,
        content="legacy",
        source_event_ids=[],
        source_event_count=0,
    )

    got = await store.get_summary(summary_id=sid)
    assert got["narrative_style"] == "default"
    assert got.get("essence_prose") in (None, "")
```

- [ ] **Step 3: Run, expect failure**

```bash
cd /Users/asuka/code/magi/backend && pytest tests/memory/l3/test_summaries_essence_prose.py -v
```

Expected: failures because `create_summary` rejects the new kwargs or returned dict is missing the keys.

- [ ] **Step 4: Update `create_summary` and the row decoder in `operations.py`**

For each `INSERT INTO summaries(...)` found in Step 1:
- Add `narrative_style, essence_prose` to the column list
- Add 2 placeholders to `VALUES (...)`
- Add `narrative_style or "default", essence_prose` to the parameters tuple

For the row→dict decoder (likely named `_summary_row_to_dict` or inline in a SELECT helper), add:

```python
        "narrative_style": str(row["narrative_style"]) if row["narrative_style"] else "default",
        "essence_prose": str(row["essence_prose"]) if row["essence_prose"] else None,
```

For each `create_summary` signature, add two optional kwargs:

```python
        narrative_style: str = "default",
        essence_prose: Optional[str] = None,
```

If `create_summary` lives in a mixin (`L3SummaryPersistenceMixin` per the L3 store survey), edit the mixin source.

- [ ] **Step 5: Run, expect pass**

```bash
cd /Users/asuka/code/magi/backend && pytest tests/memory/l3/test_summaries_essence_prose.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/memory/l3/storage/operations.py backend/tests/memory/l3/test_summaries_essence_prose.py
git commit -m "feat(memory/l3): write + read narrative_style and essence_prose on summaries"
```

---

## Task 6: Migration 0005 — create `daily_mood_aggregate` table

**Files:**
- Create: `backend/src/magi/db/migrations/memory_shared/versions/0005_daily_mood_aggregate.py`

- [ ] **Step 1: Write the migration file**

```python
"""daily mood aggregate

Revision ID: 0005_daily_mood_aggregate
Revises: 0004_l3_summary_essence_prose
Create Date: 2026-05-19
"""

from __future__ import annotations

from alembic import op

revision = "0005_daily_mood_aggregate"
down_revision = "0004_l3_summary_essence_prose"
branch_labels = None
depends_on = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS daily_mood_aggregate (
    day_local_date TEXT PRIMARY KEY,
    dominant_valence TEXT NOT NULL DEFAULT 'neutral',
    volatility_score REAL NOT NULL DEFAULT 0.0,
    state_curve_compact TEXT NOT NULL DEFAULT '[]',
    event_count INTEGER NOT NULL DEFAULT 0,
    computed_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_daily_mood_aggregate_computed
    ON daily_mood_aggregate(computed_at DESC);
"""

DROP_SQL = """
DROP INDEX IF EXISTS idx_daily_mood_aggregate_computed;
DROP TABLE IF EXISTS daily_mood_aggregate;
"""


def upgrade() -> None:
    op.get_bind().connection.executescript(SCHEMA_SQL)


def downgrade() -> None:
    op.get_bind().connection.executescript(DROP_SQL)
```

- [ ] **Step 2: Commit**

```bash
git add backend/src/magi/db/migrations/memory_shared/versions/0005_daily_mood_aggregate.py
git commit -m "feat(memory/l3): migration 0005 create daily_mood_aggregate projection"
```

---

## Task 7: Daily mood aggregate model + store (read API)

**Files:**
- Create: `backend/src/magi/memory/l3/daily_mood/__init__.py`
- Create: `backend/src/magi/memory/l3/daily_mood/models.py`
- Create: `backend/src/magi/memory/l3/daily_mood/store.py`
- Create: `backend/tests/memory/l3/daily_mood/__init__.py`
- Create: `backend/tests/memory/l3/daily_mood/test_store.py`

The store exposes only what Plan 1 needs: `upsert_aggregate`, `get_aggregate(date)`, `list_aggregates(start_date, end_date)`. Computation lives in Plan 2.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/memory/l3/daily_mood/__init__.py`:

```python
```

Create `backend/tests/memory/l3/daily_mood/test_store.py`:

```python
"""Tests for the daily_mood_aggregate store."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_upsert_and_get_aggregate(tmp_path):
    from magi.memory.l3.daily_mood.store import DailyMoodAggregateStore
    from magi.memory.l3.daily_mood.models import DailyMoodAggregate

    store = DailyMoodAggregateStore(db_path=str(tmp_path / "memory.db"))
    await store.initialize()

    agg = DailyMoodAggregate(
        day_local_date="2026-05-17",
        dominant_valence="cool",
        volatility_score=0.62,
        state_curve_compact=[0.1, 0.1, -0.3, -0.3, 0.0, 0.4, 0.4, 0.2],
        event_count=228,
    )
    await store.upsert_aggregate(agg)

    got = await store.get_aggregate(day_local_date="2026-05-17")
    assert got is not None
    assert got.day_local_date == "2026-05-17"
    assert got.dominant_valence == "cool"
    assert got.volatility_score == pytest.approx(0.62)
    assert got.event_count == 228
    assert got.state_curve_compact[0] == pytest.approx(0.1)


@pytest.mark.asyncio
async def test_upsert_overwrites_same_day(tmp_path):
    from magi.memory.l3.daily_mood.store import DailyMoodAggregateStore
    from magi.memory.l3.daily_mood.models import DailyMoodAggregate

    store = DailyMoodAggregateStore(db_path=str(tmp_path / "memory.db"))
    await store.initialize()

    await store.upsert_aggregate(DailyMoodAggregate(
        day_local_date="2026-05-17", dominant_valence="neutral",
        volatility_score=0.0, state_curve_compact=[], event_count=10,
    ))
    await store.upsert_aggregate(DailyMoodAggregate(
        day_local_date="2026-05-17", dominant_valence="warm",
        volatility_score=0.3, state_curve_compact=[0.5], event_count=20,
    ))
    got = await store.get_aggregate(day_local_date="2026-05-17")
    assert got.dominant_valence == "warm"
    assert got.event_count == 20


@pytest.mark.asyncio
async def test_list_aggregates_in_range(tmp_path):
    from magi.memory.l3.daily_mood.store import DailyMoodAggregateStore
    from magi.memory.l3.daily_mood.models import DailyMoodAggregate

    store = DailyMoodAggregateStore(db_path=str(tmp_path / "memory.db"))
    await store.initialize()

    for d in ("2026-05-10", "2026-05-12", "2026-05-15", "2026-05-20"):
        await store.upsert_aggregate(DailyMoodAggregate(
            day_local_date=d, dominant_valence="neutral",
            volatility_score=0.0, state_curve_compact=[], event_count=1,
        ))

    rows = await store.list_aggregates(start_date="2026-05-11", end_date="2026-05-17")
    dates = sorted(r.day_local_date for r in rows)
    assert dates == ["2026-05-12", "2026-05-15"]
```

- [ ] **Step 2: Run, expect failure (import errors)**

```bash
cd /Users/asuka/code/magi/backend && pytest tests/memory/l3/daily_mood/test_store.py -v
```

Expected: `ModuleNotFoundError: No module named 'magi.memory.l3.daily_mood'`.

- [ ] **Step 3: Create the model file**

Create `backend/src/magi/memory/l3/daily_mood/__init__.py`:

```python
"""Daily mood aggregate projection (read model for sidebar mood calendar)."""
```

Create `backend/src/magi/memory/l3/daily_mood/models.py`:

```python
"""Models for the daily_mood_aggregate projection."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class DailyMoodAggregate:
    """One row per local date — the sidebar mood calendar reads this directly."""

    day_local_date: str  # YYYY-MM-DD
    dominant_valence: str = "neutral"  # warm | bright | neutral | cool | tense
    volatility_score: float = 0.0  # 0.0 flat – 1.0 high swings
    state_curve_compact: list[float] = field(default_factory=list)
    event_count: int = 0
    computed_at: float = 0.0

    def __post_init__(self) -> None:
        date = (self.day_local_date or "").strip()
        if not date:
            raise ValueError("day_local_date must not be blank")
        self.day_local_date = date
        self.dominant_valence = (self.dominant_valence or "neutral").strip() or "neutral"
        self.volatility_score = max(0.0, min(1.0, float(self.volatility_score or 0.0)))
        self.state_curve_compact = [float(x) for x in (self.state_curve_compact or [])]
        self.event_count = int(self.event_count or 0)
        self.computed_at = float(self.computed_at or 0.0)
```

- [ ] **Step 4: Create the store file**

Create `backend/src/magi/memory/l3/daily_mood/store.py`:

```python
"""Persistence for daily_mood_aggregate."""

from __future__ import annotations

import json
import time
from typing import List, Optional

import aiosqlite

from ....core.sqlite import sqlite_connection_async
from .models import DailyMoodAggregate


class DailyMoodAggregateStore:
    """Tiny store for the sidebar mood calendar.

    Schema is created by migration 0005_daily_mood_aggregate. This store
    does not own DDL; it only reads and upserts rows.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    async def initialize(self) -> None:
        """Best-effort: ensure the table exists for tests that bypass migrations."""
        async with sqlite_connection_async(self.db_path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS daily_mood_aggregate (
                    day_local_date TEXT PRIMARY KEY,
                    dominant_valence TEXT NOT NULL DEFAULT 'neutral',
                    volatility_score REAL NOT NULL DEFAULT 0.0,
                    state_curve_compact TEXT NOT NULL DEFAULT '[]',
                    event_count INTEGER NOT NULL DEFAULT 0,
                    computed_at REAL NOT NULL
                );
                """
            )
            await db.commit()

    async def upsert_aggregate(self, aggregate: DailyMoodAggregate) -> None:
        computed_at = aggregate.computed_at or time.time()
        async with sqlite_connection_async(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO daily_mood_aggregate(
                    day_local_date, dominant_valence, volatility_score,
                    state_curve_compact, event_count, computed_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(day_local_date) DO UPDATE SET
                    dominant_valence = excluded.dominant_valence,
                    volatility_score = excluded.volatility_score,
                    state_curve_compact = excluded.state_curve_compact,
                    event_count = excluded.event_count,
                    computed_at = excluded.computed_at
                """,
                (
                    aggregate.day_local_date,
                    aggregate.dominant_valence,
                    aggregate.volatility_score,
                    json.dumps(aggregate.state_curve_compact, ensure_ascii=False),
                    aggregate.event_count,
                    computed_at,
                ),
            )
            await db.commit()

    async def get_aggregate(self, *, day_local_date: str) -> Optional[DailyMoodAggregate]:
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM daily_mood_aggregate WHERE day_local_date = ?",
                (day_local_date,),
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_aggregate(row)

    async def list_aggregates(
        self,
        *,
        start_date: str,
        end_date: str,
    ) -> List[DailyMoodAggregate]:
        """Inclusive on both ends. Dates compared as ISO strings (YYYY-MM-DD)."""
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM daily_mood_aggregate
                WHERE day_local_date >= ? AND day_local_date <= ?
                ORDER BY day_local_date ASC
                """,
                (start_date, end_date),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_aggregate(r) for r in rows]

    @staticmethod
    def _row_to_aggregate(row: aiosqlite.Row) -> DailyMoodAggregate:
        return DailyMoodAggregate(
            day_local_date=str(row["day_local_date"]),
            dominant_valence=str(row["dominant_valence"]),
            volatility_score=float(row["volatility_score"]),
            state_curve_compact=json.loads(row["state_curve_compact"] or "[]"),
            event_count=int(row["event_count"]),
            computed_at=float(row["computed_at"]),
        )
```

- [ ] **Step 5: Run, expect pass**

```bash
cd /Users/asuka/code/magi/backend && pytest tests/memory/l3/daily_mood/test_store.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/memory/l3/daily_mood/ backend/tests/memory/l3/daily_mood/
git commit -m "feat(memory/l3): DailyMoodAggregate store + model"
```

---

## Task 8: Media layer skeleton — `MediaSource` protocol + `MediaSourceRegistry`

**Files:**
- Create: `backend/src/magi/media/__init__.py`
- Create: `backend/src/magi/media/source_registry.py`
- Create: `backend/tests/media/__init__.py`
- Create: `backend/tests/media/test_source_registry.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/media/__init__.py`:

```python
```

Create `backend/tests/media/test_source_registry.py`:

```python
"""Tests for the MediaSourceRegistry."""

from __future__ import annotations

from typing import List

import pytest


class _StubSource:
    """Minimal stand-in matching the MediaSource protocol."""

    def __init__(self, source_id: str, assets: List[dict]) -> None:
        self.source_id = source_id
        self._assets = assets

    async def list_assets(self, *, start: float, end: float) -> List[dict]:
        return [a for a in self._assets if start <= a["timestamp"] <= end]


def test_register_and_list_sources():
    from magi.media.source_registry import MediaSourceRegistry

    reg = MediaSourceRegistry()
    a = _StubSource("photo-library", [])
    b = _StubSource("chat-attachments", [])
    reg.register(a)
    reg.register(b)

    ids = sorted(s.source_id for s in reg.iter_sources())
    assert ids == ["chat-attachments", "photo-library"]


def test_register_duplicate_raises():
    from magi.media.source_registry import MediaSourceRegistry

    reg = MediaSourceRegistry()
    reg.register(_StubSource("photo-library", []))
    with pytest.raises(ValueError, match="photo-library"):
        reg.register(_StubSource("photo-library", []))


def test_get_source_by_id():
    from magi.media.source_registry import MediaSourceRegistry

    reg = MediaSourceRegistry()
    src = _StubSource("photo-library", [])
    reg.register(src)
    assert reg.get("photo-library") is src
    assert reg.get("missing") is None


@pytest.mark.asyncio
async def test_collect_assets_across_sources():
    from magi.media.source_registry import MediaSourceRegistry

    reg = MediaSourceRegistry()
    reg.register(_StubSource("photo-library", [
        {"ref": "p://a", "timestamp": 100.0},
        {"ref": "p://b", "timestamp": 500.0},
    ]))
    reg.register(_StubSource("chat-attachments", [
        {"ref": "c://x", "timestamp": 200.0},
    ]))

    items = await reg.collect_assets(start=50.0, end=300.0)
    refs = sorted(i["ref"] for i in items)
    assert refs == ["c://x", "p://a"]
```

- [ ] **Step 2: Run, expect failure (module missing)**

```bash
cd /Users/asuka/code/magi/backend && pytest tests/media/test_source_registry.py -v
```

Expected: `ModuleNotFoundError: No module named 'magi.media'`.

- [ ] **Step 3: Create the media package**

Create `backend/src/magi/media/__init__.py`:

```python
"""Media layer: source registry, period selector, asset resolver.

This package lifts media-asset handling out of any single plugin so that
photo-library, chat attachments, and future sources (screen capture, etc.)
contribute through one registration path. See:
    docs/superpowers/specs/2026-05-19-timeline-immersive-redesign-design.md
    docs/unified-asset-resolver-architecture.md (forward-compatible)
"""

from .source_registry import MediaSource, MediaSourceRegistry
from .selector import MediaSelector

__all__ = ["MediaSource", "MediaSourceRegistry", "MediaSelector"]
```

Create `backend/src/magi/media/source_registry.py`:

```python
"""Registry of media sources (plugins/domains that contribute reusable assets)."""

from __future__ import annotations

from typing import Iterable, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class MediaSource(Protocol):
    """A contributor of time-anchored media assets.

    Implementations describe what kind of source they are (`source_id`,
    e.g. "photo-library", "chat-attachments") and how to enumerate assets
    within a time window. Each asset is a dict that MUST carry at least
    ``ref`` (a stable asset_ref string) and ``timestamp`` (unix seconds).
    Additional metadata (mime_type, dimensions, location, people, etc.) is
    optional and consumed by the selector.
    """

    source_id: str

    async def list_assets(self, *, start: float, end: float) -> List[dict]:
        ...


class MediaSourceRegistry:
    """In-memory registry of media sources, populated at bootstrap.

    The registry is intentionally tiny in Plan 1: registration and
    fan-out enumeration. Selection logic lives in MediaSelector.
    """

    def __init__(self) -> None:
        self._sources: dict[str, MediaSource] = {}

    def register(self, source: MediaSource) -> None:
        source_id = getattr(source, "source_id", "") or ""
        if not source_id:
            raise ValueError("MediaSource.source_id must be a non-empty string")
        if source_id in self._sources:
            raise ValueError(f"MediaSource already registered: {source_id}")
        self._sources[source_id] = source

    def get(self, source_id: str) -> Optional[MediaSource]:
        return self._sources.get(source_id)

    def iter_sources(self) -> Iterable[MediaSource]:
        return list(self._sources.values())

    async def collect_assets(self, *, start: float, end: float) -> List[dict]:
        """Fan out to every registered source and concatenate their assets."""
        out: list[dict] = []
        for src in self._sources.values():
            try:
                items = await src.list_assets(start=start, end=end)
            except Exception:
                # Plan 2 will add structured error reporting; for now skip the source.
                continue
            out.extend(items or [])
        return out
```

- [ ] **Step 4: Run, expect pass**

```bash
cd /Users/asuka/code/magi/backend && pytest tests/media/test_source_registry.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/media/__init__.py backend/src/magi/media/source_registry.py backend/tests/media/__init__.py backend/tests/media/test_source_registry.py
git commit -m "feat(media): MediaSource protocol + MediaSourceRegistry skeleton"
```

---

## Task 9: `MediaSelector` skeleton — `pick_representative`

**Files:**
- Create: `backend/src/magi/media/selector.py`
- Create: `backend/tests/media/test_selector.py`

Plan 1 ships the selector contract with a simple default policy (first asset by source-priority order if any). Plan 2 will replace the policy with a richer heuristic.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/media/test_selector.py`:

```python
"""Tests for MediaSelector — period → representative asset_ref."""

from __future__ import annotations

from typing import List

import pytest


class _StubSource:
    def __init__(self, source_id: str, assets: List[dict]) -> None:
        self.source_id = source_id
        self._assets = assets

    async def list_assets(self, *, start: float, end: float) -> List[dict]:
        return [a for a in self._assets if start <= a["timestamp"] <= end]


@pytest.mark.asyncio
async def test_pick_representative_returns_none_when_no_sources():
    from magi.media.selector import MediaSelector
    from magi.media.source_registry import MediaSourceRegistry

    sel = MediaSelector(registry=MediaSourceRegistry())
    out = await sel.pick_representative(start=0.0, end=100.0, hint="hero")
    assert out is None


@pytest.mark.asyncio
async def test_pick_representative_returns_none_when_no_assets_in_window():
    from magi.media.selector import MediaSelector
    from magi.media.source_registry import MediaSourceRegistry

    reg = MediaSourceRegistry()
    reg.register(_StubSource("photo-library", [
        {"ref": "p://a", "timestamp": 50.0},
    ]))
    sel = MediaSelector(registry=reg)
    out = await sel.pick_representative(start=1000.0, end=2000.0, hint="hero")
    assert out is None


@pytest.mark.asyncio
async def test_pick_representative_picks_first_from_source_priority():
    from magi.media.selector import MediaSelector
    from magi.media.source_registry import MediaSourceRegistry

    reg = MediaSourceRegistry()
    reg.register(_StubSource("photo-library", [
        {"ref": "p://earliest", "timestamp": 100.0},
        {"ref": "p://later", "timestamp": 200.0},
    ]))
    reg.register(_StubSource("chat-attachments", [
        {"ref": "c://chat", "timestamp": 150.0},
    ]))
    sel = MediaSelector(
        registry=reg,
        source_priority=("photo-library", "chat-attachments"),
    )
    ref = await sel.pick_representative(start=0.0, end=300.0, hint="hero")
    # Default policy: walk source_priority order; within first source with
    # any assets, take the earliest. Plan 2 swaps in a richer scorer.
    assert ref == "p://earliest"


@pytest.mark.asyncio
async def test_pick_representative_falls_through_priority_when_first_empty():
    from magi.media.selector import MediaSelector
    from magi.media.source_registry import MediaSourceRegistry

    reg = MediaSourceRegistry()
    reg.register(_StubSource("photo-library", []))
    reg.register(_StubSource("chat-attachments", [
        {"ref": "c://x", "timestamp": 50.0},
    ]))
    sel = MediaSelector(
        registry=reg,
        source_priority=("photo-library", "chat-attachments"),
    )
    ref = await sel.pick_representative(start=0.0, end=100.0, hint="hero")
    assert ref == "c://x"
```

- [ ] **Step 2: Run, expect failure (module missing)**

```bash
cd /Users/asuka/code/magi/backend && pytest tests/media/test_selector.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create the selector**

Create `backend/src/magi/media/selector.py`:

```python
"""Period-anchored representative asset selection."""

from __future__ import annotations

from typing import Optional, Sequence

from .source_registry import MediaSourceRegistry


class MediaSelector:
    """Given a time window, return a representative asset_ref or None.

    Plan 1 ships a simple priority-then-earliest policy. Plan 2 swaps the
    policy with a richer scorer (people-bearing > outdoor > time-of-day fit,
    plus existing user-pin signals).
    """

    def __init__(
        self,
        *,
        registry: MediaSourceRegistry,
        source_priority: Sequence[str] = ("photo-library", "chat-attachments"),
    ) -> None:
        self._registry = registry
        self._source_priority = tuple(source_priority)

    async def pick_representative(
        self,
        *,
        start: float,
        end: float,
        hint: str = "hero",
    ) -> Optional[str]:
        """Return a single asset_ref representing the window, or None.

        ``hint`` is reserved for future use (e.g., "thumbnail", "moodboard");
        the Plan 1 policy ignores it.
        """
        # Walk priority order, take earliest from the first source that has any.
        for source_id in self._source_priority:
            src = self._registry.get(source_id)
            if src is None:
                continue
            try:
                assets = await src.list_assets(start=start, end=end)
            except Exception:
                continue
            if not assets:
                continue
            assets_sorted = sorted(assets, key=lambda a: a.get("timestamp", 0.0))
            ref = (assets_sorted[0] or {}).get("ref")
            if ref:
                return str(ref)
        return None
```

- [ ] **Step 4: Run, expect pass**

```bash
cd /Users/asuka/code/magi/backend && pytest tests/media/test_selector.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/media/selector.py backend/tests/media/test_selector.py
git commit -m "feat(media): MediaSelector with priority-then-earliest default policy"
```

---

## Task 10: `AssetResolver` placeholder (forward-compatible)

**Files:**
- Create: `backend/src/magi/media/resolver.py`

A minimal stub so the package shape matches the spec. Real implementation arrives when `docs/unified-asset-resolver-architecture.md` moves from Proposed to implemented. No tests — it's a contract placeholder.

- [ ] **Step 1: Create the resolver**

Create `backend/src/magi/media/resolver.py`:

```python
"""Asset reference resolver.

Placeholder for the `asset_resolve` tool described in
`docs/unified-asset-resolver-architecture.md` (status: Proposed). The
class shape and interface stub here ensure callers can wire imports
without waiting for that proposal to land; raising NotImplementedError
keeps surprises out of production code paths.
"""

from __future__ import annotations

from typing import Any, Mapping


class AssetResolver:
    """Resolve an asset_ref into source-specific evidence.

    Resolution is delegated to source-owned hooks once the unified-asset
    proposal lands. For Plan 1, callers should treat any reference as
    opaque: store it, surface it as an identifier, never try to resolve.
    """

    def __init__(self) -> None:
        self._unimplemented = True

    async def resolve(self, *, asset_ref: str, scope: Mapping[str, Any] | None = None) -> Any:
        raise NotImplementedError(
            "AssetResolver is a forward-compatible placeholder; "
            "implement when unified-asset-resolver lands."
        )
```

- [ ] **Step 2: Update package exports**

Edit `backend/src/magi/media/__init__.py` — add `AssetResolver` to imports + `__all__`:

```python
from .source_registry import MediaSource, MediaSourceRegistry
from .selector import MediaSelector
from .resolver import AssetResolver

__all__ = ["MediaSource", "MediaSourceRegistry", "MediaSelector", "AssetResolver"]
```

- [ ] **Step 3: Verify imports**

```bash
cd /Users/asuka/code/magi/backend && python -c "from magi.media import AssetResolver; r = AssetResolver(); print(type(r).__name__)"
```

Expected: `AssetResolver`.

- [ ] **Step 4: Commit**

```bash
git add backend/src/magi/media/resolver.py backend/src/magi/media/__init__.py
git commit -m "feat(media): AssetResolver placeholder for unified-asset proposal"
```

---

## Task 11: Endpoint `GET /timeline/standout` (Magi-curated + user-pinned episodes)

**Files:**
- Modify: `backend/src/magi/api/routers/timeline.py` (add handler + Pydantic models if used elsewhere in the file)
- Test: `backend/tests/api/test_timeline_standout.py`

Query the L2 episode store for episodes WHERE `magi_standout = 1 OR user_pinned = 1`, ordered by `time_start DESC`, optionally filtered by month. Plan 1 returns user_pinned episodes (and any magi_standout that already exists, though there won't be any until Plan 2).

> **Architectural note:** the existing `/viewport` and `/context` handlers obtain services through `get_timeline_service()` → `TimelineService(unified_memory)` (see [timeline.py:16-26](../../../backend/src/magi/api/routers/timeline.py)). To stay consistent, the new endpoints add methods to `TimelineService` and the routers stay thin wrappers. The L2 store is reached as `unified.l2_pipeline._cognition_store` (per `backend/src/magi/memory/l2/maintenance_schedule.py:54`).

- [ ] **Step 1: Add a `list_standout_episodes` helper to the L2 episode CRUD**

In `backend/src/magi/memory/l2/episodes/crud.py`, add this method to `L2EpisodeCrudMixin` (just before `__all__` at the end, or after `update_episode`):

```python
    async def list_standout_episodes(
        self,
        *,
        period_start: Optional[float] = None,
        period_end: Optional[float] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List episodes that are either magi-curated or user-pinned.

        Time bounds are inclusive on both ends. If both are None, returns
        the most-recent ``limit`` standouts regardless of date.
        """
        await self.initialize()
        clauses: list[str] = ["(magi_standout = 1 OR user_pinned = 1)"]
        params: list[Any] = []
        if period_start is not None:
            clauses.append("time_start >= ?")
            params.append(period_start)
        if period_end is not None:
            clauses.append("time_start <= ?")
            params.append(period_end)
        params.append(int(max(1, limit)))
        sql = (
            "SELECT * FROM episodes WHERE "
            + " AND ".join(clauses)
            + " ORDER BY time_start DESC LIMIT ?"
        )
        async with sqlite_connection_async(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, params) as cursor:
                rows = await cursor.fetchall()
        return [self._episode_row_to_dict(r) for r in rows]
```

- [ ] **Step 2: Test the helper**

Append to `backend/tests/memory/l2/test_episodes_immersive_fields.py`:

```python
@pytest.mark.asyncio
async def test_list_standout_episodes_returns_user_pinned_and_magi(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    await store.create_episode(episode_id="ep-plain", time_start=100.0, time_end=200.0)
    await store.create_episode(episode_id="ep-pinned", time_start=300.0, time_end=400.0)
    await store.update_episode(episode_id="ep-pinned", user_pinned=True)
    await store.create_episode(
        episode_id="ep-magi", time_start=500.0, time_end=600.0,
        magi_standout=True, standout_score=0.8,
    )

    rows = await store.list_standout_episodes()
    ids = [r["episode_id"] for r in rows]
    assert "ep-plain" not in ids
    assert set(ids) == {"ep-pinned", "ep-magi"}
    # DESC by time_start
    assert rows[0]["episode_id"] == "ep-magi"


@pytest.mark.asyncio
async def test_list_standout_episodes_respects_time_window(tmp_path):
    from magi.memory.l2.store import L2CognitionStore

    store = L2CognitionStore(db_path=str(tmp_path / "l2.db"))
    await store.initialize()

    await store.create_episode(episode_id="ep-a", time_start=100.0, time_end=200.0)
    await store.update_episode(episode_id="ep-a", user_pinned=True)
    await store.create_episode(episode_id="ep-b", time_start=500.0, time_end=600.0)
    await store.update_episode(episode_id="ep-b", user_pinned=True)

    rows = await store.list_standout_episodes(period_start=400.0, period_end=700.0)
    assert [r["episode_id"] for r in rows] == ["ep-b"]
```

Run:

```bash
cd /Users/asuka/code/magi/backend && pytest tests/memory/l2/test_episodes_immersive_fields.py -v -k standout
```

Expected: 2 passed.

- [ ] **Step 3: Write the failing endpoint test**

Create `backend/tests/api/test_timeline_standout.py`:

```python
"""Tests for GET /api/timeline/standout."""

from __future__ import annotations

import pytest

from magi.timeline.service import TimelineService


@pytest.mark.asyncio
async def test_service_list_standout_returns_empty_when_no_episodes(unified_memory_for_tests):
    service = TimelineService(unified_memory_for_tests)
    out = await service.list_standout(period_start=None, period_end=None, limit=10)
    assert out == []


@pytest.mark.asyncio
async def test_service_list_standout_includes_user_pinned(unified_memory_for_tests, l2_store_for_tests):
    await l2_store_for_tests.create_episode(
        episode_id="ep-x", time_start=1715990400.0, time_end=1715990400.0 + 3600,
    )
    await l2_store_for_tests.update_episode(
        episode_id="ep-x", user_pinned=True, label="跟 Z 在文渊喝咖啡",
    )
    service = TimelineService(unified_memory_for_tests)

    out = await service.list_standout(period_start=None, period_end=None, limit=10)
    assert len(out) == 1
    item = out[0]
    assert item["episode_id"] == "ep-x"
    assert item["source"] == "user"
    assert item["title"] == "跟 Z 在文渊喝咖啡"
    assert item["date"] == "2024-05-18"
```

> If the `unified_memory_for_tests` / `l2_store_for_tests` fixtures do not yet exist in `backend/tests/api/conftest.py`, add them — they should construct an in-memory `L2CognitionStore` against `tmp_path`, then return a small fake `unified_memory` object whose `l2_pipeline._cognition_store` attribute points to it. Reuse any existing memory-test fixture if one is already exported.

- [ ] **Step 4: Run, expect failure (`AttributeError: 'TimelineService' object has no attribute 'list_standout'`)**

```bash
cd /Users/asuka/code/magi/backend && pytest tests/api/test_timeline_standout.py -v
```

- [ ] **Step 5: Add `list_standout` to `TimelineService`**

In `backend/src/magi/timeline/service.py`, add (next to `get_viewport`):

```python
    async def list_standout(
        self,
        *,
        period_start: Optional[float],
        period_end: Optional[float],
        limit: int = 50,
    ) -> list[dict]:
        """List standout episodes — Magi-curated + user-pinned — for the sidebar.

        Returns serializable dicts shaped for the GET /timeline/standout payload.
        """
        from datetime import datetime, timezone

        pipeline = getattr(self._unified_memory, "l2_pipeline", None)
        store = getattr(pipeline, "_cognition_store", None) if pipeline else None
        if store is None:
            return []

        rows = await store.list_standout_episodes(
            period_start=period_start, period_end=period_end, limit=limit,
        )
        items: list[dict] = []
        for r in rows:
            ts = float(r.get("time_start") or 0.0)
            items.append({
                "episode_id": r["episode_id"],
                "scale": "day",
                "start": ts,
                "end": float(r.get("time_end") or ts),
                "title": r.get("user_label") or r.get("label") or "",
                "date": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d"),
                "source": "user" if r.get("user_pinned") else "magi",
                "score": float(r.get("standout_score") or 0.0),
            })
        return items
```

Adjust the `self._unified_memory` attribute name if `TimelineService` uses a different private name; check the existing `__init__` of that class.

- [ ] **Step 6: Add the route handler — thin wrapper around the service method**

In `backend/src/magi/api/routers/timeline.py`, add:

```python
@timeline_router.get("/standout")
async def get_standout_endpoint(
    month: Optional[str] = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    limit: int = Query(default=50, ge=1, le=200),
):
    from datetime import datetime, timezone

    period_start = period_end = None
    if month:
        year, mo = (int(p) for p in month.split("-", 1))
        start_dt = datetime(year, mo, 1, tzinfo=timezone.utc)
        end_dt = (
            datetime(year + 1, 1, 1, tzinfo=timezone.utc)
            if mo == 12
            else datetime(year, mo + 1, 1, tzinfo=timezone.utc)
        )
        period_start = start_dt.timestamp()
        period_end = end_dt.timestamp()

    service = get_timeline_service()
    items = await service.list_standout(
        period_start=period_start, period_end=period_end, limit=limit,
    )
    return {"month": month, "items": items}
```

- [ ] **Step 7: Register `/standout` as a public method**

Edit `backend/src/magi/api/routes.py`, find the `"timeline"` block in `_PUBLIC_ROUTE_METHODS` (around line 85), add the new path:

```python
    "timeline": {
        "/viewport": {"GET"},
        "/context/{anchor_id}": {"GET"},
        "/standout": {"GET"},
    },
```

- [ ] **Step 8: Run, expect pass**

```bash
cd /Users/asuka/code/magi/backend && pytest tests/api/test_timeline_standout.py -v
```

Expected: 2 passed.

- [ ] **Step 9: Commit**

```bash
git add backend/src/magi/memory/l2/episodes/crud.py backend/src/magi/timeline/service.py backend/src/magi/api/routers/timeline.py backend/src/magi/api/routes.py backend/tests/memory/l2/test_episodes_immersive_fields.py backend/tests/api/test_timeline_standout.py
git commit -m "feat(api/timeline): GET /standout for sidebar 值得回来的"
```

---

## Task 12: Endpoint `GET /timeline/mood-calendar`

**Files:**
- Modify: `backend/src/magi/timeline/service.py` (add `list_mood_calendar`)
- Modify: `backend/src/magi/api/routers/timeline.py` (add handler)
- Modify: `backend/src/magi/api/routes.py`
- Test: `backend/tests/api/test_timeline_mood_calendar.py`

Returns one row per day in the month from `daily_mood_aggregate`. Days with no row are omitted (the frontend renders empty cells locally).

> **Pattern note (same as Task 11):** add the method to `TimelineService` and keep the router as a thin wrapper. The `DailyMoodAggregateStore` is constructed against the same memory database path the L2 cognition store uses; reach it through the unified-memory facade.

- [ ] **Step 1: Add `daily_mood_store` accessor to the unified-memory facade (if not already present)**

Investigate whether `unified_memory` already exposes a path to `memory.db`:

```bash
cd /Users/asuka/code/magi/backend && grep -n "memory_db_path\|memory\.db\|memory_db\b" src/magi/memory/provider.py src/magi/memory/store_lifecycle.py 2>/dev/null | head -20
```

If `unified_memory.memory_db_path` (or equivalent) exists, use it. If not, the simplest addition is a property on `UnifiedMemoryStore` that returns the same db_path used to construct `_cognition_store`. Add it next to where `l2_pipeline` is exposed. Do not invent a separate path resolver.

- [ ] **Step 2: Write the failing test**

Create `backend/tests/api/test_timeline_mood_calendar.py`:

```python
"""Tests for the mood-calendar service method."""

from __future__ import annotations

import pytest

from magi.timeline.service import TimelineService
from magi.memory.l3.daily_mood.models import DailyMoodAggregate


@pytest.mark.asyncio
async def test_list_mood_calendar_empty_month(unified_memory_for_tests):
    service = TimelineService(unified_memory_for_tests)
    out = await service.list_mood_calendar(month="2026-05")
    assert out == {"month": "2026-05", "days": []}


@pytest.mark.asyncio
async def test_list_mood_calendar_returns_days_in_month(
    unified_memory_for_tests, daily_mood_store_for_tests,
):
    await daily_mood_store_for_tests.upsert_aggregate(DailyMoodAggregate(
        day_local_date="2026-05-10", dominant_valence="warm",
        volatility_score=0.2, state_curve_compact=[0.4], event_count=42,
    ))
    await daily_mood_store_for_tests.upsert_aggregate(DailyMoodAggregate(
        day_local_date="2026-05-17", dominant_valence="cool",
        volatility_score=0.6, state_curve_compact=[-0.3, 0.2], event_count=228,
    ))
    # Out of month — must not appear
    await daily_mood_store_for_tests.upsert_aggregate(DailyMoodAggregate(
        day_local_date="2026-04-30", dominant_valence="bright",
        volatility_score=0.1, state_curve_compact=[0.5], event_count=10,
    ))

    service = TimelineService(unified_memory_for_tests)
    out = await service.list_mood_calendar(month="2026-05")
    dates = sorted(d["date"] for d in out["days"])
    assert dates == ["2026-05-10", "2026-05-17"]

    day17 = next(d for d in out["days"] if d["date"] == "2026-05-17")
    assert day17["dominant_valence"] == "cool"
    assert day17["volatility"] == pytest.approx(0.6)
    assert day17["event_count"] == 228
    assert day17["sparkline"] == [-0.3, 0.2]


@pytest.mark.asyncio
async def test_list_mood_calendar_rejects_invalid_month(unified_memory_for_tests):
    service = TimelineService(unified_memory_for_tests)
    out = await service.list_mood_calendar(month="not-a-month")
    assert out == {"month": "not-a-month", "days": [], "error": "invalid_month"}
```

> The `daily_mood_store_for_tests` fixture should build a `DailyMoodAggregateStore` against the same `tmp_path / "memory.db"` that `unified_memory_for_tests` uses, so writes from the fixture are visible to the service's reads. Add it to `backend/tests/api/conftest.py` next to the Task 11 fixtures.

- [ ] **Step 3: Run, expect failure**

```bash
cd /Users/asuka/code/magi/backend && pytest tests/api/test_timeline_mood_calendar.py -v
```

Expected: `AttributeError: 'TimelineService' object has no attribute 'list_mood_calendar'`.

- [ ] **Step 4: Add `list_mood_calendar` to `TimelineService`**

In `backend/src/magi/timeline/service.py`:

```python
    async def list_mood_calendar(self, *, month: str) -> dict:
        """Sidebar mood calendar payload for a YYYY-MM month."""
        from calendar import monthrange
        from magi.memory.l3.daily_mood.store import DailyMoodAggregateStore

        try:
            year, mo = (int(p) for p in month.split("-", 1))
            last_day = monthrange(year, mo)[1]
        except (ValueError, OverflowError):
            return {"month": month, "days": [], "error": "invalid_month"}

        db_path = getattr(self._unified_memory, "memory_db_path", None)
        if db_path is None:
            return {"month": month, "days": []}

        store = DailyMoodAggregateStore(db_path=str(db_path))
        start_date = f"{year:04d}-{mo:02d}-01"
        end_date = f"{year:04d}-{mo:02d}-{last_day:02d}"
        rows = await store.list_aggregates(start_date=start_date, end_date=end_date)

        return {
            "month": month,
            "days": [
                {
                    "date": r.day_local_date,
                    "dominant_valence": r.dominant_valence,
                    "volatility": r.volatility_score,
                    "event_count": r.event_count,
                    "sparkline": r.state_curve_compact,
                }
                for r in rows
            ],
        }
```

If `unified_memory` does not expose `memory_db_path` after Step 1, surface the constructor argument the L2 pipeline already uses — do not hardcode a path.

- [ ] **Step 5: Add the route handler**

In `backend/src/magi/api/routers/timeline.py`:

```python
@timeline_router.get("/mood-calendar")
async def get_mood_calendar_endpoint(
    month: str = Query(pattern=r"^\d{4}-\d{2}$"),
):
    service = get_timeline_service()
    return await service.list_mood_calendar(month=month)
```

- [ ] **Step 6: Register `/mood-calendar` as a public method**

In `backend/src/magi/api/routes.py`, extend the `timeline` block:

```python
    "timeline": {
        "/viewport": {"GET"},
        "/context/{anchor_id}": {"GET"},
        "/standout": {"GET"},
        "/mood-calendar": {"GET"},
    },
```

- [ ] **Step 7: Run, expect pass**

```bash
cd /Users/asuka/code/magi/backend && pytest tests/api/test_timeline_mood_calendar.py -v
```

Expected: 3 passed.

- [ ] **Step 8: Commit**

```bash
git add backend/src/magi/timeline/service.py backend/src/magi/api/routers/timeline.py backend/src/magi/api/routes.py backend/tests/api/test_timeline_mood_calendar.py
# Include the unified-memory accessor change from Step 1 if it touched a file:
git add backend/src/magi/memory/provider.py backend/src/magi/memory/store_lifecycle.py 2>/dev/null
git commit -m "feat(api/timeline): GET /mood-calendar reading daily_mood_aggregate"
```

---

## Task 13: Full backend test sweep + contract validation

**Files:** none modified — validation only.

- [ ] **Step 1: Run the full memory + media + timeline-api test suites**

```bash
cd /Users/asuka/code/magi/backend && pytest tests/memory/l2 tests/memory/l3 tests/media tests/api/test_timeline_standout.py tests/api/test_timeline_mood_calendar.py -v
```

Expected: all green. If any pre-existing test broke because of an INSERT column-list mismatch, fix it (likely by passing default values for the new columns in test fixtures).

- [ ] **Step 2: Run the API contract checker**

```bash
cd /Users/asuka/code/magi && python scripts/check-api-contract.py
```

Expected: no errors. The `/api/timeline` prefix is already registered as `python-ipc` in `contracts/api/gateway_routes.json`, so the new sub-routes inherit the proxy ownership without further changes.

- [ ] **Step 3: Run the SQLite ownership checker**

```bash
cd /Users/asuka/code/magi && python scripts/check-sqlite-ownership.py
```

Expected: no errors. All new schema is owned by Python; no Rust gateway writes are introduced.

- [ ] **Step 4: Run mypy (or whatever the repo's typecheck command is) on touched files**

```bash
cd /Users/asuka/code/magi/backend && python -m mypy src/magi/memory/l2/episode_models.py src/magi/memory/l2/episodes/crud.py src/magi/memory/l2/episodes/codec.py src/magi/memory/l3/daily_mood src/magi/media src/magi/api/routers/timeline.py 2>&1 | tail -20
```

If `mypy` is not installed or the repo uses a different typechecker (e.g., `pyright`), substitute. If type errors surface, fix them inline.

- [ ] **Step 5: Final commit if any fixes were applied**

```bash
git status
# If fixes were applied:
git add -A && git commit -m "fix(timeline): typecheck/contract fixes after Plan 1 sweep"
```

---

## Acceptance criteria for Plan 1

- All schema migrations apply cleanly to a fresh and an existing memory.db.
- `EpisodeWrite` supports the 6 new immersive fields; round-trip through `create_episode` / `update_episode` / `get_episode` is lossless.
- `summaries` table accepts and returns `narrative_style` + `essence_prose`.
- `DailyMoodAggregateStore` upserts and reads `DailyMoodAggregate` rows correctly.
- `MediaSourceRegistry` and `MediaSelector` are importable, tested, and ready for Plan 2's photo-library registration.
- `GET /api/timeline/standout?month=YYYY-MM` returns user-pinned episodes (and any magi-curated ones, of which there will be zero until Plan 2).
- `GET /api/timeline/mood-calendar?month=YYYY-MM` returns one entry per day with an aggregate row, empty otherwise.
- `scripts/check-api-contract.py` and `scripts/check-sqlite-ownership.py` are clean.
- The existing frontend timeline page renders identically to before (no user-visible change).

## Handoff to Plan 2

Plan 2 (Generation pipeline + scoring) will:
- Register the photo-library plugin as a `MediaSource` in `MediaSourceRegistry`
- Implement the `timeline.diary_narrative` LLM scenario + prompt
- Build the end-of-day/week/month generation orchestrator (writes essence to L3, slice narratives to L2 episodes, populates `representative_asset_ref` via `MediaSelector`)
- Implement the magi-standout scoring heuristic and a periodic re-scoring job
- Implement the `daily_mood_aggregate` algorithm C (time-weighted dominant valence + volatility) and its scheduler integration

After Plan 2 lands, `/standout` and `/mood-calendar` will start returning rich data without any further frontend or API changes.
