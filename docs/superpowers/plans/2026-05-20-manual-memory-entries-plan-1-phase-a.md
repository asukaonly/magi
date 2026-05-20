# Plan: Manual Memory Entries — Phase A

**Date**: 2026-05-20
**Spec**: [`2026-05-20-manual-memory-entries-design.md`](../specs/2026-05-20-manual-memory-entries-design.md)
**Scope**: Quick capture only (text + images + mood + auto-context).
Rich editor (titles, formatting, tags, cross-link, privacy gate) is
deferred to Phase B+.

## Task breakdown

### Backend

#### T1 — Migration + `ManualEntryStore`

- New migration `0007_manual_entries.py` creating `manual_entries`
  table per the spec.
- Add `0007_manual_entries.py` to `tests/_shared/memory_schema.py`
  migration list.
- New module `backend/src/magi/memory/manual_entries/`:
  - `models.py` — `ManualEntry` dataclass
  - `store.py` — `ManualEntryStore` with CRUD:
    - `create(entry: ManualEntry) -> str`
    - `update(entry_id, *, body=None, mood=None, attachments=None, event_at=None) -> bool`
    - `soft_delete(entry_id) -> bool`
    - `get(entry_id) -> Optional[ManualEntry]`
    - `list_window(time_start, time_end, *, include_deleted=False) -> list[ManualEntry]`
    - `link_l1_event(entry_id, l1_event_id) -> None`

Tests: store CRUD, soft-delete behavior, window query excluding deleted.

#### T2 — Asset storage + upload endpoint

- New module `backend/src/magi/memory/manual_entries/asset_store.py`:
  - `ManualEntryAssetStore` with:
    - `store_bytes(data: bytes, declared_ext: str) -> str`
      Computes sha256, writes to
      `~/.magi/data/media/manual_entries/<sha[:2]>/<sha>.<ext>` if not
      already present, returns asset_ref `manual-entry-asset://<sha>.<ext>`.
    - `resolve(asset_ref) -> tuple[bytes, content_type] | None`
    - heic conversion via `pillow-heif` (already in deps? else add)
- Asset upload route: `POST /memory/manual-entries/assets`
  - Multipart form, single file per request
  - Validates `Content-Type` in {image/png, jpeg, gif, webp, heic, heif}
  - Validates `Content-Length` ≤ 10MB
  - Returns `{asset_ref, width, height, content_type, byte_size}`
- Add `manual-entry-asset://` scheme to the existing
  `_resolve_photo_library_asset`-style registry in `timeline/service.py`
  so the existing `/timeline/asset/{ref:path}` route can serve them.

Tests: dedup by sha (same bytes twice → single file, same ref),
oversized payload rejected, content-type whitelist, heic→jpg path.

#### T3 — Entry CRUD endpoints

New router `backend/src/magi/api/routers/manual_entries.py`:

- `POST   /memory/manual-entries` — create
  Body: `{event_at, body, mood?, location_label?, location_lat?, location_lng?, attachment_refs: []}`
  Returns the created entry.
- `GET    /memory/manual-entries?time_start=&time_end=&include_deleted=` — list window
- `PATCH  /memory/manual-entries/{entry_id}` — partial update
  Allowed fields: `body`, `mood`, `event_at`, `attachment_refs`
- `DELETE /memory/manual-entries/{entry_id}` — soft delete

Each route's handler is thin: validate, call store, project L1 (T4 below),
return DTO.

Mirror the routes in the Rust gateway's proxy table
(`gateway/src/routes/memory.rs` or wherever the `_PUBLIC_ROUTE_METHODS`
dict equivalent lives) so frontend can hit them through the gateway.

#### T4 — L1 projection (`ManualEntryL1Projector`)

When an entry is created/updated/soft-deleted, project to L1:

- New helper `manual_entries/l1_projector.py`:
  - `async def project_on_create(entry, l1_store) -> str`
    Emits `MemoryEvent(source='manual_entry', timestamp=event_at,
    content=body, metadata={...})` and returns the assigned event_id.
    Idempotency key: `manual-entry:{entry_id}:v1`.
  - `async def project_on_update(entry, l1_store) -> None`
    If `entry.l1_event_id` exists, re-issue the event with bumped
    version and same idempotency key prefix. Otherwise create fresh.
  - `async def project_on_delete(entry, l1_store) -> None`
    Tombstone the L1 row (existing tombstone path on L1Store).

