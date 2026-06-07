# Obsidian Vault Sensor — Design Spec

- **Status:** Draft (design approved in brainstorming; pending spec review)
- **Date:** 2026-06-07
- **Plugin id:** `obsidian-vault` (lives in the `magi-plugins` repo, installed to `~/.magi/plugins/`)
- **Contribution type:** Sensor (read-only)

## 1. Summary

A Sensor plugin that folds an Obsidian vault into Magi's memory. It periodically scans
the vault, and for each new/changed note emits one `SensorOutput` carrying the note's
**full current text** plus its structured signals (`[[wikilinks]]`, `#tags`, YAML
frontmatter). This lands as **one canonical L1 event per note** (superseded on re-ingest)
and, when the note is in a cognition-eligible folder, drives **L2 extraction** of
entities / typed relations / state assertions — each fact carrying provenance
(`evidence_event_ids`) back to the source note.

The vault is **one source among many** (git, calendar, screen, chat). The differentiator
is not "AI inside Obsidian" but **cross-source memory**: the `[[Alex]]` in a note resolves
to the same Alex entity your calendar and chat mention, and recalled facts point back to
the exact note.

## 2. Competitive landscape & positioning

The Obsidian × AI space today clusters into four buckets, plus one adjacent rival:

1. **In-vault semantic search / link discovery** — Smart Connections (~4.4k★), Smart
   Graph. On-device embeddings (no API key, offline), block-level, surfaces semantically
   related/unlinked notes. Solves "show connections I didn't make."
2. **In-vault chat / RAG + writing assistant** — Copilot for Obsidian (~5.8k★), Text
   Generator, Smart Composer. Side-panel chat, Vault QA (RAG), inline AI writing, BYO key,
   can run local models. Solves "ask my vault" and "help me write."
3. **Auto-organization / auto-tagging** — Note Companion, AI Tagger, LLM Tagger (Ollama).
   Auto-tags frontmatter, suggests folders/titles, moves notes. Solves "keep my vault tidy."
4. **Expose vault to an external agent** — obsidian-claude-code-mcp, Local REST API + MCP,
   or Claude Desktop's filesystem connector ("three clicks"). Solves "let an external agent
   read/write my vault on demand."

**Adjacent rival — cross-source AI memory:** Saner.AI (notes+email+calendar+Slack+Drive),
Reflect (notes+calendar), Mem (email+calendar+Slack → structured knowledge). These do
proactive multi-source memory, **but they want to *be* your note app** (cloud SaaS, migrate
your notes in), not augment an existing Obsidian vault, and are not local-first.

**Common thread:** all are Obsidian-centric and on-demand — the vault is the universe, AI is
a feature inside it (or pointed at it), retrieval happens when you ask.

### Where Magi is differentiated (must be made *visible*)

- **Vault as one input into a unified, cross-source memory of *you*** — no Obsidian plugin
  links your notes to your git commits, calendar, screen, and chat. Magi does.
- **Persistent, extracted, inspectable knowledge graph with provenance** (L2
  entities/relations/assertions + `evidence_event_ids`) vs Smart Connections' *similarity*
  graph (embeddings, not facts) and Copilot's *ephemeral* query-time RAG (nothing persists).
- **Proactive / passive** — the vault becomes part of what the companion knows over time
  (persona, timeline, proactive recall) vs reactive "open chat and ask."
- **Cross-source entity identity** — `[[Alex]]` resolves to the same Alex entity as chat/calendar.
- **Local-first**, and L2 can run on a local model (Ollama).

### Where Magi is weaker (accepted)

- **No in-editor experience.** We are read-only ingestion; we do not help you *write* in
  Obsidian. That lane (Copilot/Text Generator) is saturated and is explicitly **not ours**.
- **Maturity/community** vs Copilot/Smart Connections.
- **Zero-setup local search.** Smart Connections needs no API key and is more private for
  pure "find related notes." Our L2 extraction wants an LLM (cost/privacy) — mitigated by
  Ollama support and by the search/embedding path being L1-only and local.
- **"Why not just the MCP filesystem connector?"** is the floor competitor. We beat it on
  *persistence + cross-source + timeline + proactive recall*, not on "read my notes." This
  must be obvious from the first demo.

### Positioning one-liner (for launch copy)

> Other Obsidian AI tools live inside your vault and answer when asked. Magi folds your
> vault into a local, cross-source memory — linking your notes to your code, calendar, and
> screen — and remembers, with every fact traceable back to the source note.

