# DTO / API Contract Compatibility Audit

Date: 2026-05-06
Scope: backend/src (Python), sdk, contracts, crates (Rust serde)
Goal: identify compatibility shims and dual-shape logic added during development that may be safe to remove before a clean release.

Legend:
- DELETE — pure dev-time shim, no on-disk or external consumer; safe to drop.
- CONSOLIDATE — keep semantics but collapse the dual path; the new shape can be made canonical.
- KEEP — coupled to persisted DB rows, on-disk traces, or external contracts; old-shape data may still exist.

---

## 1. runtime_trace/

### 1.1 `PluginIngressEventRecord` re-export shim
- **File:** `backend/src/magi/runtime_trace/__init__.py:1-34`
- **Compat:** `magi_plugin_sdk.ingress.PluginIngressEventRecord` (Protocol) is re-exported from `magi.runtime_trace` for "older plugin code that typed handlers against `magi.runtime_trace`". The persisted dataclass is renamed to `StoredPluginIngressEventRecord`.
- **Recommendation:** CONSOLIDATE — rename the import path inside backend to `StoredPluginIngressEventRecord` everywhere and require third‑party plugins to import from `magi_plugin_sdk.ingress`. The re-export is a small backward-compat seam, not coupled to data on disk; can be removed when SDK boundary is firm.

### 1.2 `trace_spans.turn_id` NOT NULL → nullable rebuild migration
- **File:** `backend/src/magi/runtime_trace/schema.py:192-239`
- **Compat:** Idempotent SQLite table-rebuild that detects the legacy `NOT NULL turn_id` shape and rewrites the table to allow `NULL`.
- **Recommendation:** KEEP — directly tied to existing on-disk SQLite trace databases; users upgrading carry the legacy shape.

### 1.3 Span attribute `result_json: None` placeholder
- **File:** `backend/src/magi/agent/execution/tool_invocation_service.py:101`
- **Compat:** Always sets `result_json: None` on the span attributes; column was added later via `ensure_trace_detail_columns`.
- **Recommendation:** CONSOLIDATE — drop the explicit `None` write once writers are confirmed; column default is fine.

### 1.4 `_event_bus` retained for backward compat in tool invocation
- **File:** `backend/src/magi/agent/execution/tool_invocation_service.py:58-62, 112-117`
- **Compat:** `self._event_bus` is "kept for backward compat; SpanCompleted publishes via container.message_bus". Also a structured `ToolError` is built only "for legacy translators that read sp.error".
- **Recommendation:** CONSOLIDATE — verify no consumers read the bus instance directly or rely on `sp.error`; drop both the field and the synthetic `ToolError` once `SpanCompleted` is the single contract.

---

## 2. chat/

### 2.1 Legacy L1 → ChatStore backfill
- **File:** `backend/src/magi/chat/migration.py:1-159`, invoked from `backend/src/magi/chat/lifecycle.py:8,30-32`
- **Compat:** `backfill_chat_store_from_legacy` reads the old `fact_events`/`chat_sessions` tables (`UserMessage`/`AIResponse` types) and re-inserts them into the new chat store on first run.
- **Recommendation:** KEEP — strictly a data-migration shim for users who already have an on-disk L1 transcript DB. Do not delete; alternatively gate behind a one-shot version flag and remove in a later release.

### 2.2 `legacy_messages` bucket in display history
- **File:** `backend/src/magi/chat/read/history_operations.py:222, 241, 304`
- **Compat:** Messages whose `turn_id` is empty fall into a `legacy_messages: list[ChatDisplayMessage]` bucket and are appended to the timeline; this exists because the migration above and pre-turn rows have no `turn_id`.
- **Recommendation:** KEEP — protects rendering of historical rows already persisted without a turn id.

### 2.3 `ChatDisplayMessage.message_kind` optional
- **File:** `backend/src/magi/chat/read/models.py:75, 93`
- **Compat:** Field is `str | None`; serialized unconditionally. Old rows lack `message_kind`.
- **Recommendation:** KEEP — read-side only, must tolerate historical persisted rows.