Wired in T3 route handlers immediately after store writes.

Tests: round-trip (create → list returns it; L1 query in window finds
the projection; soft-delete tombstones the L1).

#### T5 — Diary LLM prompt: weight manual entries

In `timeline/narrative/event_excerpts.py` `build_excerpts`:
- Take an additional bias: if event has `source == 'manual_entry'`,
  prepend with a "用户原话：" prefix so the LLM treats it specially.
- Don't change cap or selection logic — the existing length-sort
  promotes them naturally since user text is usually longer than
  Chrome titles.

Also in `timeline/narrative/prompts.py`:
- Add one sentence to the system prompt:
  > 标有"用户原话"的事件证据是用户亲手写下的笔记或日记，
  > 是最高优先级的信号——essence 中可以直接引用一句。

Tests extend existing test_event_excerpts.py with a manual-entry case.

#### T6 — TimelineService surfaces manual entries naturally

No code change expected — the cluster_builder already reads L1 events
in episode windows; once the L1 projection lands, manual entries flow
through to clusters automatically. The cluster's `source_types` list
will contain `'manual_entry'` once `_enrich_cluster_source_types` runs.

Two small additions:
- `cluster_builder._episode_to_cluster`: when an episode's L1 events
  include `source='manual_entry'`, hoist the entry's attachments into
  `cluster.media_refs` so the frontend can render thumbnails.
- `viewport_builder._enrich_cluster_source_types`: prefer
  'manual_entry' as the primary source_type when present (so the
  frontend buckets group it correctly).

#### T7 — Backend tests

- store/, l1_projector/, asset_store/ unit tests (covered above)
- End-to-end integration: POST entry → GET window → DELETE → check L1
  tombstoned + cluster_builder no longer surfaces it.

### Frontend

#### T8 — `manualEntriesApi` module

`frontend/src/api/modules/manualEntries.ts`:
- `list({timeStart, timeEnd, includeDeleted?}) -> ManualEntry[]`
- `create(body) -> ManualEntry`
- `update(id, patch) -> ManualEntry`
- `remove(id) -> void`
- `uploadAsset(file: File) -> {asset_ref, width, height, content_type}`

TypeScript interfaces for `ManualEntry` matching backend DTO.

#### T9 — Floating ✎ button on timeline page

In `frontend/src/pages/Timeline.tsx`:
- Floating button fixed at bottom-right of `<main>`
- Icon: `Feather` from lucide
- Hidden when sheet is open
- Opens `<QuickEntrySheet>`

Keyboard shortcut: `n` on the timeline page (only when no input is
focused) opens the sheet. Standard `useHotkeys` hook or manual listener.

#### T10 — `QuickEntrySheet` component

New `frontend/src/components/timeline/manual-entries/QuickEntrySheet.tsx`:

State:
- `body: string`
- `attachments: AttachmentDraft[]` where AttachmentDraft is
  `{ asset_ref, thumb_url, status: 'uploading' | 'ready' | 'error' }`
- `mood: Valence | null`
- `eventAt: number | null` (null = "now at save time")
- `location: { label, lat, lng } | null`
- `saving: boolean`

Components inside:
- Textarea with placeholder "写下…"
- AttachmentRow: thumbnail grid + 📎 upload button
- MoodPillRow: 5 circles + clear ✕
- TimeShiftDropdown: preset menu + custom datetime
- LocationChip: shows current resolver result with ✕

UX rules:
- Save button disabled while `body.trim() === '' && attachments.length === 0`
- Save disabled while any attachment status is 'uploading'
- ⌘+Enter triggers save
- Esc closes (with unsaved-changes confirm if body or attachments non-empty)

#### T11 — Image paste handler

