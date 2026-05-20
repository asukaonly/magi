# Screenshot Timeline Plugin — Design

**Date**: 2026-05-21
**Status**: Approved, ready for implementation plan
**Scope**: First-party plugin for the magi launch pack — continuous screen capture + local OCR feeding L1, with a memory-grounded query path for future Pass-2 vision LLM enrichment.

---

## 1. Problem & Goal

Magi's plugin ecosystem today consists almost entirely of structured-data sensors (calendar, git, chrome history, music, etc.). The product positioning — a local AI companion with long-term memory — is bottlenecked by **what magi can see**. Knowledge workers spend most of their day inside windows whose contents leave no structured trace: reading docs, drafting in editors, watching videos, jumping between tools.

Rewind and Microsoft Recall validated the demand for "ambient screen memory" but neither integrates with a memory-aware agent that can act on the captured context. Magi already has the memory substrate (L0–L4 lifecycle, evidence classification, episode formation). The missing piece is a high-coverage **passive visual sensor** that feeds it.

**Goal**: ship a macOS-only screenshot timeline sensor in the first launch pack that:
- Continuously captures screen content based on smart triggers, not naive polling
- Runs OCR locally via Apple Vision Framework (no cloud, no LLM calls)
- Writes burst-aggregated events into L1 with structured entity hints
- Reserves an architectural slot for a future Pass-2 vision LLM enrichment without committing to it in v1
- Respects privacy by default (sensible blocklist + global panic hotkey)
- Bounds disk usage (originals on rolling 30-day window, thumbnails permanent)

**Non-goals (v1)**: Windows support, video recording, audio capture, vision LLM enrichment of stored screenshots, cross-device sync.

---

## 2. Constraints from the magi codebase

Decisions below were made to fit existing magi contracts rather than invent new ones:

- **Plugin SDK**: must use the existing `Plugin` + `SensorBase` contribution path. Plugin ships as a self-contained package under `magi-plugins/plugins/screenshot_timeline/`.
- **L1 ingestion**: must produce a normalized `SensorOutput` and flow through the host-owned `SensorIngestionGateway`. Plugin does not write directly to `l1_events.db`.
- **Source-side hints**: structured entity hints (apps, URLs, topics) must travel via `MemoryEvent.metadata_json.structured_entity_hints`, matching the chrome-history precedent (see [memory-system-design.md](../../memory-system-design.md), section "L2 Write-Side Semantic Conventions").
- **Burst aggregation**: matches the chrome-history pattern documented in memory-system-design — short-time-window consecutive same-context captures aggregate into one L1 event.
- **Plugin permissions metadata**: declares its capabilities in `plugin.toml` even though enforcement is not yet wired up. Forward-looking field for the upcoming marketplace permission story.
- **Plugin cache**: any rebuildable state lives under `~/.magi/cache/plugins/screenshot_timeline/`, not in memory databases.

---

## 3. Architecture

### Process topology

```
┌─────────────────────────────────────────────────┐
│ magi backend (Python sidecar)                    │
│                                                  │
│  ScreenshotTimelinePlugin                        │
│   └─ ScreenshotSensor                            │
│       ├─ TriggerOrchestrator                     │
│       │   ├─ timer (active-window interval)      │
│       │   ├─ timer (full-screen interval)        │
│       │   ├─ NSWorkspace observer (window swap)  │
│       │   └─ AX hotkey listener (optional)       │
│       │                                          │
│       ├─ HelperClient                            │
│       │   └─ async stdio JSON ↔ Swift helper     │
│       │                                          │
│       ├─ BurstAggregator                         │
│       │   ├─ session keying by (app, window)     │
│       │   ├─ 5min gap close / 30min hard cap     │
│       │   └─ OCR line-level dedup union          │
│       │                                          │
│       ├─ PrivacyGuard                            │
│       │   ├─ bundle-id blocklist matcher         │
│       │   ├─ incognito window detector           │
│       │   ├─ lockscreen pause                    │
│       │   └─ panic hotkey state                  │
│       │                                          │
│       ├─ RetentionTask (daily cron)              │
│       └─ SensorOutput emitter → ingestion gw     │
│                                                  │
└──────────────────┬──────────────────────────────┘
                   │ stdio JSON
                   ▼
┌─────────────────────────────────────────────────┐
│ magi-vision-helper (Swift binary, child process) │
│                                                  │
│   ├─ ScreenCaptureKit (capture, macOS 12.3+)     │
│   ├─ VNRecognizeTextRequest (OCR)                │
│   ├─ JPEG encoding (sharp-equivalent via Core)   │
│   └─ writes to resources/screenshots/{date}/     │
│                                                  │
└──────────────────┬──────────────────────────────┘
                   │ writes files
                   ▼
        ~/.magi/data/resources/screenshots/
                YYYY/MM/DD/
                cap_{ulid}_thumb.jpg   (permanent)
                cap_{ulid}_orig.jpg    (30-day rolling)

                   │ via SensorIngestionGateway
                   ▼
                magi L1 (fact_events)
                memory_domain = external_activity
                retention_class = compressible
```