### 2.4 `ChatSessionSummary.history_version` default 0
- **File:** `backend/src/magi/chat/read/models.py:21`, written via `backend/src/magi/chat/store.py:121`
- **Compat:** History version increments only when `existing_session is not None`; old sessions default to 1.
- **Recommendation:** KEEP — required for legacy rows missing the column.

---

## 3. agent/task_agents/chat/

### 3.1 `IntentDecision.deep_thinking` legacy property
- **File:** `backend/src/magi/agent/task_agents/chat/contracts.py:116-119`
- **Compat:** Property derived from `thinking_depth`; comment "Legacy accessor".
- **Recommendation:** DELETE if no caller still reads `decision.deep_thinking`; otherwise CONSOLIDATE to use `thinking_depth` enum directly in callers.

### 3.2 `resolve_event_bus` thin wrapper
- **File:** `backend/src/magi/agent/task_agents/chat/postprocess/utils.py:48-58`
- **Compat:** "Backward-compatible thin wrapper. Phase 6 moved the canonical implementation to `magi.runtime_trace.span_publisher`."
- **Recommendation:** DELETE — switch the few in-package callers to import `from ...runtime_trace.span_publisher import resolve_event_bus`. No persistence coupling.

### 3.3 `ContextDecision.deep_thinking` parallel constructor argument
- **File:** `backend/src/magi/tools/context_routing/models.py:13-43`
- **Compat:** Constructor accepts both `deep_thinking: bool` and `thinking_depth`; if `thinking_depth is None` falls back to `deep_thinking`. Property `deep_thinking` retained as "Legacy accessor".
- **Recommendation:** CONSOLIDATE — drop the `deep_thinking` constructor kwarg and property after auditing call-sites (router/decider modules).

### 3.4 `BackgroundTaskRequest.pending_message_id` legacy detach paths
- **File:** `backend/src/magi/agent/background/contracts.py:88-96`
- **Compat:** "legacy detach paths leave it `None`" — both shapes accepted.
- **Recommendation:** KEEP for now (request shape may be stored in queue records); revisit when all detach paths are unified.

---

## 4. memory/ (related, not in primary scope but shows the pattern)

### 4.1 `_from_sensor_legacy` translator
- **File:** `backend/src/magi/memory/event_translation.py:123-161`, dispatch at line 363
- **Compat:** Two-branch sensor translation: full-context (C producer) vs. lean A-era `SensorEventEmitted`. Comment: "Will be removed when all producers upgrade."
- **Recommendation:** CONSOLIDATE — verify no in-tree producer still emits the lean shape; once removed, delete `_from_sensor_legacy`. No on-disk coupling: this is event-time translation.

### 4.2 Memory ingestion `event_id` vs legacy `id`
- **File:** `backend/src/magi/memory/store_ingestion.py:182-185`
- **Compat:** Reads `payload.get("event_id") or payload.get("id")` to accept both envelope-named and legacy-named keys.
- **Recommendation:** CONSOLIDATE — emit only `event_id` and drop the `id` fallback once producers are audited.

### 4.3 Hybrid retrieval `_LEGACY_MODE_MAP` and `recall_intent` migration
- **File:** `backend/src/magi/memory/hybrid_retrieval/router.py:1-56`
- **Compat:** Two maps — `_RECALL_INTENT_TO_MODE` (old `recall_intent` kwarg → new `query_mode`) and `_LEGACY_MODE_MAP` (deprecated mode names → unified). `build_query` pops `recall_intent`.
- **Recommendation:** CONSOLIDATE — these are call-site shims for tool args; once tool prompt schemas no longer mention the legacy names, delete both maps and the kwarg pop.

### 4.4 `tom_trait_assertions_legacy` rebuild
- **File:** `backend/src/magi/memory/l2/storage/migrations.py:115-245`
- **Compat:** Renames the old table to `..._legacy`, creates new schema, copies+transforms rows (incl. `trait_name → trait_family` mapping) and drops the legacy table.
- **Recommendation:** KEEP — irreplaceable on-disk migration; acts on user databases.

### 4.5 L2 graph candidate "legacy/unified extraction paths" merge
- **File:** `backend/src/magi/memory/l2/pipeline/validation/graph_candidates.py:19-40`
- **Compat:** Docstring: "Merge and prepare graph candidates from legacy/unified extraction paths." Accepts multiple groups.
- **Recommendation:** CONSOLIDATE — once the legacy extraction path is gone, the merge becomes a no-op identity step that can be inlined.