## 3. Goals / Non-goals (MVP)

**Goals**
- Read an Obsidian vault and ingest notes into L1 as canonical current-state events.
- Extract structured signals (wikilinks, tags, frontmatter) and, for cognition-eligible
  folders, drive L2 entity/relation/assertion extraction with provenance.
- Make cross-source entity resolution + provenance-linked recall a first-class, demoable outcome.
- Local-first; opt-in; privacy-forward.

**Non-goals (MVP)**
- No writing back to the vault (pure Sensor; read-only).
- No real-time filesystem watcher (interval polling only).
- No deletion/rename reconciliation (moved/renamed notes leave stale records; documented).
- No Tool contribution ("save to vault", "search my vault on command") — a separate future plugin.
- No backend change unless we adopt Option Y (§7).

## 4. Architecture & data flow

`Plugin.get_sensors()` → one `ObsidianVaultSensor`, following the
`chrome-history` / `git-activity` interval+cursor pattern.

```
[interval scan vault/*.md]
   → for each new/changed note: build SensorOutput (full text + structured signals)
   → L1: one canonical MemoryEvent per note (supersede on re-ingest)
   → L2 (if cognition_eligible): Phase1 entities + fact claims → Phase2 resolve + write
        knowledge edges / ToM assertions, each with evidence_event_ids → source note
```

- **Platforms:** macOS, Windows (pure file reads).
- **Capability:** `filesystem_read` scoped to the configured vault path.

## 5. L1 event mapping (`build_output`)

Per the SDK `SensorOutput` contract (`sdk/src/magi_plugin_sdk/sensors.py`):

| SensorOutput field | Value |
|---|---|
| `source_type` | `"obsidian_vault"` |
| `source_item_id` | frontmatter UID (`id`/`uid`) if present, else vault-relative path |
| `occurred_at` | note file mtime |
| `captured_at` | scan time |
| `activity` | source=`obsidian`, action=`created`\|`edited`, object=`note`; qualifiers: `word_count`, `wikilink_count`, `tag_count` |
| `narration.body` | full note markdown (frontmatter parsed out into structured fields) |
| `narration.title` | note title (frontmatter `title` → H1 → filename) |
| `content_blocks` | `text`(body) + one `wikilink` block per link + one `tag` block per tag |
| `tags` | note tags (frontmatter + inline `#tags`) |
| `entities` | wikilink targets + the note itself; `alias_signals` from frontmatter `aliases` |
| `provenance` | `{ vault, file_path, aliases }` |
| `domain_payload` | `{ wikilinks, frontmatter }` |

**Memory policy** (`SensorMemoryPolicy`):
`memory_domain="user_authored"`, `ingest_target="l1_only"`, `retention_class="permanent"`
(authored, not compressible), `importance_bias≈0.6`, `author_type="user"`,
`content_type="text"`, `cognition_eligible` = (note folder is a knowledge folder — see §7).

## 6. Supersession model

`source_item_id` is a stable note identity; `idempotency_key` derives from it. Re-ingesting a
changed note **updates the same canonical L1 record** → exactly one current-state row per
note, no near-duplicate bloat. L2 re-extraction supersedes prior facts via the existing
evidence/conflict-resolution mechanism.

**Caveat (non-goal to fix in MVP):** a path-based id changes on move/rename, creating a new
record and leaving the old one stale. Mitigation: prefer a frontmatter UID. Deletion/rename
reconciliation is deferred.

## 7. Cognition gating

**Constraint (verified):** `cognition_eligible` is **all-or-nothing**. `l2_layer.py`'s
`accepts()` returns `False` when `not event.cognition_eligible`, and the structured-hint
processing (`l2/pipeline/validation/structured_*_hints.py`) lives *inside* that gated
pipeline. So "structured signals always, free-prose gated" is **not** achievable with the
single flag without a backend change.

### Option X — MVP (chosen, zero backend change)

The vault is partitioned by folder into three tiers:

- **Knowledge folders** (default: whole vault minus the exclusions below) →
  `cognition_eligible=True` → full L2 (structured edges + free-prose facts).
- **Search-only** (`cognition_exclude_folders`, default e.g. `Clippings/`, `References/`) →
  `cognition_eligible=False` → **L1 only** (full-text searchable + embeddings, but no graph
  edges / extracted facts).