### Why Swift subprocess (not PyObjC in-process)

Apple Vision Framework is the only complex native dependency. Two approaches were considered:

| | A. PyObjC in-process | B. Swift subprocess (chosen) |
|---|---|---|
| Vision framework integration | requires runloop ↔ asyncio glue | native runloop |
| Modern capture API (ScreenCaptureKit) | PyObjC bindings incomplete | first-class |
| Crash isolation | crash takes down Python sidecar | crash is recoverable, sensor restarts helper |
| Memory management | CGImage refcount leaks reported in similar projects | Swift ARC, clean |
| Build cost | none (pip install) | one-time Swift toolchain in plugin CI |
| Precedent | calendar plugin uses PyObjC but EventKit is much simpler than Vision | Alma's `AlmaComputerUse` proves this works in production |

B was chosen. The complexity of Vision + ScreenCaptureKit + asyncio in a single Python process outweighs the cost of maintaining a small Swift helper. The helper is the only native component; everything else stays in Python.

### Helper binary distribution

Three-stage rollout:

1. **Dev (now)**: binary committed under `magi-plugins/plugins/screenshot_timeline/bin/magi-vision-helper`. Unsigned. Devs `xattr -d com.apple.quarantine` to bypass Gatekeeper.
2. **Public release**: `magi-plugins` repo CI builds + Developer-ID-signs + notarizes the helper, uploads to GitHub Releases. Plugin manifest declares `release_url` + `release_sha256`; the plugin's first activation downloads and verifies into `~/.magi/cache/plugins/screenshot_timeline/bin/`.
3. **Future**: marketplace-served binaries with hash-based attestation (out of scope for v1).

This keeps Swift toolchain out of the main `magi` build. The main app's signing keys are never used to sign plugin assets.

---

## 4. Capture scope & triggers

### Capture scope (configurable, default hybrid)

| Mode | What it captures | Used when |
|---|---|---|
| `active_window` | Only the frontmost focused window of the focused app | scope = `active_window` or `hybrid` (most ticks) |
| `full_screen` | Entire primary display | scope = `full_screen` (all ticks) or `hybrid` (periodic only) |
| `all_displays` | Every connected display | scope = `all_displays` (all ticks); each display saved as a separate capture file sharing the same burst |

**Hybrid mode (default)** is the most nuanced: on each active-window tick it captures `active_window`, and on each separate full-screen tick (default every 5 min) it captures `full_screen`. The two timers run independently.

**Note**: in hybrid mode, the `full_screen_interval_min` setting (default 5 min) is **different** from the `burst_gap_minutes` parameter (also 5 min, see section 5). They happen to share the same default but control unrelated concepts: interval = how often to capture, gap = how to cluster captures into bursts.

### Trigger sources

| Trigger | Mechanism | Permission | Default |
|---|---|---|---|
| Active-window timer | asyncio interval | Screen Recording | on, **10 sec** |
| Full-screen timer | asyncio interval | Screen Recording | on, **5 min** |
| Window-switch event | `NSWorkspace.shared.notificationCenter` `didActivateApplicationNotification` + AX observation for window focus | Screen Recording | on |
| Keyboard/mouse triggers (scroll, arrow, space, delete) | `CGEventTap` global tap | Accessibility | off (user opts in) |
| Manual capture hotkey | `RegisterEventHotKey` | Accessibility | off (user opts in) |

