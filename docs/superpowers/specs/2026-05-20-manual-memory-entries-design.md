# Design: Manual Memory Entries

**Date**: 2026-05-20
**Status**: spec (Phase A approved for implementation)

## Why

Magi today is a one-way observer: it sees Chrome, screen, music, calendar,
location — but it never hears from the user directly. The most important
"memory raw material" — thoughts, intentions, conversations remembered,
emotional state, plans — lives only in the user's head, never reaching
the system. Every other observation-only feature (timeline, themes, mood,
diary) is built on top of a structurally incomplete picture.

A standalone notes app inside Magi would partially fix this but lose the
core value: the entry's only purpose would be to be re-read later. The
better framing is **manual memory entries as first-class citizens of the
existing data flow**:

- Saved → projected to L1 event (`source = 'manual_entry'`)
- L2 episode_formation absorbs them like any other L1 event
- Themes pipeline considers their tags (future) and entities
- mood_aggregate consumes the user-tagged valence as ground truth
- Diary LLM receives them as the **highest-weight evidence** in its
  per-episode excerpt list
- Rendered inline in the same time-of-day buckets as Chrome / screen rows

The differentiator from "yet another notes app" is the integration:
the user writes a sentence, Magi works it into the day's essence.

## Core decisions

### 1. Two capture surfaces (Phase A vs Phase B)

| Mode | Use | Friction | Phase |
|------|-----|----------|-------|
| Quick | "刚刚突然想到…" | One textarea, ⌘+Enter saves | A |
| Rich | Sit-down journal entry | Title + body + rich text + tags | B |

90% of memory capture is impulse-driven; 10% is intentional. Forcing both
through a single editor punishes both populations.

### 2. `event_at` ≠ `created_at`

Users often write about the past: "昨晚的会议让我…". The entry should
land in **yesterday**'s timeline, not today's. The data model separates:

- `created_at` — when the user clicked save
- `event_at` — when the memory itself happened (defaults to created_at)

UI exposes this as a small time-shift dropdown next to the save button
(刚才 / 1h 前 / 今早 / 昨晚 / 自定义...).

### 3. Default participate in LLM generation

User-written content is the highest-quality memory signal we'll ever
have. Defaulting it out of LLM context wastes the most useful data.
**Phase A: every entry participates.** Phase B+ adds a per-entry
`exclude_from_llm` toggle for sensitive notes. The toggle in the row
menu (⋯) becomes ⚙ "不参与生成".

## Phase A scope

**In:**
- Floating ✎ button on the timeline page
- Slide-up sheet with: textarea, image attachments (upload + clipboard
  paste), mood pills (5 valence), time-shift dropdown, location chip
- Image storage as content-addressed files under
  `~/.magi/data/media/manual_entries/<sha256>.{ext}`
- L1 projection (`source='manual_entry'`, content=body,
  metadata carries attachment refs + mood + entry_id)
- Render in DayBuckets as a special source group "📝 你的记录" — always
  ordered first within its bucket, with a left accent stripe
- Image thumbnails inline in slice rows; click → full-screen preview
- Edit / soft-delete via row menu (⋯)

**Out (deferred to B/C):**
- Title field
- Rich text formatting (Tiptap)
- Tags
- Cross-link to specific episodes via @-mention
- Per-entry privacy gate (`exclude_from_llm`)
- Edit history snapshots
- Auto-suggestion of tags from recent activity

## Data model

### Tables (new migration `0007_manual_entries`)

```sql
CREATE TABLE manual_entries (
  entry_id          TEXT PRIMARY KEY,
  created_at        REAL NOT NULL,
  event_at          REAL NOT NULL,
  kind              TEXT NOT NULL DEFAULT 'quick',
  body              TEXT NOT NULL,
  mood              TEXT,
  location_label    TEXT,
  location_lat      REAL,
  location_lng      REAL,
  attachments_json  TEXT NOT NULL DEFAULT '[]',
  exclude_from_llm  INTEGER NOT NULL DEFAULT 0,
  user_pinned       INTEGER NOT NULL DEFAULT 0,
  deleted_at        REAL,
  l1_event_id       TEXT
);
CREATE INDEX idx_manual_entries_event_at ON manual_entries(event_at DESC);
CREATE INDEX idx_manual_entries_active   ON manual_entries(deleted_at, event_at DESC)
    WHERE deleted_at IS NULL;
```

Fields reserved for B/C (`title`, `tags_json`, `related_episode_ids_json`)
deliberately omitted from the v1 migration — adding nullable columns later
is cheap. Including unused columns now would muddle the data.

### L1 event projection

When a manual entry is saved or updated, we emit a corresponding L1 event
so the entry participates in the rest of the memory model without
parallel ingestion paths:

```python
L1Event(
    event_id=<generated>,
    source='manual_entry',
    timestamp=entry.event_at,       # NOT created_at — placement on timeline
    content=entry.body,
    metadata={
        'timeline': {
            'title': '你写下的',
            'source_type': 'manual_entry',
            'mood': entry.mood,
            'attachments': entry.attachments,   # asset_ref list
        },
        'manual_entry': {
            'entry_id': entry.entry_id,
            'location_label': entry.location_label,
        },
    },
)
```

The entry's `l1_event_id` is stored back on `manual_entries.l1_event_id`
so edits can update the same L1 row in place (re-issue with new content)
and soft-deletes can tombstone the L1 row.