- **Ingest-exclude** (`exclude_folders`, default `.obsidian/`, `.trash/`, `Templates/`,
  attachment dirs) → not read at all (privacy).

Consequence: search-only folders contribute no knowledge-graph edges (acceptable / desirable
for clippings/quotes — keeps borrowed content from being asserted as the user's beliefs,
the same failure mode that made `screenshot_timeline` set `cognition_eligible=False`).

### Option Y — deferred fast-follow (needs backend change)

Add a `structured_only` cognition mode so search-only folders still contribute high-confidence
link/tag edges while skipping LLM free-prose extraction. Requires extending the L2 layer to
admit structured-hint processing independent of the `cognition_eligible` gate. Tracked as a
follow-up; not in MVP.

## 8. L2 extraction (what becomes knowledge, and why it is not a summary)

L2 produces **discrete facts with provenance**, never prose summaries:

- **Structured (high confidence):** `[[wikilink]]` → `references` edge; `#tag` → `tagged_as`;
  frontmatter keys → attributes / state assertions.
- **Free prose (cognition-eligible folders only):** existing Phase1/Phase2 LLM extraction of
  entities + `L2Phase1FactClaim` triples, integrated with conflict resolution.
- **Provenance:** every `L2KnowledgeEdgeWrite` / `L2TomAssertionWrite` carries
  `evidence_event_ids` pointing to the source note's L1 event. Recall surfaces "you wrote
  this in note X (open it)" — a pointer + cross-reference, not a re-summary. The vault stays
  the source of truth; the full text already lives verbatim in L1.
- **Cross-source resolution (first-class):** wikilink targets and note aliases feed the L2
  entity catalog / resolution so a note's `[[Alex]]` merges with the Alex entity seen in
  chat/calendar/git. This is the demoable differentiator — it must be exercised by tests and
  surfaced in recall, not left implicit.

## 9. Sync mechanics

- `SensorSpec.sync_mode = interval` (configurable, default ~10 min) + a per-file mtime cursor
  in `sensor_state.db`. Each scan walks `*.md` and ingests files with `mtime > cursor`.
- A manual "Sync now" action (`PluginSettingsActionSpec`) for on-demand refresh.
- Alternative considered: a real-time fs-watcher (fsevents/watchdog) — more deps/complexity,
  deferred.

## 10. Settings, permissions, i18n

**Settings (`ExtensionFieldSpec`)**
- `vault_path` — `path`, required.
- `exclude_folders` — `tags`/list (default: `.obsidian`, `.trash`, `Templates`, attachments).
- `cognition_exclude_folders` — `tags`/list (default: `Clippings`, `References`).
- `sync_interval_min` — `number` (default 10).
- `enabled` — `switch`, **default false** (opt-in, privacy-forward like `screenshot_timeline`).

**Permissions:** `filesystem_read` scoped to `vault_path`.

**i18n:** plugin-scoped schema — strings nested under `obsidian-vault.fields.*` /
`obsidian-vault.actions.*`; activity facets carry `i18n_key` + fallback. Ship `i18n/en.json`
and `i18n/zh-CN.json`.

## 11. Privacy framing (launch-facing)

Off by default; all reads are local; the vault is never uploaded by Magi. The only external
exposure is whatever the **user's configured LLM provider** sees during L2 extraction — and
L2 can run on a local model (Ollama). The plugin `description` must state this plainly
(do not repeat the `screenshot_timeline` mistake of a scary one-liner).

## 12. Acceptance criteria ("done when")

- Pointing the sensor at a vault ingests notes into L1 as one canonical record per note;
  editing a note updates that same record (no duplicates).
- `[[wikilinks]]`, `#tags`, and frontmatter from knowledge folders produce L2 edges/assertions
  with `evidence_event_ids` back to the note.
- Search-only folders are full-text searchable but produce no graph edges.
- A note's `[[Alex]]` resolves to the same Alex entity surfaced by another source (cross-source
  resolution demonstrated by a test).
- Recall of a vault-derived fact can be traced back to the originating note.
- Off by default; enabling requires explicit consent; excluded folders are never read.

## 13. Open questions / future work

- Option Y (`structured_only` cognition mode) — backend change.
- Tool contribution: "save to vault" / "search my vault on command" (separate plugin).
- Real-time fs-watcher.
- Deletion / rename reconciliation (tombstones, UID tracking).
- Whether L1-only embeddings should power a vault full-text RAG recall path (overlaps Copilot Vault QA).