On the textarea's `onPaste`:
- Iterate `event.clipboardData.items`
- For each `item.type.startsWith('image/')`:
  - `getAsFile()` → `File`
  - Add an AttachmentDraft with `status: 'uploading'`
  - Call `manualEntriesApi.uploadAsset(file)` async
  - On resolve, update draft with returned `asset_ref` + `status: 'ready'`
  - On reject, mark `status: 'error'` and surface a toast

Same flow on the 📎 file picker button (which opens a native input).

For HEIC: don't preview in the browser (no native support); show a
generic image placeholder with the filename, rely on server-side
conversion to jpg for the stored copy.

#### T12 — Render manual entries in DayBuckets

In `frontend/src/components/timeline/immersive/DayBuckets.tsx`:
- When a cluster has `source_types[0] === 'manual_entry'`:
  - Render as a special source group, always first in its bucket
  - Use `Feather` icon (or 📝) instead of the generic icon
  - Left accent stripe (`border-l-2 border-warm` or similar)
  - If `cluster.media_refs` non-empty, render a thumbnail grid below
    the slice text (max 4 visible, "+N" overlay for more)
  - If cluster's underlying entry had a mood, show a colored dot next
    to the time

Image thumbnails:
- Use existing `resolveTimelineAssetUrl` for the photo proxy path
- Click → existing fullscreen image preview pattern (reuse from chat
  if it exists, otherwise create a tiny modal here)

#### T13 — Edit / delete from row menu

Slice's existing ⋯ menu adds two items when the underlying cluster is
a manual entry:
- 编辑 → opens `<QuickEntrySheet>` pre-filled
- 删除 → confirm modal → calls `manualEntriesApi.remove`

Pin / un-pin (♡) already exists and works.

#### T14 — Frontend tests

- `manualEntriesApi.test.ts`: shape only
- `QuickEntrySheet.test.tsx`:
  - Save disabled while body empty + no attachments
  - ⌘+Enter triggers save
  - Paste image → upload + thumb shown
  - Mood pill select / deselect
- `DayBuckets.test.tsx`: extends existing tests with a manual-entry
  cluster fixture

### Wiring

#### T15 — Bootstrap + routes

- New `ManualEntriesModule` in `backend/src/magi/memory/` that
  constructs `ManualEntryStore` + `ManualEntryAssetStore` + projector
  and attaches them to `unified_memory`
- Register the new router in `transport/http_app.py`
- Add new gateway proxy table entries for the 5 routes + asset upload

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Tauri's webview clipboard image paste may not deliver the same `clipboardData` shape as a browser | Test on the actual desktop build early; fallback to manual upload button always available |
| HEIC conversion fails on Linux/Windows | Make heic conversion optional — if `pillow-heif` import fails, reject heic uploads with a clear error |
| Image upload races vs save | Save button disabled while any attachment is uploading; visible upload spinner per thumbnail |
| L1 projection drift on edit (orphan L1 row) | Idempotency key includes entry_id; existing tombstone path on L1Store cleans up on delete |
| User pastes a 50MB screenshot | Size check on server (10MB cap) + client-side pre-check before upload to give a friendlier error |
| Image bytes leak between users in multi-user setups (future) | Content-addressed storage means user A's sha256 can collide with user B's identical bytes — by definition the content IS the same. Not a leak. |

## Estimate

- T1 + T2 + T3 + T4: 1.5 days (the storage + endpoints + projection)
- T5 + T6: 0.5 day (diary prompt + cluster enrichment)
- T7: 0.5 day (backend tests)
- T8 + T9 + T10 + T11: 1 day (frontend api + sheet UI + paste)
- T12 + T13: 0.5 day (bucket rendering + edit/delete)
- T14: 0.5 day (frontend tests)
- T15: 0.25 day (wiring + smoke test)

**Total: ~4 days.**

## Out of scope reminders (Phase B+)

- Title field
- Rich text / Tiptap
- Tags
- Cross-link to episodes via @-mention
- `exclude_from_llm` per-entry toggle
- Edit history / revisions
- Auto-suggested mood from text sentiment
- Standout score boost for manual entries (right now they're eligible
  via the generic heuristic but don't get extra weight)