**Global debounce**: regardless of trigger, the orchestrator enforces a **1.5 second minimum interval** between any two captures of the same scope. Prevents the common "window switch fires + first keystroke fires" double-capture.

**Keyboard trigger debounce**: even when enabled, each individual key trigger type has a per-key 2-second debounce. Scrolling fires at most once every 2 seconds even if the user scrolls continuously.

### Pause states (no capture happens)

- macOS screen locked
- Active app is on the bundle-ID blocklist
- Active window detected as incognito/private mode
- Panic hotkey was pressed within the last `panic_pause_seconds` (default 60)

---

## 5. Burst aggregation

A **burst** is a sequence of captures that share `(app_bundle_id, window_id)` and have no internal gap longer than the burst-gap threshold.

### Aggregation rules

- **burst_gap_minutes**: 5 (default). Captures within the same window within 5 minutes belong to the same burst.
- **burst_max_minutes**: 30 (hard cap). Even continuous activity cuts at 30 minutes.
- **Forced cut conditions**:
  1. Active app or window changes (cuts immediately)
  2. burst_gap_minutes elapsed since last capture
  3. burst_max_minutes elapsed since burst start
  4. Sensor stops or settings change

### When a burst closes, the aggregator emits one `SensorOutput`

The aggregator owns the in-memory state of open bursts (typically 1–2 at any moment). When a burst closes, it produces:

- `SensorActivity` with `source_code`, `action_code`, `object_code` (app bundle), and `qualifiers` (window title, URL, capture counts, duration, trigger breakdown)
- `SensorNarration` with `title` = `f"{app_name}: {window_title}"` and `body` = OCR text union (see section 6)
- `content_blocks` — empty for v1; reserved for future Pass-2 image-block injection
- `entities` — structured entity hints (app, software, topic) derived from window title + URL + bundle ID
- `tags` — `app:{slug}`, `category:{browser|editor|...}`, `display:{primary|secondary}`

---

## 6. L1 data shape

### fact_events row (after host normalization)

| Field | Value |
|---|---|
| `event_id` | host-generated ULID |
| `source` | `"screenshot_timeline"` |
| `event_type` | `"SENSOR_EVENT"` |
| `source_item_id` | `f"{yyyymmdd}_{burst_start_unix}_{app_bundle}_{window_hash}"` |
| `idempotency_key` | same as `source_item_id` |
| `timestamp` | burst start time |
| `memory_domain` | `external_activity` |
| `cognition_eligible` | `true` |
| `retention_class` | `compressible` |
| `content_type` | `TEXT` |
| `importance_score` | 0.3 (timer-only) / 0.5 (window-switch) / 0.8 (manual hotkey) |
| `content` | see "Content composition" below |
| `metadata_json` | see "Metadata structure" below |

### Content composition (OCR text union)

The `content` field is the canonical retrieval surface for L1 vector and FTS indexes. To balance recall against bloat:

1. Start with the window title on its own line (strongest signal)
2. Iterate captures in chronological order
3. For each capture, split OCR text by lines
4. Append each line that has not been seen in this burst (case-sensitive exact match, after trim)
5. Cap at 8000 characters per L1 event (truncate with `\n[truncated]` marker if exceeded — should be rare even for long reading sessions)

This deduplicates the "user re-reads the same paragraph 12 times" case while preserving order-of-discovery for novel content (scrolling reveals new lines, which get appended).

### Metadata structure

```json
{
  "activity": {
    "source_code": "screenshot_timeline",
    "action_code": "screen_session",
    "object_code": "com.apple.Safari",
    "qualifiers": {
      "window_title": "Magi project plan - Notion",
      "url": "https://notion.so/...",
      "display_id": "primary",
      "capture_count": 12,
      "duration_seconds": 540,
      "trigger_breakdown": {
        "timer": 6,
        "window_switch": 1,
        "keyboard": 5,
        "manual": 0
      },
      "ocr_confidence_avg": 0.94
    }
  },
  "media": {
    "representative_capture_id": "cap_01JQM...",
    "captures": [
      {
        "capture_id": "cap_01JQM...",
        "captured_at": 1747823400.123,
        "trigger": "window_switch",
        "scope": "active_window",
        "thumbnail_path": "resources/screenshots/2026/05/21/cap_01JQM_thumb.jpg",
        "original_path": "resources/screenshots/2026/05/21/cap_01JQM_orig.jpg",
        "original_expires_at": 1750415400.0,
        "dimensions": [2880, 1800],
        "ocr_text_hash": "sha256:..."
      }
    ]
  },
  "projection": {
    "renderer_version": "screenshot_timeline.v1",
    "burst_strategy": "same_window_5min_gap_30min_cap"
  },
  "structured_entity_hints": [
    {"type": "software", "name": "Safari", "canonical_id": "com.apple.Safari"},
    {"type": "software", "name": "Notion", "canonical_id": "so.notion"},
    {"type": "topic", "name": "Magi project plan"}
  ]
}
```

