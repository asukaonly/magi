# Frontend Compatibility Audit

Scope: `/Users/asuka/code/magi/frontend`. Focused on `src/api/`, `src/domain/chat/`, `src/__tests__/`, with crosschecks in `src/realtime/`, `src/stores/`, and shared utilities.

This audit lists every compatibility / fallback / migration surface I could find. For each item I cite `file:line`, describe it briefly, and recommend DELETE / CONSOLIDATE / KEEP. KEEP is reserved for code that handles data the **current backend still emits** or that the **user's stored data still contains**.

Note: I did not find any feature flags (no `VITE_FEATURE`, `useFeatureFlag`, or similar) gating old vs new UI paths in the frontend. I also did not find browser polyfills beyond defensive `crypto.randomUUID` guards.

---

## 1. API layer (`src/api/`)

### 1.1 Gateway-envelope unwrapping (`unwrapGatewayPayload`)

- `frontend/src/api/client.ts:239-244` — `unwrapGatewayPayload<T>` accepts both an `ApiResponse<T>` envelope (`{success, message, data}`) and a bare `T`, returning whichever is provided. This is a tolerance layer for endpoints that historically returned the envelope vs. those that now return raw payloads.
- Every call site in `src/api/modules/*.ts` (e.g. `messages.ts:231, 242, 249, 264, 279, 351, 371, 384, 394, 405`, `memory.ts:371`, `personas.ts`, etc.) wraps responses with this helper.
- The `api.get/post/...` helpers in `client.ts:320-337` already type-assert to `ApiResponse<T>` and return `response.data`, so an additional unwrap of `{success, data}` here is *only* needed when a particular route may return a raw payload directly. The pluginsApi test (`__tests__/pluginsApi.test.ts:53`) explicitly states "still unwraps legacy success envelopes".

Recommendation:
- KEEP for now. The backend gateway is mid-transition: some routes still return `{success, data}` envelopes (proven by `pluginsApi.test.ts:19-77` covering both shapes). Once the gateway is unified, this becomes deletable.
- Action item once backend is fixed: remove `unwrapGatewayPayload`, simplify `api.get/...` to return raw `T`.

### 1.2 `ChatHistoryMessage.kind` field

- `frontend/src/api/modules/messages.ts:74` — `kind?: 'user' | 'assistant' | 'status' | null;` lives alongside `role` (`messages.ts:70`).
- Backend still produces `kind` (see `backend/src/magi/chat/read/models.py:96`) so both fields are part of the live wire contract.

Recommendation: KEEP. Backend currently emits both. (Could be CONSOLIDATEd by the backend into a single field, but that is a backend cleanup item, not frontend.)

### 1.3 `personasApi` "legacy endpoints, still active" comment

- `frontend/src/api/modules/personas.ts:380` — comment "Personality generation & bootstrap (legacy endpoints, still active)".
- The endpoints (`/personality/generate`, `/personality/generation-jobs`) are still consumed (e.g. by onboarding / personality generation flow).

Recommendation: KEEP. Comment is misleading — they are not deprecated. CONSOLIDATE: rewrite the comment to drop "legacy" since these are the live endpoints.

### 1.4 `memoryApi` "Legacy API object for backward compatibility" comment

- `frontend/src/api/modules/memory.ts:373` — comment "Legacy API object for backward compatibility" sits above the only exported `memoryApi`. There is no newer object that this is "fallback for"; it is the active singleton consumed across the memory pages.

Recommendation: CONSOLIDATE. Delete the misleading comment. The object itself is in active use; the comment is a leftover from a refactor.

### 1.5 `PersonalityConfig as RuntimePersonalityConfig` re-export alias

- `frontend/src/api/index.ts:29` — re-exports `PersonalityConfig` from `config` module under the alias `RuntimePersonalityConfig`, while `personas.ts` exports its own `PersonalityConfig` (`api/index.ts:46`).
- The alias exists because two modules define a same-named type. `RuntimePersonalityConfig` is the runtime/system config flavor; the unaliased `PersonalityConfig` is the persona schema.

Recommendation: KEEP. The alias resolves a real name collision, not a legacy migration. (Could be CONSOLIDATEd by renaming the runtime type at source for clarity, but not safe to remove blindly.)

### 1.6 401 redirect to `/login`

- `frontend/src/api/client.ts:286-291` — `localStorage.removeItem('auth_token'); window.location.href = '/login'`.
- The desktop app uses `X-Magi-Session-Token` (`client.ts:266-268`); there is no `/login` route in the SPA router and `auth_token` is only ever read, never written. This is dead code from an earlier auth model.