---

## 5. config/

### 5.1 `Config = AppConfig` type alias
- **File:** `backend/src/magi/config/models.py:818-819`, re-exported `backend/src/magi/config/__init__.py:77, 161`
- **Compat:** Plain alias for backward compatibility.
- **Recommendation:** DELETE if no external code imports `Config`; otherwise KEEP as a one-line stable alias.

### 5.2 `_prune_deprecated_memory_settings`
- **File:** `backend/src/magi/config/loader_file_ops.py:186-201`, used at `loader_persistence.py:48`
- **Compat:** Strips `agent.memory.async_embeddings` and `agent.memory.embedding.backend` from on-disk YAML before validation.
- **Recommendation:** KEEP — operates on user YAML files.

### 5.3 Plugin layout migration: drop `agent_data.llm` & promote chrome-history
- **File:** `backend/src/magi/config/plugin_layout.py:149-203`
- **Compat:** Removes obsolete `llm` block from `agent.yaml`, copies legacy `plugins.packages` to the new index, promotes builtin chrome-history defaults.
- **Recommendation:** KEEP — touches user config files on disk.

---

## 6. personality/

### 6.1 `needs_bootstrap_init` alias for `needs_bootstrap`
- **File:** `backend/src/magi/personality/bootstrap_service.py:136-138`
- **Compat:** `needs_bootstrap_init` is a backward-compatible alias; called internally at line 151 and from API tests (`backend/tests/api/test_personality_bootstrap_api.py`).
- **Recommendation:** CONSOLIDATE — rename callers (API + tests + the self-call at line 151) to `needs_bootstrap`, drop the alias. JSON response field at `test_personality_bootstrap_api.py:72` (`"needs_bootstrap_init": True`) is the externally observable contract — decide whether to rename it before deleting.

---

## 7. llm/

### 7.1 `_coerce_thinking_depth(thinking_depth, disable_thinking)`
- **File:** `backend/src/magi/llm/provider_bridge/__init__.py:31-45`, used by `chat`, `chat_response`, `chat_with_tools`
- **Compat:** Resolves `ThinkingDepth` from new param or legacy `disable_thinking: bool`.
- **Recommendation:** CONSOLIDATE — once all callers in-tree pass `thinking_depth`, drop `disable_thinking` from the signatures and remove the helper. Confirm SDK/plugin callers.

### 7.2 `_disabled_thinking_extra_body` `.. deprecated::`
- **File:** `backend/src/magi/llm/provider_bridge/options.py:50-58`
- **Compat:** Marked deprecated; supplanted by `_build_glm_thinking_params(ThinkingDepth)`.
- **Recommendation:** DELETE if unused; `grep` for callers and remove.

### 7.3 `OpenAIAdapter._apply_glm_thinking_control` `.. deprecated::`
- **File:** `backend/src/magi/llm/openai.py:75-100`
- **Compat:** "Remains only for direct adapter calls that bypass the bridge."
- **Recommendation:** DELETE if no in-tree direct adapter callers remain; bridge is the canonical path.

### 7.4 `api_base` dual-arg fallback in OpenAI/Anthropic adapters
- **File:** `backend/src/magi/llm/openai.py:21-55`, `backend/src/magi/llm/anthropic.py:25-46`
- **Compat:** Both adapters accept `base_url` and legacy `api_base`; `api_endpoint = base_url or api_base`.
- **Recommendation:** CONSOLIDATE — config writers emit `base_url` only; remove `api_base` after a release window. Coupled to user-edited config YAML, so handle via `_prune_deprecated_memory_settings`-style normalization rather than bare deletion.

### 7.5 `OpenAIAdapter.DEFAULT_EMBEDDING_MODEL` "Legacy fallback"
- **File:** `backend/src/magi/llm/openai.py:21-22`
- **Compat:** Class constant retained "for compatibility references"; runtime now uses scenario-selected model.
- **Recommendation:** DELETE if no external import — it's only a class attribute.

