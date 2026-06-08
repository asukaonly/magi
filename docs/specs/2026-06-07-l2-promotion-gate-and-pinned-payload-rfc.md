# RFC: L2 Ingestion — Plugin-Owned Promotion Gate + Capture-Time Pinned Payload

- **Status:** Draft RFC (design discussion captured; not yet scheduled)
- **Date:** 2026-06-07
- **Scope:** The L2 memory pipeline ↔ sensor-plugin contract (backend `magi.memory` + plugin SDK).
- **Explicitly out of scope:** predicate ontology changes (adding `REFERENCES` to `PREDICATE_REGISTRY`, plugin-registered predicates). That is a separate decision — see §9.

## 1. Motivation — three real tensions

1. **Cost / noise.** Every cognition-eligible event runs LLM phase1/phase2 **unconditionally** (`memory/l2/pipeline/extraction.py:189` calls `extract_phase1` with no skip path; the only off-switch is `cognition_eligible=False`, which also disables deterministic direct-writes). High-volume / low-signal sources pay full LLM cost for almost nothing.
   - Verified: git's L1 `content` is the **session summary** ("Worked in repo X: commit 3, merge 1") — the commit message text never reaches `event.content`, and phase1 reads `event.content` (`extraction.py` `event_window.texts = [item.content]`). So git's LLM pass can extract ≈ the repo entity, which the deterministic `COMMITTED` direct-write already produces. git phase1 is ~redundant as built.
2. **Who owns "is this worth extracting?"** The host's generic `classify_event_evidence` (`memory/evidence/policy.py`) cannot know per-source semantics (chrome: 1 visit = noise, 20 = signal; git: a session of `wip` commits = noise). The **producer (plugin)** does.
3. **L1 lean vs L2 rich.** L1 deliberately does not persist full bodies (git = summary; we likely want obsidian and others lean too, for size + privacy/retention). But good L2 extraction needs the full body.

Today's flow: `sensor → L1 → L2 (static per-sensor cognition gate) → phase1/phase2 (unconditional LLM)`.

## 2. The invariant, reframed (the core idea)

The implicit rule "L2 derives from L1" is really protecting **provenance + reproducibility**: every L2 fact carries `evidence_event_ids` back to an L1 event, and that evidence must be the *exact, stable* content that produced the fact.

Reframe the rule to what it must actually guarantee:

> **L2's input MUST be a snapshot pinned at the L1 event's capture time — NEVER a live, mutable source re-read at extraction time.**

- "Pinned" ≠ "bytes inline in the L1 row." A capture-time payload stored *by reference* (`raw_payload_ref` / `media_path`, with a retention window) still satisfies the invariant.
- Re-reading the live git repo / vault file at L2 time **violates** it: the source can be amended/rebased/edited/deleted, and L2 runs async/batched (possibly much later), so the content L2 sees ≠ the captured content → evidence ≠ claim, non-reproducible.

This reframe is what unlocks "L1 lean + L2 rich" without breaking provenance.

## 3. Proposed flow

```
sensor
  → L1 (lean durable row)  +  pinned capture-time payload (raw_payload_ref, retention-bounded)
  → promotion gate (plugin-owned decision: promote / direct_only / defer / drop)
  → L2 extraction (reads the pinned payload; deterministic direct-writes + optional LLM phase1/2)
```

The two new pieces are the **promotion gate** (§4) and the **pinned payload as an L2 content source** (§5).

## 4. Mechanism A — promotion gate (plugin-owned, per-event)

A decision point between L1 and L2 extraction. It generalizes today's static `cognition_eligible` (per-sensor class attr) into a per-event decision the *producer* can drive. Two layers:

**A1 — Declarative (host-owned; covers the common case).**
The plugin declares a promotion policy in its `SensorSpec`/metadata, e.g.:
- `{ mode: "structured_only" }` — never run the LLM; do deterministic direct-writes only.
- `{ mode: "frequency", key: "domain", threshold: N, window: W }` — defer until the key has been seen ≥N times in the window, then promote.
The **host** owns the accumulator, its storage, and idempotency. No plugin code runs mid-pipeline.

**A2 — Callback (escape hatch; for genuinely custom logic).**
`Plugin.evaluate_promotion(l1_view) -> { decision, payload_ref? }`. The plugin may keep its own state DB. The host calls it from the **async L2 batch worker**, time-bounded, with errors → a safe default (must not stall ingestion). Use sparingly; prefer A1.

**Decisions:**
- `promote` — run full L2 (direct-writes + LLM phase1/2).
- `direct_only` — do the deterministic direct-writes (entities/edges), **skip the LLM**.
- `defer` — don't extract yet; keep accumulating.
- `drop` — never extract.

**This subsumes everything we discussed:**
- `structured_only` toggle = always `direct_only`.
- chrome interest = `defer` until visit-count ≥ N, then `promote`.
- git = `direct_only` (the `COMMITTED` edge is the value; LLM adds ≈ nothing as built).

So we build **one** gate, not a separate `structured_only` flag plus a frequency feature.

## 5. Mechanism B — capture-time pinned payload as an L2 content source