Recommendation: DELETE. No `/login` route exists; `auth_token` is never set anywhere in the codebase. The whole `auth_token` read at `client.ts:260-263` and the 401 handler can go.

---

## 2. Domain chat (`src/domain/chat/`)

### 2.1 Dual camelCase + snake_case tolerance in `normalizeTurnUxPlan`

- `frontend/src/domain/chat/state.ts:392-414` — accepts both `assistantSurfaceMode|assistant_surface_mode`, `interimText|interim_text`, `thinkingIndicator|thinking_indicator`, `traceDisplayMode|trace_display_mode`, `reactionStyle|reaction_style`, `allowTraceCollapse|allow_trace_collapse`.
- Realtime payloads from the backend use snake_case (e.g. `store-projection.ts:80` reads `payload.ux_plan`). The camelCase branch only fires when the plan is read back from a frontend-cached value.

Recommendation: CONSOLIDATE to snake_case only after confirming no in-flight payload uses camelCase. A quick `grep -r "assistantSurfaceMode" backend/` shows backend produces snake_case. Frontend is the only emitter of camelCase (e.g. tests). Likely safe to DELETE the camelCase fallbacks — but verify trace persistence does not store the camelCase shape. (Tests at `chatTraceState.test.ts:735, 763, 798, 838, 916` all pass camelCase, so removing it requires test updates.)

### 2.2 `message.kind || message.role` fallback in `normalizeHistoryMessages`

- `frontend/src/domain/chat/state.ts:421` — `const kind = (message.kind || message.role) as ChatMessageKind`.
- Backend now always emits `kind` (`backend/src/magi/chat/read/models.py:96`). The fallback to `role` exists for very old persisted history rows that lacked `kind`.

Recommendation: KEEP. Cheap defensive fallback for legacy persisted SQLite history that may predate the `kind` column. Removing it requires a confirmed migration of the chat history DB.

### 2.3 `message.trace_summary as ExecutionTraceSummary | undefined`

- `frontend/src/domain/chat/state.ts:422` — type assertion is a TypeScript escape hatch, not a runtime fallback. Not a compat issue.

Recommendation: KEEP. Pure typing.

### 2.4 Second-vs-millisecond timestamp normalization

- `frontend/src/domain/chat/timestamps.ts` (used at `state.ts:428`, test at `__tests__/chatTraceState.test.ts:1185-1197`) — normalizes second-based timestamps to ms.
- Backend now emits ms; older history rows may have second-based timestamps. The test explicitly verifies this conversion.

Recommendation: KEEP. Persisted user history may still contain second-based timestamps.

### 2.5 Trace summary shape duplication (snake_case input → camelCase normalized)

- `frontend/src/domain/chat/state.ts:172-216` (`normalizeTraceSummary`), `218-229` (`normalizeTraceNode`), `370-390` (`normalizeTraceSnapshot`).
- This is the standard wire-shape adapter pattern, not a legacy adapter — backend uses snake_case JSON, frontend uses camelCase types.

Recommendation: KEEP.

### 2.6 `toExecutionTraceSummary` reverse projection (camelCase → snake_case)

- `frontend/src/realtime/store-projection.ts:31-64` — converts the normalized camelCase summary back to snake_case `ExecutionTraceSummary` only to feed `useChatTraceStore.upsertSummary`, which then re-normalizes on read.
- This round-trip exists because `useChatTraceStore` was originally typed against the wire shape.

Recommendation: CONSOLIDATE. Change `chat-trace` store to accept `NormalizedExecutionTraceSummary` directly and delete `toExecutionTraceSummary`. Pure architectural cleanup, no behavior change.

### 2.7 `applyAgentResponse` rhythm-segment "canonical compatibility" branch

- `frontend/src/domain/chat/state.ts:737-744, 762-773` — when a turn already has rhythm segments, a later final-only payload (no `messageId`, no `messageKind`) is suppressed and only its trace summary is folded in.
- Test at `__tests__/chatTraceState.test.ts:55-85` ("keeps rhythm segments when the canonical compatibility event arrives later") documents this as a backend that emits both rhythm segments AND a canonical full message.

Recommendation: KEEP. Backend still emits the canonical event after rhythm segments per the test; removing this would cause duplicate text in the UI. Re-evaluate once backend stops emitting the legacy canonical full-message event for rhythm turns.

### 2.8 `presentation.ts` barrel re-export

- `frontend/src/domain/chat/presentation.ts:1-3` — barrel that re-exports `presentation.types`, `presentation.control`, `presentation.execution`, `presentation.timeline`. 28 import sites across the codebase.