### Pass-2 reservation

`metadata.media.captures[*].original_path` is the hook future Pass-2 vision LLM enrichment will use. While `original_path` is non-null (within the 30-day window) a future feature can:

1. Receive a `historical_recall` hit pointing at this L1 event
2. Read `metadata.media.captures` for the still-alive originals
3. Pass them to a vision model for higher-fidelity interpretation
4. Optionally write derived L2 assertions back

No code or schema work is needed in v1 to enable this — the metadata shape is forward-compatible.

---

## 7. Privacy controls

### Default blocklist (shipped)

| Category | Examples |
|---|---|
| Password managers (bundle ID glob) | `com.agilebits.onepassword*`, `com.bitwarden.desktop`, `com.lastpass.LastPassMacDesktop`, `com.apple.keychainaccess`, `com.dashlane.*`, `com.1password.1password*` |
| Incognito browser windows | detected via Accessibility API window-attribute introspection (Safari Private, Chrome Incognito, Firefox Private, Arc Incognito) |
| System auth UIs | `com.apple.SecurityAgent` (the system password sheet) |
| Lock screen | suspend capture entirely when `CGSessionCopyCurrentDictionary` reports locked |

### User extensions

- App blocklist editor in Settings (add/remove bundle IDs via drag-and-drop of `.app` or manual entry)
- Window-title substring blocklist (default empty; users opt in if they want title-keyword filtering)
- Panic hotkey (default ⌥⇧P, configurable): pressing it pauses capture for `panic_pause_seconds` (default 60). Pressing again clears the pause early.

### Permission disclosure

First-run UI explicitly enumerates:
- "Screen Recording" permission required (for capture itself)
- "Accessibility" permission optional (only if keyboard/mouse triggers or panic hotkey are enabled)
- Local-only storage confirmation: "Screenshots are stored only on this Mac. They are not sent to any server, including LLM providers, unless you explicitly use the future 'analyze with vision' feature."

---

## 8. Storage & retention

### Layout

```
~/.magi/data/resources/screenshots/
  2026/05/21/
    cap_01JQM_thumb.jpg    ~30KB, 1024px wide, JPEG quality 70, permanent
    cap_01JQM_orig.jpg     ~250KB, native resolution, JPEG quality 80, 30-day rolling
    cap_01JQR_thumb.jpg
    cap_01JQR_orig.jpg
    ...
```

### Retention enforcement

The plugin registers a **daily maintenance task** through magi's existing scheduler. The task:

1. Queries L1 for `screenshot_timeline` events created more than `retention_days` ago
2. For each event, iterates `metadata.media.captures[]`
3. For each capture with `original_path` non-null and `original_expires_at < now`:
   - Deletes the `_orig.jpg` file
   - Patches the L1 metadata: sets `original_path` to `null`, keeps `thumbnail_path` and all other fields
4. Logs deleted bytes and capture count for observability

### Disk usage projection

- Typical day: 100–300 captures
- Thumbnail growth (permanent): ~1–3 GB / year, **uncapped** — grows linearly with use
- Originals at any moment: ~3–10 GB (capped by 30-day rolling window)
- Year-1 total: roughly **10–15 GB** (3 GB thumb + ~10 GB peak orig)
- Year-3 total: roughly **15–20 GB** (9 GB thumb + ~10 GB peak orig)

The settings UI surfaces a "Storage used" indicator with two actions: "trim originals now" (deletes all originals immediately, keeps thumbnails) and "delete thumbnails older than N days" (for users who want a hard cap on thumbnail growth). The latter is destructive and prompts for confirmation.

---

