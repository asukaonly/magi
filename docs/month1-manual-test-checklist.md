# Month 1 Manual Test Checklist

## Purpose

This checklist defines the minimum manual verification pass for the Month 1 runtime goals.

It focuses on the main product path:

- onboarding to first usable message
- direct chat
- tool execution
- explicit memory recall
- explore and orchestration behavior
- plugin lifecycle
- settings persistence and restart behavior

This document is intentionally narrow. It is not a full release checklist.

## Test Session Metadata

- Tester:
- Date:
- Build or commit:
- Platform:
- Runtime mode: `web` / `desktop`
- Notes:

## Environment Preconditions

- The app starts successfully.
- A valid LLM provider is configured.
- At least one builtin tool is enabled.
- At least one provider-backed tool is enabled if that scenario will be tested.
- The plugin management page is reachable.
- The tester can restart the app during the session.

## Result Legend

- `PASS`: behavior matches expectation
- `FAIL`: behavior is incorrect or broken
- `BLOCKED`: test could not be completed because of setup or environment issues

## Core Checklist

### 1. Onboarding To First Message

**Goal:** A new or reset user can reach a usable chat state without runtime initialization errors.

**Steps:**

1. Start from a fresh or onboarding-incomplete state.
2. Open the app.
3. Complete the minimum onboarding flow.
4. Send the first simple message.

**Expected Result:**

- The app routes into onboarding first.
- Onboarding completes without crashing or trapping the user.
- The app enters the main chat surface after onboarding.
- The first message receives a response.
- No runtime or configuration initialization error is shown.

**Status:** `PASS / FAIL / BLOCKED`

**Notes:**

### 2. Direct Chat Response

**Goal:** A simple request that does not need tools returns a direct answer and preserves short conversation continuity.

**Steps:**

1. Ask a simple question that should not require tools.
2. Ask one follow-up question that depends on the previous answer.

**Expected Result:**

- The first reply is returned normally.
- The second reply still understands the immediate conversation context.
- The conversation does not reset or lose the current topic between turns.

**Status:** `PASS / FAIL / BLOCKED`

**Notes:**

### 3. Builtin Tool Success Path

**Goal:** A builtin tool request is routed correctly and produces a user-facing answer based on tool output.

**Steps:**

1. Send a request that clearly requires an enabled builtin tool.
2. Wait for the response.

**Expected Result:**

- The request completes successfully.
- The answer reflects tool output rather than a generic guess.
- The UI remains responsive after the tool call finishes.

**Status:** `PASS / FAIL / BLOCKED`

**Notes:**

### 4. Tool Failure Path

**Goal:** A failed tool call does not break the chat session.

**Steps:**

1. Trigger a tool request with intentionally invalid or unavailable input.
2. Observe the response.
3. Send a normal message immediately afterward.

**Expected Result:**

- The failure is surfaced clearly.
- The app does not hang or crash.
- A follow-up normal message still works in the same session.

**Status:** `PASS / FAIL / BLOCKED`

**Notes:**

### 5. Provider-Backed Tool Success Path

**Goal:** A provider-backed tool can be called successfully with valid credentials and configuration.

**Steps:**

1. Confirm the provider-backed tool is configured.
2. Send a request that requires that tool.

**Expected Result:**

- The request succeeds with provider-backed data.
- The result is returned in a user-facing format.
- The app does not silently fall back to a fabricated answer.

**Status:** `PASS / FAIL / BLOCKED`

**Notes:**

### 6. Explicit Memory Recall Hit

**Goal:** The app can explicitly recall a fact from earlier interaction instead of guessing.

**Steps:**

1. Tell the assistant one specific fact.
2. Send one or two unrelated messages.
3. Ask the assistant to recall the earlier fact explicitly.

**Expected Result:**

- The assistant returns the earlier fact correctly.
- The answer behaves like a recall, not a fresh invention.

**Status:** `PASS / FAIL / BLOCKED`

**Notes:**

### 7. Explicit Memory Recall Miss

**Goal:** The app does not invent history when recall data is missing.

**Steps:**

1. Ask about a prior fact or event that was never provided.

**Expected Result:**

- The assistant clearly indicates that the information could not be found.
- The response does not fabricate a fake prior memory.

**Status:** `PASS / FAIL / BLOCKED`

**Notes:**

### 8. Explore Or Large Task Request

**Goal:** A large request that should decompose still returns a stable final answer.

**Steps:**

1. Send a request that is too large for a single direct answer.
2. Wait for the system to finish.

**Expected Result:**

- The app does not fail immediately or respond with a shallow one-line answer.
- The final answer is aggregated and coherent.
- The session remains usable afterward.

**Status:** `PASS / FAIL / BLOCKED`

**Notes:**

### 9. Plugin Disable And Enable

**Goal:** Plugin state changes are reflected in the product surface and runtime behavior.

**Steps:**

1. Open the plugin or extension management surface.
2. Disable a plugin that contributes visible capability.
3. Confirm the state change.
4. Re-enable the same plugin.

**Expected Result:**

- Disable succeeds and the plugin shows as disabled.
- Re-enable succeeds and the plugin shows as enabled again.
- The state does not drift between UI and backend behavior.

**Status:** `PASS / FAIL / BLOCKED`

**Notes:**

### 10. Plugin Reload And Rescan

**Goal:** Reload and rescan actions complete without corrupting plugin state.

**Steps:**

1. Reload a plugin from the plugin management surface.
2. Trigger a plugin rescan.

**Expected Result:**

- Reload completes without error.
- Rescan completes without error.
- The plugin list remains consistent after both actions.

**Status:** `PASS / FAIL / BLOCKED`

**Notes:**

### 11. Settings Persistence

**Goal:** A changed setting is saved and visible after a refresh.

**Steps:**

1. Change one core setting such as a memory flag, tool setting, or provider-related setting.
2. Save the settings.
3. Refresh the page or reopen the settings surface.

**Expected Result:**

- The save action succeeds.
- The modified setting still shows the updated value after refresh.

**Status:** `PASS / FAIL / BLOCKED`

**Notes:**

### 12. Restart Persistence

**Goal:** Core configuration survives a full app restart.

**Steps:**

1. Change and save one visible configuration value.
2. Restart the app.
3. Reopen the relevant settings surface.
4. Send one normal message.

**Expected Result:**

- The changed setting is still present after restart.
- The app remains usable after restart.
- Chat still works after restart with the saved configuration.

**Status:** `PASS / FAIL / BLOCKED`

**Notes:**

## Exit Criteria

Month 1 manual verification is acceptable when:

- all critical core scenarios complete without crash
- direct chat works
- at least one builtin tool succeeds
- explicit memory recall hit and miss both behave correctly
- settings survive refresh and restart
- plugin lifecycle actions do not leave the system in a broken state

If any of the following fail, the build should be treated as not ready for Month 1 sign-off:

- onboarding cannot reach first usable message
- normal chat breaks
- failed tool calls poison the session
- recall miss fabricates prior history
- restart loses saved settings