Recommendation: KEEP. Active organization, not legacy.

---

## 3. Realtime / store projection (`src/realtime/`, `src/stores/`)

### 3.1 `payload.persona_id || payload.personaId` dual-key reads

- `frontend/src/realtime/store-projection.ts:77, 136` — accepts both snake_case and camelCase `persona_id`.
- Backend always emits `persona_id`. The camelCase fallback has no known emitter.

Recommendation: DELETE (or at minimum CONSOLIDATE to `payload.persona_id` only after a quick `grep` of backend emit sites confirms no camelCase variant).

### 3.2 `content_delta` / `is_final` legacy stream-text fallback

- `frontend/src/realtime/store-projection.ts:191-207` — when the structured `streamEvent` did not match `text_delta`/`text_flush`/`reasoning_delta`/tool-call, fall back to raw `payload.content_delta` + `payload.is_final` to drive `appendStreamTextDelta` / `appendStreamTextFlush`.
- Test at `__tests__/realtimeProvider.test.tsx:369-405` is named "keeps the legacy content-delta fallback for streaming text chunks" and explicitly verifies this path.

Recommendation: KEEP for now (test name says "keeps the legacy" — implying the writer side has not yet migrated all chunk emitters to structured `streamEvent`). DELETE candidate once `normalizeRealtimeStreamEvent` covers every code path the backend emits. Re-audit after the backend phase-5 refactor (recent commit `2782ed42 refactor(llm): delete legacy LLM_CALL_COMPLETED chain (phase 5)`) settles.

---

## 4. Storage / migration code

### 4.1 `auth_token` localStorage reads/writes

- `frontend/src/api/client.ts:260, 288`, `frontend/src/constants/app.ts:54`. No code path writes `auth_token` anywhere; the value is only read and removed.

Recommendation: DELETE. Dead key. (See 1.6.)

### 4.2 `desktop-shell-sidebar-collapsed` storage cleanup test

- `frontend/src/__tests__/chatShell.test.tsx:104-111` — test "does not expose deprecated sidebar collapse state anymore" asserts the store has no `sidebarCollapsed`/`setSidebarCollapsed`/`toggleSidebarCollapsed` properties and that `localStorage` has no `desktop-shell-sidebar-collapsed` key.
- This is a regression test confirming the property was removed.

Recommendation: KEEP. Cheap regression guard. Could be deleted, but it has near-zero cost.

Note: there is no migration code that *removes* the old `desktop-shell-sidebar-collapsed` key on app start — it is simply orphaned in user storage. If clean-release matters, consider adding a one-shot migration in `App.tsx`/`main.tsx` to `localStorage.removeItem('desktop-shell-sidebar-collapsed')`. Otherwise stale users keep the dead key forever.

### 4.3 `magi_onboarding_state` STORAGE_KEY duplication

- Defined twice: `frontend/src/components/onboarding/OnboardingFlow.tsx:28` and `frontend/src/pages/Onboarding.tsx:8`. `Onboarding.tsx:32` also calls `localStorage.removeItem(STORAGE_KEY)` on completion.

Recommendation: CONSOLIDATE. Move into `constants/app.ts` (already has `ONBOARDING_COMPLETED` at `app.ts:57`); not a legacy issue but a duplication issue.

---

## 5. Tests (`src/__tests__/`)

### 5.1 `pluginsApi.test.ts:53-77` "still unwraps legacy success envelopes"

- Tests both unwrapped and `{success, data}`-wrapped responses from `/plugins/.../resource`. As long as `unwrapGatewayPayload` exists (1.1), this test must stay.

Recommendation: KEEP while 1.1 remains; DELETE together with 1.1.

### 5.2 `realtimeProvider.test.tsx:369-405` "keeps the legacy content-delta fallback"

- Pinned regression test for 3.2.

Recommendation: KEEP while 3.2 remains; DELETE together.

### 5.3 `chatShell.test.tsx:104-111` "deprecated sidebar collapse state"

- See 4.2.

Recommendation: KEEP (or DELETE if you trim regression-only tests; cost is negligible).

### 5.4 Tests passing camelCase ux-plan keys

- `__tests__/chatTraceState.test.ts:735, 763, 798, 838, 916, 954, 977` — exclusively use camelCase ux-plan keys (`assistantSurfaceMode`, `traceDisplayMode`, etc.).
- These tests are currently the *only* exercise of the camelCase branch flagged in 2.1.

Recommendation: If 2.1 is DELETEd, update these tests to use snake_case (matching what backend actually emits). Otherwise KEEP.