## 9. Plugin manifest

```toml
[plugin]
id = "screenshot_timeline"
name = "Screenshot Timeline"
version = "0.1.0"
description = "Captures your macOS screen, runs local OCR, and feeds magi's memory."
official = true
entry_module = "plugin"
entry_class = "ScreenshotTimelinePlugin"
contribution_types = ["sensor"]
platforms = ["macos"]
min_sdk_version = "0.1.0"  # pinned to current SDK; bump if we depend on new features

[plugin.helper]
binary_relative_path = "bin/magi-vision-helper"

[plugin.permissions]
declares = ["screen_recording", "accessibility_optional", "fs_write_resources"]
memory_access = ["write_l1"]
```

The `[plugin.helper]` section is a plugin-local extension to the manifest schema. In dev mode it points at the committed binary. In release mode it will additionally carry `release_url` and `release_sha256` for first-activation download.

---

## 10. Settings surface

Exposed via `PluginSettingsResourceSpec` and `ExtensionFieldSpec`:

| Field | Type | Default | Notes |
|---|---|---|---|
| `enabled` | toggle | `false` | User must explicitly enable on first run |
| `capture_scope` | select(active_window, full_screen, hybrid, all_displays) | `hybrid` | |
| `active_window_interval_sec` | number(2..120) | `10` | |
| `full_screen_interval_min` | number(1..60) | `5` | Applies only when scope == hybrid or full_screen |
| `ocr_languages` | multi(BCP-47) | `["en-US", "zh-Hans"]` | Forwarded to Vision recognitionLanguages |
| `ocr_recognition_level` | select(fast, accurate) | `accurate` | Vision tradeoff knob |
| `original_retention_days` | number(0..365) | `30` | 0 means delete originals immediately after OCR |
| `keyboard_triggers_enabled` | toggle | `false` | Gates the Accessibility permission ask |
| `keyboard_trigger_types` | multi(scroll, arrow, space, delete, return) | all four | |
| `app_blocklist` | list(bundle_id pattern) | default list | Default list is editable; user can remove items |
| `window_title_blocklist` | list(substring) | `[]` | |
| `panic_hotkey` | shortcut | `⌥⇧P` | |
| `panic_pause_seconds` | number(10..3600) | `60` | |

---

## 11. Helper protocol (Python ↔ Swift)

Newline-delimited JSON over stdio. Python writes requests; helper writes responses.

### Request types

```jsonc
// Capture + OCR
{
  "id": "req_01JQM...",
  "op": "capture_and_ocr",
  "scope": "active_window",   // or "full_screen", "display:1"
  "ocr": {
    "languages": ["en-US", "zh-Hans"],
    "level": "accurate"
  },
  "save_paths": {
    "original": "/Users/asuka/.magi/data/resources/screenshots/2026/05/21/cap_01JQM_orig.jpg",
    "thumbnail": "/Users/asuka/.magi/data/resources/screenshots/2026/05/21/cap_01JQM_thumb.jpg"
  },
  "jpeg_quality": {"original": 80, "thumbnail": 70},
  "thumbnail_max_width": 1024
}

// Probe active window (no capture)
{
  "id": "req_01JQN...",
  "op": "probe_active_window"
}

// Shutdown
{
  "id": "req_01JQO...",
  "op": "shutdown"
}
```

### Response types

```jsonc
{
  "id": "req_01JQM...",
  "ok": true,
  "captured_at": 1747823400.123,
  "dimensions": [2880, 1800],
  "active_window": {
    "app_bundle_id": "com.apple.Safari",
    "app_name": "Safari",
    "window_title": "Magi project plan - Notion",
    "url": "https://notion.so/...",      // null for non-browser apps
    "incognito": false,
    "display_id": "primary"
  },
  "ocr": {
    "text": "<full OCR text with newlines>",
    "confidence_avg": 0.94,
    "block_count": 23
  },
  "files_written": {
    "original_bytes": 256432,
    "thumbnail_bytes": 31204
  }
}

// Error
{
  "id": "req_01JQM...",
  "ok": false,
  "error": {
    "code": "PERMISSION_DENIED",  // or "CAPTURE_FAILED", "OCR_FAILED", "BLOCKED_APP"
    "message": "Screen Recording permission not granted"
  }
}
```