- The plumbing largely exists: `SensorOutput.raw_payload_ref`, `MemoryEvent.media_path`. `screenshot_timeline` already keeps heavy originals for `original_retention_days` then deletes them — the precedent for "pin heavy payload by reference with a retention window."
- Formalize: a sensor MAY attach the full body as a **pinned payload at capture**, while L1's durable `content` stays a lean summary.
- Extend L2 window-building (`extraction.py`, currently `event_window.texts = [item.content]`) to ALSO load the referenced payload when present, so direct-write and phase1 see the full body.
- Retention: keep the payload for a configurable window; after L2 extracts (or the window elapses) the heavy payload can be dropped → lean L1 + extracted facts remain. (Privacy bonus: **extract-then-forget**.)
- **Hard rule:** the payload is written ONCE at capture (pinned). L2 NEVER re-reads the live source. If the payload is gone (retention elapsed) and the event was never extracted, L2 falls back to the lean `L1.content` — never to a live re-fetch.

## 6. Enabling contract changes

1. **Per-event eligibility override.** Today `cognition_eligible` / `SensorMemoryPolicy` is a per-sensor static class attr, and `SensorOutput` carries no per-event policy. Add a per-event promotion/eligibility signal (on `SensorOutput`, and/or produced by the gate) so the decision can vary per event. **This is the central, small change.**
2. **Promotion-gate hook** at the L2 admission point (where `l2_layer.accepts()` / the `PolicyDecision` is computed): consult A1 (declarative policy) then A2 (callback) before admitting to extraction.
3. **L2 payload read.** Extend the extraction window to load `raw_payload_ref` / `media_path` when present.
4. **Backward compatible.** A sensor that declares nothing keeps today's behavior (static `cognition_eligible`, `content = summary`, unconditional LLM).

## 7. Worked examples

- **git:** L1 lean ("Worked in repo X: N commits"); full commit messages pinned as payload; gate default = `direct_only` (`COMMITTED` always written, LLM skipped). If commit semantics are later judged worth it, switch to `promote`; L2 then reads the pinned commit text (prompt-hardened for terse messages). Note: terse-commit noise never reaches the LLM today because commit text isn't in `content` — so `direct_only` is the honest default.
- **chrome:** `VISITED`/`VIEWED` direct-written always (the fact); gate = `frequency` on domain → `defer` until ≥N visits in window, then `promote`. Interest becomes frequency-grounded, and the LLM runs only on domains that cleared the bar. (Fixes "a casual click becomes INTERESTED_IN.")
- **obsidian:** L1 lean (title + short summary); full note body pinned as payload (droppable after extraction for privacy); knowledge-folder notes `promote` (LLM mines prose); search-folder notes `direct_only` or `drop`.

## 8. Risks / traps + mitigations

1. **Double counting on re-sync / replay** → host-owned idempotent accumulation keyed by `source_item_id` / version fingerprint.
2. **Initial backfill flood** (import 30 days → thresholds cross instantly → L2 flood) → window semantics distinguish backfill vs steady-state; cap promotions per batch.
3. **Plugin code in the hot path** → A2 runs in the async L2 worker, time-bounded, errors → safe default. Prefer A1 declarative.
4. **State durability** → host-owned accumulator (A1) is more robust than a per-plugin DB; if a plugin keeps its own state (A2), it owns recovery.
5. **Provenance red line** → L2 input is ALWAYS the pinned capture-time payload or `L1.content`; NEVER a live re-read. Enforce by not exposing any live-fetch path to L2.
6. **Payload gone before extraction** (retention elapsed + deferred too long) → fall back to lean `L1.content`; never live-fetch. Tune retention vs defer windows together.

## 9. Non-goals / separate decisions

- **Predicate ontology** — adding `REFERENCES` to `PREDICATE_REGISTRY`, or a "plugins register predicates into the shared catalog" capability. Related (it's the other half of making Obsidian's structured edges land) but orthogonal to this data-flow RFC; decide separately.
- Not a rewrite of phase1/phase2 — this is a gate in front + a content-source extension.

## 10. Phasing (each phase independently shippable, backward compatible)

- **P1:** per-event eligibility override + `direct_only` / `structured_only` declarative mode. Immediate cost win for git. 
- **P2:** declarative `frequency` gate + host accumulator. Fixes chrome interest.
- **P3:** pinned-payload read in L2 + retention/drop. Enables obsidian full-body and (optionally) git commit text.
- **P4 (optional):** A2 plugin callback escape hatch.
- **Validate with data between phases:** does "promoted-only" extraction preserve recall quality while cutting LLM cost? Don't blanket-disable a source without checking its extraction actually wasn't surfacing useful recall.

## 11. Open questions

- Where exactly does the gate run — at L1-write time or in the async L2 batch worker? Frequency needs cross-event state, so likely a pre-L2 step in the worker.
- Storage for the host accumulator — reuse `target_state`, or a new table?
- How `defer` interacts with `L2BatchJob` batching and supersession.
- Should `direct_only` events still get entity-catalog upserts + facets (yes, those are deterministic) but skip phase1/phase2 (yes)? Confirm the exact cut line in `extraction.py`.

## 12. Why this is one coherent direction

It unifies the whole thread: the blunt `structured_only` toggle, the frequency gate, the git/chrome low-signal handling, and obsidian's "L1 lean but L2 needs the body" — all become the **same two mechanisms**: a producer-owned **promotion gate** (what enters L2) and a capture-time **pinned payload** (what L2 reads), bounded by one red line: *L2 never reads a live, mutable source.*