### 7.6 Legacy XML tool-call parser
- **File:** `backend/src/magi/llm/parsers/tool_call_parser.py` (whole file), `backend/src/magi/llm/parsers/__init__.py:4,7,8`, used by `backend/src/magi/llm/provider_bridge/responses.py:271-285`
- **Compat:** Parses `<tool_call>...</tool_call>` blocks from plain text as a fallback path when the model returns no structured tool calls. IDs minted as `legacy_call_{n}`.
- **Recommendation:** KEEP for now — exercised at runtime against models that still emit XML-shaped tool calls (e.g. older GLM routes). Re-evaluate once provider matrix is pinned.

---

## 8. api/ (router shim)

### 8.1 `legacy_messages_module()` import-time delegate
- **File:** `backend/src/magi/api/routers/messages_common.py:14-15`, used by `messages_dispatch.py`, `messages_content.py`, `messages_sessions.py` (e.g. `messages_content.py:13,26,64,93,125,149`); analogous patterns: `plugins_core_routes.py`, `plugins_install_routes.py`, `personality_config_routes.py`.
- **Compat:** New modular routers re-import the original monolithic `magi.api.routers.messages` (and `plugins`/`personality_config`) module via `import_module` and call private helpers (`legacy._require_session_id`, `legacy._get_chat_attachment_ingestion_service`, etc.). The local name `legacy` is purely the variable for this shim.
- **Recommendation:** CONSOLIDATE — move the still-used helpers (`_require_session_id`, `_get_chat_attachment_ingestion_service`, `get_chat_read_service`) into `messages_common.py` (or a new `_helpers.py`) and import them directly. Eliminates the runtime `import_module` indirection and the misleading "legacy" name.

---

## 9. SDK

### 9.1 `PluginManifest.plugin_id = Field(alias="id")` + `populate_by_name`
- **File:** `sdk/src/magi_plugin_sdk/contracts.py:164-185` (also duplicated in `sdk/build/lib/magi_plugin_sdk/contracts.py:133, 151`)
- **Compat:** The on-disk plugin manifest YAML uses `id`; the Python attribute is `plugin_id`. `populate_by_name = True` allows both.
- **Recommendation:** KEEP — `id` is the public manifest contract used by external plugin authors.

### 9.2 `sdk/build/` shadow copy
- **File:** `sdk/build/lib/magi_plugin_sdk/*` mirrors `sdk/src/magi_plugin_sdk/*`
- **Compat:** Build artifact, not a compatibility shim.
- **Recommendation:** Out of scope for this audit (build hygiene, not DTO compat).

---

## 10. crates/ (Rust serde)

Search for `#[serde(rename = …)]`, `#[serde(alias = …)]`, multiple-shape detection:
- **File:** `crates/magi-gateway/src/ipc/protocol.rs:17,25` — only `skip_serializing_if = "Option::is_none"` (compactness, not compat). No `serde(rename)` / `serde(alias)` present anywhere under `crates/`.
- **Recommendation:** No findings; nothing to remove.

---

## 11. contracts/

- `contracts/api/gateway_routes.json` and `contracts/sqlite/gateway_writes.json` are descriptive contracts; they do not contain alias/version logic.
- **Recommendation:** No DTO compat shims here.

---

## Summary by recommendation

| Verdict | Items |
|---|---|
| DELETE (safe dev-time shim) | 3.2, 5.1 (if no external import), 7.2, 7.3 (if confirmed unused), 7.5 |
| CONSOLIDATE (collapse dual path) | 1.1, 1.3, 1.4, 3.1, 3.3, 4.1, 4.2, 4.3, 4.5, 6.1, 7.1, 7.4, 8.1 |
| KEEP (persisted/external) | 1.2, 2.1, 2.2, 2.3, 2.4, 3.4, 4.4, 5.2, 5.3, 7.6, 9.1 |

The KEEP cluster is dominated by anything that touches user SQLite databases (`runtime_trace`, `chat`, `memory/l2`), user-edited YAML, or external plugin manifests. The CONSOLIDATE items are mostly internal call-site shims that became safe once their producers were audited; removing them requires a quick caller sweep but no data-migration dance. The DELETE items are isolated wrappers and unused class attributes.