### Lifecycle

- The Python sensor spawns one long-lived helper process on sensor start
- The sensor monitors the helper's exit code; on unexpected exit, it relaunches with exponential backoff (1s, 2s, 4s, capped at 60s)
- The helper logs to stderr; the sensor mirrors helper stderr into magi's logger with the `screenshot_timeline.helper` namespace
- The helper exits cleanly on `op=shutdown`; the sensor waits up to 2 seconds, then SIGTERM, then SIGKILL

---

## 12. Failure modes & recovery

| Failure | Detection | Recovery |
|---|---|---|
| Helper crashes | exit code observed by sensor | exponential-backoff respawn; sensor health degrades to `unhealthy` after 5 consecutive failures |
| Screen Recording permission revoked at runtime | helper returns `PERMISSION_DENIED` | sensor pauses, surfaces a settings notification, retries every 5 minutes |
| Disk full | file write fails | skip this capture, log warning, surface settings notification at >3 consecutive failures |
| Helper hangs (no response within 10s) | request timeout in sensor | kill helper, respawn, drop this capture |
| OCR returns empty (e.g., screen was all-black) | response with empty text | store the capture metadata anyway with `ocr.text=""`; do not emit a burst-extending event from an empty capture |
| Same capture file fails to save | retry once with a new ULID, then give up |
| Burst aggregator state lost (process restart) | open bursts at restart are simply closed and emitted; in-flight captures resume in new bursts |

The sensor exposes standard `SensorBase` health and status fields; the settings UI surfaces "Last capture", "Captures today", "Storage used", "Helper status".

---

## 13. Testing strategy

### Unit
- Burst aggregator: gap-cut, max-cut, window-change-cut, idempotency-key generation
- Privacy guard: bundle-ID glob matching, incognito detection logic, lockscreen state
- OCR text union: line-level dedup, ordering preservation, length cap
- Trigger debounce: global 1.5s, per-key 2s
- Retention task: `original_expires_at` filtering, metadata patching idempotency

### Integration (mock Swift helper)
- Sensor↔helper protocol contract: request/response JSON round-trip
- Helper crash → respawn cycle with backoff
- Empty OCR result → does not break burst aggregation

### Manual E2E
- Enable plugin, work for 30 minutes, verify:
  - L1 events appear under the screenshot_timeline source
  - Bursts segment by visible window changes
  - OCR text in L1 content is reasonable and deduplicated
  - Thumbnails open in Finder
  - Blocklist enforced (open 1Password, capture is suppressed)
  - Panic hotkey suspends for 60 seconds

---

## 14. Open items deferred to implementation plan

- Exact Swift helper build target / Xcode project layout
- Whether to use `pyobjc-framework-Quartz` for the lightweight NSWorkspace observer (no Vision dep) or to push window-event detection into the Swift helper too
- Settings UI mockup details (which fields collapse into "Advanced")
- L4 procedural learning: whether to surface "user manually invoked panic hotkey while in app X" as a signal — likely out of scope for v1
- Multi-monitor capture ordering and naming conventions in `all_displays` mode

These are implementation-time choices; none affect the L1 contract or the public-facing behavior described above.

---

## 15. Out of scope (explicitly)

- Windows support — separate design once magi grows a Windows-OCR plugin
- Vision LLM Pass 2 — separate design, but storage and metadata are forward-compatible
- Video recording or audio capture
- Cross-device sync of screenshots
- Sharing/export of captured timeline segments (a future "publish" plugin's responsibility)
- Modifying or styling magi's daily briefing — a separate plugin

---

## 16. References

- Plugin SDK contracts: [magi/sdk/src/magi_plugin_sdk/](../../../sdk/src/magi_plugin_sdk/)
- L1 ingestion path: [memory-system-design.md § "How Data Enters the Memory System"](../../memory-system-design.md)
- Burst pattern precedent: [chrome-history plugin](https://github.com/asukaonly/magi-plugins/tree/main/plugins/chrome-history)
- PyObjC precedent in magi: [calendar_plugin](https://github.com/asukaonly/magi-plugins/tree/main/plugins/calendar_plugin)
- Swift subprocess precedent: Alma.app's `AlmaComputerUse` helper (`Vision.framework` + `VNRecognizeTextRequest`)