### Image attachments

**Storage**: Content-addressed under
`~/.magi/data/media/manual_entries/<sha256[:2]>/<sha256>.{ext}` — same
sha256 of bytes is deduplicated automatically. Two-character prefix
directory keeps any single dir below ~1k files.

**Reference scheme**: `manual-entry-asset://<sha256>.{ext}`. Served by the
existing `/timeline/asset/{ref:path}` route after a small extension to
its resolver registry.

**Upload size cap**: 10MB per image (v1). Reject larger with a clear
error. No auto-resize or recompression in v1.

**Format support**: png, jpg/jpeg, gif, webp, heic. heic is converted to
jpg server-side on upload (macOS users paste a lot of heic).

## Visual integration

### Day scale — special source group in buckets

```
晚上  18:00 – 24:00                                    3h
  ▎ 📝 你的记录 · 1                             ← left accent stripe
       20:43 ● (warm)   和 X 在咖啡馆聊了一小时...    ← mood dot inline
                        [thumb] [thumb]                 ← image grid
                                                ♡  ⋯
  
  🌐 Chrome · 2h
       ...
```

- The 📝 group is always rendered first in its bucket (not subject to
  duration-sort)
- Left accent stripe (`border-l-2`) in a warm color so the group reads as
  "yours" at a glance
- If mood is set, render a tiny colored dot next to the time
- Image thumbnails inline below the text, max 4 visible, "+N" overlay
  for more
- Click image → full-screen preview using existing image-preview pattern

### Hero — diary LLM may quote manual entries

The diary LLM prompt receives a per-episode excerpts list. We weight
manual-entry-derived excerpts higher in the assembly step. The prompt's
system message already says "incorporate concrete nouns from 事件证据";
adding "用户原话" as a higher-priority excerpt type lets it surface
verbatim phrasings when they're striking:

> 上午你写下"找回那种平静的感觉"——这一天似乎就是循着这句话展开的。

### Sidebar / standout

Manual entries are eligible for standout scoring. They get a large
intrinsic score (manual entries are by definition "worth coming back
to"). The 值得回来的 sidebar column shows them with a 📝 marker.

## Interaction details

### Quick capture sheet

```
┌──────────────────────────────────────────────┐
│ 写下…                                          │
│                                               │
│ │cursor│                                      │
│ (3-line min textarea, ⌘+Enter to save)       │
│                                               │
├──────────────────────────────────────────────┤
│ [📎 添加图片]                                  │
│ [thumb] [thumb] [+]                          │  ← when attachments
├──────────────────────────────────────────────┤
│ 🎨  ○  ○  ○  ●  ○      ✕                    │  ← mood pills + clear
│                                               │
│ 🕐 [刚才 ▾]     📍 [杭州 ✕]                    │
├──────────────────────────────────────────────┤
│                  [取消]    [保存]              │
└──────────────────────────────────────────────┘
```

**Triggers:**
- ✎ floating button on timeline page (bottom-right, 56px circle)
- Keyboard shortcut: `n` when timeline page is focused (no input has focus)

**Save:**
- ⌘+Enter inside textarea
- "保存" button
- Save is disabled until body has at least 1 non-whitespace character
  OR at least 1 image attached

**Paste handler:**
- `onPaste` on the textarea catches `image/*` clipboard items
- Each pasted image is uploaded to the asset endpoint immediately and a
  thumbnail appears in the attachments row
- Text paste flows through normally

**Cancel:**
- "取消" button closes without saving
- Esc key (if no field has unsaved changes; otherwise confirm)

### Mood pill selector

5 circles in a row, each colored to its valence:

- warm (`#c9a878`)
- bright (`#d4b886`)
- neutral (`#a8a08a`)
- cool (`#7a8898`)
- tense (`#b87a78`)

Behavior:
- All empty (outline only) by default
- Click one → solid fill + ring
- Click selected → deselect (back to all-empty)
- An "✕" appears next to the row when one is selected — clicking it
  clears the selection (faster than finding the right pill)

### Time-shift dropdown

```
[ 刚才 ▾ ]
   ↓
┌──────────────┐
│ 刚才          │
│ 1 小时前      │
│ 今早          │
│ 昨晚          │
│ 自定义...    │  → 弹出原生 datetime picker
└──────────────┘
```

The presets compute `event_at` relative to "now" at save time. "自定义"
opens a datetime picker.

### Edit / delete

Row menu (⋯) on the rendered slice:
- 编辑 → reopens the same sheet pre-filled
- 删除 → confirms, then soft-deletes (sets `deleted_at`)
- ♡ 收藏 / 取消收藏 (existing slice menu item)

## Privacy posture (Phase A)

- All entries participate in LLM generation (no per-entry gate)
- All entries appear in themes / mood / diary
- B phase introduces `exclude_from_llm` toggle and a row-menu item for it

The rationale for default-participate: a user who took the effort to
write something down by hand has implicitly endorsed it as meaningful.
The few cases they don't want LLM to see can be addressed in B.

## Non-goals (Phase A)

- Title field
- Rich text formatting (Tiptap / blocks)
- Tags / categories
- Cross-link to specific episodes via @-mention
- Edit history / revisions
- Auto-suggested mood from text sentiment
- Speech-to-text input
- Sync across devices (covered by existing memory.db sync)
- Mobile companion (no mobile client exists)