---

## 6. Other findings (not in heavily-modified areas, but adjacent)

### 6.1 Two unrelated `STORAGE_KEY = 'magi-theme-mode'` vs `'magi_theme'`

- `frontend/src/stores/theme.ts:11` uses `'magi-theme-mode'` while `frontend/src/constants/app.ts:56` defines `THEME: 'magi_theme'`. Different keys for the same concept.

Recommendation: CONSOLIDATE. Pick one canonical key; if migrating, add a one-shot `localStorage.removeItem('magi_theme')` (or vice versa). Verify whichever one is actually written today before committing.

### 6.2 No polyfills found

- `crypto.randomUUID` defensive checks at `state.ts:14-17` and `useChatDraftAttachments.ts:112-114` are reasonable safeguards, not legacy.

Recommendation: KEEP.

### 6.3 No feature flags found

- Searched `VITE_FEATURE`, `useFeatureFlag`, `FEATURE_FLAG`, `FeatureFlag` — none. There are no flagged dual-render paths.

---

## Summary table

| # | File:line | Action | Notes |
|---|-----------|--------|-------|
| 1.1 | `src/api/client.ts:239-244` (+all `modules/*.ts` call sites) | KEEP (then DELETE) | Drop after backend gateway envelope is unified |
| 1.2 | `src/api/modules/messages.ts:74` | KEEP | Backend still emits `kind` |
| 1.3 | `src/api/modules/personas.ts:380` | CONSOLIDATE | Misleading "legacy" comment; endpoints active |
| 1.4 | `src/api/modules/memory.ts:373` | CONSOLIDATE | Delete misleading comment |
| 1.5 | `src/api/index.ts:29` | KEEP | Real name-collision alias |
| 1.6 | `src/api/client.ts:260, 286-291` | DELETE | `auth_token` and `/login` are dead |
| 2.1 | `src/domain/chat/state.ts:392-414` | CONSOLIDATE → DELETE | Drop camelCase ux-plan fallbacks; update tests |
| 2.2 | `src/domain/chat/state.ts:421` | KEEP | Defensive against pre-`kind` history rows |
| 2.4 | `src/domain/chat/state.ts:428` (timestamps) | KEEP | Old history rows may be seconds-based |
| 2.6 | `src/realtime/store-projection.ts:31-64` | CONSOLIDATE | Round-trip helper deletable after store refactor |
| 2.7 | `src/domain/chat/state.ts:737-744, 762-773` | KEEP | Backend still emits canonical event for rhythm turns |
| 3.1 | `src/realtime/store-projection.ts:77, 136` | DELETE | `personaId` camelCase fallback has no live emitter |
| 3.2 | `src/realtime/store-projection.ts:191-207` | KEEP (then DELETE) | Re-audit after backend phase-5 refactor settles |
| 4.1 | `src/api/client.ts:260, 288`, `src/constants/app.ts:54` | DELETE | Dead key |
| 4.2 | `src/__tests__/chatShell.test.tsx:104-111` | KEEP | Cheap regression guard |
| 4.3 | `OnboardingFlow.tsx:28`, `pages/Onboarding.tsx:8` | CONSOLIDATE | Duplicated `STORAGE_KEY` constant |
| 5.1 | `__tests__/pluginsApi.test.ts:53-77` | linked to 1.1 | Delete with 1.1 |
| 5.2 | `__tests__/realtimeProvider.test.tsx:369-405` | linked to 3.2 | Delete with 3.2 |
| 5.4 | `__tests__/chatTraceState.test.ts:735, 763, 798, 838, 916, 954, 977` | linked to 2.1 | Update with 2.1 |
| 6.1 | `src/stores/theme.ts:11` vs `src/constants/app.ts:56` | CONSOLIDATE | Pick one theme storage key |

## Confident DELETE candidates (no behavior risk)

1. `auth_token` localStorage path (1.6 / 4.1) — `src/api/client.ts:260, 286-291`, `src/constants/app.ts:54`.
2. `personaId` camelCase fallback (3.1) — `src/realtime/store-projection.ts:77, 136`.
3. The misleading "legacy" / "backward compatibility" comments at `src/api/modules/personas.ts:380` and `src/api/modules/memory.ts:373` — pure doc cleanup.

## Items that are legacy in name only

- `memoryApi` (`memory.ts:373`) — the comment claims "legacy" but the object is the only memory client and is in active use.
- `personasApi` generation endpoints (`personas.ts:380`) — comment claims "legacy" but they are the live generation pipeline.
